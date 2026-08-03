from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import openpyxl
from lxml import etree

from crs_fatca_generator.infrastructure.paths import default_crs_schema, resource_path
from crs_fatca_generator.services.xml_helpers import (
    CRS_CFC_NS,
    CRS_FTCA_V1_NS,
    CRS_ISO_NS,
    CRS_NS,
    CRS_STF_NS,
    CRS_V3_NS,
    XSI_NS,
    atomic_write,
    q,
    sanitize_xml_tree,
    strip_invalid_xml_chars,
)
from crs_fatca_generator.services.xml_validator import XmlValidator


CRS_V2_SCHEMA_LOCATION = f"{CRS_NS} CrsXML_v2.0.xsd"
CRS_V3_SCHEMA_LOCATION = f"{CRS_V3_NS} CrsXML_v3.0.xsd"
SUPPORTED_ERROR_CODES = {"CRS0024", "KY0008"}
DOC_REF_PATTERN = re.compile(r"\b(KY[A-Za-z0-9]+)\b")


@dataclass
class CrsErrorInstruction:
    doc_ref_id: str
    codes: set[str]
    rows: list[str]


@dataclass
class CrsCorrectionResult:
    input_path: Path
    output_path: Path
    crs_version: str
    doc_type_indic: str
    old_message_ref_id: str
    new_message_ref_id: str
    docs_updated: int = 0
    corr_doc_refs_added: int = 0
    closed_accounts: int = 0
    balances_zeroed: int = 0
    zero_payments_added_or_updated: int = 0
    organisation_tins_converted: int = 0
    organisation_ins_converted: int = 0
    v3_only_elements_removed: int = 0
    v3_only_elements_added: int = 0
    validation_errors: int = 0
    data_excel_path: Path | None = None
    errors_excel_path: Path | None = None
    error_rows_loaded: int = 0
    error_rules_mapped: int = 0
    target_doc_refs: int = 0
    matched_doc_refs: int = 0
    unmatched_doc_refs: int = 0
    account_reports_removed: int = 0
    reporting_fi_resent: int = 0
    message_type_indic: str = ""
    unknown_error_codes: int = 0


class CrsCorrectionService:
    def correct_file(
        self,
        input_path: Path,
        output_path: Path | None = None,
        crs_version: str = "v2",
        doc_type_indic: str = "OECD2",
        zero_closed_balance: bool = True,
        add_zero_payment_for_closed: bool = True,
        data_excel_path: Path | None = None,
        errors_excel_path: Path | None = None,
    ) -> CrsCorrectionResult:
        if not input_path.exists():
            raise FileNotFoundError(f"XML CRS nao encontrado: {input_path}")
        if data_excel_path and not data_excel_path.exists():
            raise FileNotFoundError(f"Excel de dados nao encontrado: {data_excel_path}")
        if errors_excel_path and not errors_excel_path.exists():
            raise FileNotFoundError(f"Excel de erros nao encontrado: {errors_excel_path}")
        doc_type = _normalize_doc_type(doc_type_indic)
        version = _normalize_crs_version(crs_version)
        error_instructions = _load_error_instructions(errors_excel_path) if errors_excel_path else {}
        target_doc_refs = set(error_instructions)
        target = output_path or input_path.with_name(f"{input_path.stem}_corrigido_{version}_{doc_type}{input_path.suffix or '.xml'}")
        raw = input_path.read_text(encoding="utf-8", errors="replace")
        root = self._parse_xml(strip_invalid_xml_chars(raw))
        if version == "v3":
            root = self._force_crs_v3(root)
        else:
            root = self._force_crs_v2(root)
        old_message_ref = _first_text(root, ".//*[local-name()='MessageRefId']") or "KY2025BRFI107442"
        new_message_ref = _new_identifier(old_message_ref, "MSG", 0)
        result = CrsCorrectionResult(input_path, target, version, doc_type, old_message_ref, new_message_ref)
        result.data_excel_path = data_excel_path
        result.errors_excel_path = errors_excel_path
        result.error_rows_loaded = sum(len(item.rows) for item in error_instructions.values())
        result.error_rules_mapped = sum(len(item.codes) for item in error_instructions.values())
        result.target_doc_refs = len(target_doc_refs)
        self._set_message_spec(root, result)
        if version == "v3":
            result.organisation_ins_converted = self._convert_account_holder_organisation_in_to_tin(root)
            result.v3_only_elements_added = self._ensure_v3_required_elements(root)
        else:
            result.v3_only_elements_removed = self._remove_v3_only_elements(root)
            result.organisation_tins_converted = self._convert_organisation_tin_to_in(root)
        if doc_type == "OECD2" and target_doc_refs:
            result.account_reports_removed = self._remove_untargeted_account_reports(root, target_doc_refs)
        if error_instructions:
            matched = self._apply_error_instruction_rules(root, result, error_instructions, zero_closed_balance, add_zero_payment_for_closed)
            result.matched_doc_refs = len(matched)
            result.unmatched_doc_refs = len(target_doc_refs - matched)
        elif zero_closed_balance or add_zero_payment_for_closed:
            self._apply_closed_account_rules(root, result, zero_closed_balance, add_zero_payment_for_closed)
        self._set_doc_specs(root, result, target_doc_refs)
        sanitize_xml_tree(root)
        atomic_write(etree.ElementTree(root), target, True)
        result.validation_errors = len(XmlValidator().validate_file(target, _schema_for_version(version), "crs"))
        return result

    def _parse_xml(self, text: str) -> etree._Element:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, remove_blank_text=True)
        return etree.fromstring(text.encode("utf-8"), parser)

    def _force_crs_v2(self, root: etree._Element) -> etree._Element:
        for element in root.iter():
            qname = etree.QName(element)
            if qname.namespace == CRS_V3_NS:
                element.tag = q(CRS_NS, qname.localname)
        root = _rebuild_root_with_crs_prefix(root, CRS_NS)
        root.set("version", "2.0")
        root.set(q(XSI_NS, "schemaLocation"), CRS_V2_SCHEMA_LOCATION)
        return root

    def _force_crs_v3(self, root: etree._Element) -> etree._Element:
        for element in root.iter():
            qname = etree.QName(element)
            if qname.namespace == CRS_NS:
                element.tag = q(CRS_V3_NS, qname.localname)
        root = _rebuild_root_with_crs_prefix(root, CRS_V3_NS)
        root.set("version", "3.0")
        root.set(q(XSI_NS, "schemaLocation"), CRS_V3_SCHEMA_LOCATION)
        return root

    def _set_message_spec(self, root: etree._Element, result: CrsCorrectionResult) -> None:
        message_ref = _first(root, ".//*[local-name()='MessageSpec']/*[local-name()='MessageRefId']")
        if message_ref is not None:
            message_ref.text = result.new_message_ref_id
        message_spec = _first(root, ".//*[local-name()='MessageSpec']")
        if message_spec is None:
            return
        message_type = _first(message_spec, "./*[local-name()='MessageTypeIndic']")
        if result.doc_type_indic == "OECD2":
            result.message_type_indic = "CRS702"
        else:
            result.message_type_indic = "CRS701"
        if message_type is not None:
            message_type.text = result.message_type_indic
        _remove_children(message_spec, "CorrMessageRefId")

    def _set_doc_specs(self, root: etree._Element, result: CrsCorrectionResult, target_doc_refs: set[str]) -> None:
        for index, doc_spec in enumerate(root.xpath(".//*[local-name()='DocSpec']"), 1):
            old_doc_ref = _child_text(doc_spec, "DocRefId") or f"{result.old_message_ref_id}DOC{index:06d}"
            if result.doc_type_indic == "OECD2" and _is_reporting_fi_doc_spec(doc_spec):
                _set_child_text(doc_spec, "DocTypeIndic", "OECD0")
                _set_child_text(doc_spec, "DocRefId", old_doc_ref)
                _remove_children(doc_spec, "CorrMessageRefId")
                _remove_children(doc_spec, "CorrDocRefId")
                result.reporting_fi_resent += 1
            elif result.doc_type_indic == "OECD2":
                if target_doc_refs and old_doc_ref not in target_doc_refs:
                    continue
                _set_child_text(doc_spec, "DocTypeIndic", "OECD2")
                _set_child_text(doc_spec, "DocRefId", _new_identifier(old_doc_ref, "DOC", index))
                _remove_children(doc_spec, "CorrMessageRefId")
                _ensure_child_text(doc_spec, CRS_STF_NS, "CorrDocRefId", old_doc_ref, after_local_name="DocRefId")
                result.corr_doc_refs_added += 1
            else:
                _set_child_text(doc_spec, "DocTypeIndic", result.doc_type_indic)
                _set_child_text(doc_spec, "DocRefId", _new_identifier(old_doc_ref, "DOC", index))
                _remove_children(doc_spec, "CorrMessageRefId")
                _remove_children(doc_spec, "CorrDocRefId")
            result.docs_updated += 1

    def _remove_untargeted_account_reports(self, root: etree._Element, target_doc_refs: set[str]) -> int:
        removed = 0
        for account in list(root.xpath(".//*[local-name()='AccountReport']")):
            doc_ref = _doc_ref_for_correctable(account)
            if doc_ref not in target_doc_refs:
                parent = account.getparent()
                if parent is not None:
                    parent.remove(account)
                    removed += 1
        return removed

    def _remove_v3_only_elements(self, root: etree._Element) -> int:
        removed = 0
        for element in list(root.xpath(".//*[local-name()='SelfCert' or local-name()='DDProcedure' or local-name()='AccountType' or local-name()='JointAccount' or local-name()='EquityInterestType']")):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
                removed += 1
        return removed

    def _convert_organisation_tin_to_in(self, root: etree._Element) -> int:
        converted = 0
        for tin in root.xpath(".//*[local-name()='AccountHolder']/*[local-name()='Organisation']/*[local-name()='TIN']"):
            tin.tag = q(CRS_NS, "IN")
            converted += 1
        return converted

    def _convert_account_holder_organisation_in_to_tin(self, root: etree._Element) -> int:
        converted = 0
        for item in root.xpath(".//*[local-name()='AccountHolder']/*[local-name()='Organisation']/*[local-name()='IN']"):
            item.tag = q(CRS_V3_NS, "TIN")
            converted += 1
        return converted

    def _ensure_v3_required_elements(self, root: etree._Element) -> int:
        added = 0
        for holder in root.xpath(".//*[local-name()='AccountHolder']"):
            if _first(holder, "./*[local-name()='SelfCert']") is None:
                marker = _first(holder, "./*[local-name()='Individual' or local-name()='Organisation']")
                self_cert = etree.Element(q(CRS_V3_NS, "SelfCert"))
                self_cert.text = "CRS901"
                insert_at = list(holder).index(marker) if marker is not None else 0
                holder.insert(insert_at, self_cert)
                added += 1
        for controlling in root.xpath(".//*[local-name()='ControllingPerson']"):
            if _first(controlling, "./*[local-name()='SelfCert']") is None:
                self_cert = etree.Element(q(CRS_V3_NS, "SelfCert"))
                self_cert.text = "CRS1001"
                controlling.append(self_cert)
                added += 1
        for account in root.xpath(".//*[local-name()='AccountReport']"):
            if _first(account, "./*[local-name()='DDProcedure']") is None:
                dd = etree.Element(q(CRS_V3_NS, "DDProcedure"))
                dd.text = "CRS1201"
                _insert_after_last(account, dd, {"Payment", "AccountBalance"})
                added += 1
            if _first(account, "./*[local-name()='AccountType']") is None:
                account_type = etree.Element(q(CRS_V3_NS, "AccountType"))
                account_type.text = "CRS1101"
                dd = _first(account, "./*[local-name()='DDProcedure']")
                insert_at = list(account).index(dd) + 1 if dd is not None else len(account)
                account.insert(insert_at, account_type)
                added += 1
        return added

    def _apply_closed_account_rules(
        self,
        root: etree._Element,
        result: CrsCorrectionResult,
        zero_closed_balance: bool,
        add_zero_payment_for_closed: bool,
    ) -> None:
        for account in root.xpath(".//*[local-name()='AccountReport']"):
            account_number = _first(account, "./*[local-name()='AccountNumber']")
            if account_number is None or not _is_true(account_number.get("ClosedAccount")):
                continue
            result.closed_accounts += 1
            balance = _first(account, "./*[local-name()='AccountBalance']")
            if zero_closed_balance and balance is not None:
                balance.text = "0.00"
                balance.set("currCode", "USD")
                result.balances_zeroed += 1
            if add_zero_payment_for_closed:
                if self._ensure_zero_payment(account):
                    result.zero_payments_added_or_updated += 1

    def _apply_error_instruction_rules(
        self,
        root: etree._Element,
        result: CrsCorrectionResult,
        instructions: dict[str, "CrsErrorInstruction"],
        zero_closed_balance: bool,
        add_zero_payment_for_closed: bool,
    ) -> set[str]:
        matched: set[str] = set()
        for account in root.xpath(".//*[local-name()='AccountReport']"):
            doc_ref = _doc_ref_for_correctable(account)
            if not doc_ref or doc_ref not in instructions:
                continue
            instruction = instructions[doc_ref]
            matched.add(doc_ref)
            codes = instruction.codes
            if "CRS0024" in codes:
                self._mark_account_closed(account)
                if zero_closed_balance:
                    balance = _first(account, "./*[local-name()='AccountBalance']")
                    if balance is not None:
                        balance.text = "0.00"
                        balance.set("currCode", "USD")
                        result.balances_zeroed += 1
                if add_zero_payment_for_closed and self._ensure_zero_payment(account):
                    result.zero_payments_added_or_updated += 1
                result.closed_accounts += 1
            if "KY0008" in codes:
                self._mark_account_closed(account)
                if add_zero_payment_for_closed and self._ensure_zero_payment(account):
                    result.zero_payments_added_or_updated += 1
                if "CRS0024" not in codes:
                    result.closed_accounts += 1
            result.unknown_error_codes += len(codes - SUPPORTED_ERROR_CODES)
        return matched

    def _mark_account_closed(self, account: etree._Element) -> None:
        account_number = _first(account, "./*[local-name()='AccountNumber']")
        if account_number is not None:
            account_number.set("ClosedAccount", "true")

    def _ensure_zero_payment(self, account: etree._Element) -> bool:
        account_ns = etree.QName(account).namespace or CRS_NS
        for payment in account.xpath("./*[local-name()='Payment']"):
            if _child_text(payment, "Type") == "CRS501":
                amount = _first(payment, "./*[local-name()='PaymentAmnt']")
                if amount is None:
                    amount = etree.SubElement(payment, q(account_ns, "PaymentAmnt"), currCode="USD")
                amount.text = "0.00"
                amount.set("currCode", "USD")
                return True
        payment = etree.Element(q(account_ns, "Payment"))
        etree.SubElement(payment, q(account_ns, "Type")).text = "CRS501"
        etree.SubElement(payment, q(account_ns, "PaymentAmnt"), currCode="USD").text = "0.00"
        balance = _first(account, "./*[local-name()='AccountBalance']")
        insert_at = list(account).index(balance) + 1 if balance is not None else len(account)
        account.insert(insert_at, payment)
        return True


def _normalize_doc_type(value: str) -> str:
    text = str(value or "").strip().upper()
    return text if text in {"OECD1", "OECD2"} else "OECD2"


def _normalize_crs_version(value: str) -> str:
    text = str(value or "").strip().lower()
    return "v3" if text in {"v3", "3", "3.0", "crs v3", "crs xml v3"} else "v2"


def _schema_for_version(version: str) -> Path:
    if version == "v3":
        return resource_path("schemas", "crs", "v3_0", "CrsXML_v3.0.xsd")
    return default_crs_schema()


def _load_error_instructions(path: Path) -> dict[str, CrsErrorInstruction]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    instructions: dict[str, CrsErrorInstruction] = {}
    try:
        for sheet in workbook.worksheets:
            for row_index, row in enumerate(sheet.iter_rows(min_col=1, max_col=2, values_only=True), 1):
                code = str(row[0] or "").strip().upper()
                message = str(row[1] or "").strip()
                if row_index == 1 and code in {"CODE", "CODIGO", "CODIGO DO ERRO"}:
                    continue
                if not code or not message:
                    continue
                doc_ref = _extract_doc_ref_id(message)
                if not doc_ref:
                    continue
                instruction = instructions.setdefault(doc_ref, CrsErrorInstruction(doc_ref, set(), []))
                instruction.codes.add(code)
                instruction.rows.append(f"{sheet.title}:{row_index}")
    finally:
        workbook.close()
    return instructions


def _extract_doc_ref_id(message: str) -> str:
    match = DOC_REF_PATTERN.search(str(message or ""))
    return match.group(1) if match else ""


def _doc_ref_for_correctable(element: etree._Element) -> str:
    return _first_text(element, ".//*[local-name()='DocSpec']/*[local-name()='DocRefId']")


def _is_reporting_fi_doc_spec(doc_spec: etree._Element) -> bool:
    return _ancestor_local_name(doc_spec, "ReportingFI")


def _ancestor_local_name(element: etree._Element, local_name: str) -> bool:
    parent = element.getparent()
    while parent is not None:
        if etree.QName(parent).localname == local_name:
            return True
        parent = parent.getparent()
    return False


def _rebuild_root_with_crs_prefix(root: etree._Element, crs_ns: str) -> etree._Element:
    nsmap = {
        "crs": crs_ns,
        "stf": CRS_STF_NS,
        "cfc": CRS_CFC_NS,
        "iso": CRS_ISO_NS,
        "ftc": CRS_FTCA_V1_NS,
        "xsi": XSI_NS,
    }
    rebuilt = etree.Element(q(crs_ns, "CRS_OECD"), nsmap=nsmap)
    for name, value in root.attrib.items():
        rebuilt.set(name, value)
    rebuilt.text = root.text
    rebuilt.tail = root.tail
    while len(root):
        rebuilt.append(root[0])
    return rebuilt


def _new_identifier(old_value: str, kind: str, sequence: int) -> str:
    clean = "".join(char for char in str(old_value or "") if char.isalnum()) or "KY2025BRFI107442"
    suffix = f"C{datetime.now():%Y%m%d%H%M%S}{kind}{sequence:06d}"
    return f"{clean[: max(1, 170 - len(suffix))]}{suffix}"


def _first(root: etree._Element, xpath: str) -> etree._Element | None:
    matches = root.xpath(xpath)
    return matches[0] if matches else None


def _first_text(root: etree._Element, xpath: str) -> str:
    element = _first(root, xpath)
    return str(element.text or "").strip() if element is not None else ""


def _child_text(parent: etree._Element, local_name: str) -> str:
    child = _first(parent, f"./*[local-name()='{local_name}']")
    return str(child.text or "").strip() if child is not None else ""


def _set_child_text(parent: etree._Element, local_name: str, value: str) -> None:
    child = _first(parent, f"./*[local-name()='{local_name}']")
    if child is not None:
        child.text = value


def _ensure_child_text(parent: etree._Element, ns: str, local_name: str, value: str, after_local_name: str) -> None:
    child = _first(parent, f"./*[local-name()='{local_name}']")
    if child is None:
        child = etree.Element(q(ns, local_name))
        after = _first(parent, f"./*[local-name()='{after_local_name}']")
        insert_at = list(parent).index(after) + 1 if after is not None else len(parent)
        parent.insert(insert_at, child)
    child.text = value


def _remove_children(parent: etree._Element, local_name: str) -> None:
    for child in list(parent.xpath(f"./*[local-name()='{local_name}']")):
        parent.remove(child)


def _insert_after_last(parent: etree._Element, child: etree._Element, local_names: set[str]) -> None:
    insert_at = len(parent)
    for index, existing in enumerate(parent):
        if etree.QName(existing).localname in local_names:
            insert_at = index + 1
    parent.insert(insert_at, child)


def _is_true(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {"true", "1", "sim", "s", "yes", "y", "verdadeiro", "x"}
