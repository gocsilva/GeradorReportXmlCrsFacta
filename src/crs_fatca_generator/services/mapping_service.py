from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from crs_fatca_generator.infrastructure.database import IdentifierStore
from crs_fatca_generator.infrastructure.paths import default_output_dir
from crs_fatca_generator.models.domain import (
    AccountReport,
    Address,
    DocSpec,
    MessageSpec,
    Name,
    Party,
    Payment,
    ReportingFI,
    TIN,
    TaxReport,
)
from crs_fatca_generator.models.mapping import MappingProfile, MappingRule, OutputConfig
from crs_fatca_generator.services.controlling_person_service import ControllingPersonRecord
from crs_fatca_generator.services.fatca_missing_tin_policy import DEFAULT_MISSING_US_TIN_POLICY, TECHNICAL_TEST_POLICY, FatcaMissingTinPolicy
from .transformation_service import apply_transformations, country_code, currency_code, is_empty, normalize_text, split_values, to_bool, to_date, to_datetime, to_decimal


SIMPLE_REQUIRED_COLUMNS = [
    "DocumentoCliente",
    "Tipo de documento",
    "NumConta",
    "NomeCliente",
    "SaldoTotal",
    "Endereco",
    "Cidade",
    "Pais",
]

SIMPLE_REQUIRED_ALIASES = {
    "DocumentoCliente": ["DocumentoCliente", "Identification Number / CPF"],
    "Tipo de documento": ["Tipo de documento", "DocumentType"],
    "NumConta": ["NumConta", "AccountNumber"],
    "NomeCliente": ["NomeCliente", "Name"],
    "SaldoTotal": ["SaldoTotal", "Saldo da conta em 31/12/2025", "Account Balance"],
    "Endereco": ["Endereco", "Street", "Address"],
    "Cidade": ["Cidade", "City"],
    "Pais": ["Pais", "Country", "Tax Residence", "Pais de Residencia fiscal", "País de Residencia fiscal"],
}

PROJECT_DEFAULT_CURRENCY = "USD"
DITC_DEFAULT_PREFIX = "KY2025BRFI107442"

logger = logging.getLogger(__name__)


def missing_simple_columns(headers: list[str]) -> list[str]:
    found = {header.strip().casefold() for header in headers}
    missing: list[str] = []
    for column in SIMPLE_REQUIRED_COLUMNS:
        aliases = SIMPLE_REQUIRED_ALIASES.get(column, [column])
        if not any(alias.casefold() in found for alias in aliases):
            missing.append(column)
    return missing


def simple_output_paths(excel_path: Path) -> OutputConfig:
    output_dir = default_output_dir(excel_path)
    stem = excel_path.stem
    return OutputConfig(
        crs_path=str(output_dir / f"{stem}_CRS.xml"),
        fatca_path=str(output_dir / f"{stem}_FATCA.xml"),
        pretty_print=True,
    )


class MappingService:
    def __init__(self, identifier_store: IdentifierStore | None = None) -> None:
        self.identifier_store = identifier_store or IdentifierStore()
        self._sequence_next: dict[str, int] = {}

    def build_report(
        self,
        kind: str,
        rows: list[dict[str, Any]],
        profile: MappingProfile,
        file_hash: str = "",
        progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
    ) -> TaxReport:
        if not rows:
            rows = [{"_excel_row": 0}]
        first = rows[0]
        message = self._message_spec(kind, first, profile, file_hash)
        reporting_fi = self._reporting_fi(kind, first, profile, file_hash)
        nil_enabled = self.value("nil_report.enabled", first, profile).lower() in {"sim", "s", "yes", "true", "1"}
        if kind == "fatca" and nil_enabled:
            nil = DocSpec(
                self._doc_type(kind, self.value("account.doc_type_indic", first, profile, default="FATCA1")),
                self._explicit_identifier_value("account.doc_ref_id", first, profile) or self._new_id("fatca-nil-doc", profile, file_hash),
            )
            return TaxReport(kind, message, reporting_fi, [], nil)
        accounts = self._accounts(kind, rows, profile, file_hash, progress_callback)
        return TaxReport(kind, message, reporting_fi, accounts)

    def value(self, field: str, row: dict[str, Any], profile: MappingProfile, default: str = "") -> str:
        rule = profile.field_mappings.get(field, MappingRule("empty"))
        raw: Any = ""
        if rule.source == "fixed":
            raw = rule.fixed_value
        elif rule.source == "column" and rule.column:
            raw = row.get(rule.column, "")
        elif rule.source == "calculated" and rule.column:
            columns = [part.strip() for part in rule.column.replace("|", ";").split(";") if part.strip()]
            raw = ", ".join(normalize_text(row.get(column, "")) for column in columns if normalize_text(row.get(column, "")))
        elif rule.source == "auto":
            raw = self._auto_value(field, profile)
        elif rule.source == "empty":
            raw = ""
        if is_empty(raw):
            return default
        try:
            value = apply_transformations(raw, rule.transformations)
        except ValueError:
            raise
        return value if not is_empty(value) else default

    def _message_spec(self, kind: str, row: dict[str, Any], profile: MappingProfile, file_hash: str) -> MessageSpec:
        message_ref = self._explicit_identifier_value("message.message_ref_id", row, profile)
        if not message_ref:
            message_ref = self._new_id(f"{kind}-message", profile, file_hash)
        self.identifier_store.add(f"{kind}-message", message_ref, file_hash)
        reporting_period = self.value("message.reporting_period", row, profile)
        if reporting_period:
            reporting_period = to_date(reporting_period)
        timestamp = self.value("message.timestamp", row, profile)
        if timestamp:
            timestamp = to_datetime(timestamp)
        else:
            timestamp = datetime.now().replace(microsecond=0).isoformat()
        warning = self.value("message.warning", row, profile)
        if kind == "fatca" and not warning and self.value("fatca.missing_us_tin_policy", row, profile, TECHNICAL_TEST_POLICY) == TECHNICAL_TEST_POLICY:
            warning = "ARQUIVO TECNICO DE TESTE: tratamento do US Tax ID pendente de confirmacao fiscal; nao usar para envio definitivo."
        return MessageSpec(
            sending_company_in=self.value("message.sending_company_in", row, profile),
            transmitting_country=country_code(self._message_value(kind, "transmitting_country", row, profile, "KY")),
            receiving_country=country_code(self._message_value(kind, "receiving_country", row, profile, "US" if kind == "fatca" else "BR")),
            message_type="FATCA" if kind == "fatca" else "CRS",
            message_ref_id=message_ref,
            reporting_period=reporting_period or f"{datetime.now().year - 1}-12-31",
            timestamp=timestamp,
            message_type_indic=self.value("message.message_type_indic", row, profile, "CRS701" if kind == "crs" else ""),
            corr_message_ref_ids=split_values(self.value("message.corr_message_ref_id", row, profile)),
            warning=warning,
            contact=self.value("message.contact", row, profile),
        )

    def _reporting_fi(self, kind: str, row: dict[str, Any], profile: MappingProfile, file_hash: str) -> ReportingFI:
        name = self.value("reporting_fi.name", row, profile, "Instituicao Financeira")
        party = Party(
            kind="organisation",
            res_country_codes=split_values(self.value("reporting_fi.res_country", row, profile, profile.identifier_config.country)),
            name=Name(organisation_name=name),
            address=Address(
                country_code=country_code(self.value("reporting_fi.address_country", row, profile, profile.identifier_config.country)),
                address_free=self.value("reporting_fi.address_free", row, profile, "Endereco nao informado"),
            ),
            tins=[
                TIN(
                    self.value("reporting_fi.in", row, profile),
                    country_code(self.value("reporting_fi.issued_by", row, profile, profile.identifier_config.country)),
                )
            ]
            if self.value("reporting_fi.in", row, profile)
            else [],
        )
        doc_type = self._doc_type(kind, self.value("reporting_fi.doc_type_indic", row, profile, "FATCA1" if kind == "fatca" else "OECD1"))
        doc_ref = self._explicit_identifier_value("reporting_fi.doc_ref_id", row, profile) or self._new_id(f"{kind}-fi-doc", profile, file_hash)
        self.identifier_store.add(f"{kind}-fi-doc", doc_ref, file_hash)
        return ReportingFI(party, DocSpec(doc_type, doc_ref), self.value("reporting_fi.filer_category", row, profile, "FATCA601"))

    def _accounts(
        self,
        kind: str,
        rows: list[dict[str, Any]],
        profile: MappingProfile,
        file_hash: str,
        progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
    ) -> list[AccountReport]:
        groups: dict[str, list[dict[str, Any]]] = {}
        key_col = profile.grouping.account_key
        for row in rows:
            key = str(row.get(key_col, "") or self.value("account.account_number", row, profile) or row.get("_excel_row"))
            groups.setdefault(key, []).append(row)
        accounts: list[AccountReport] = []
        total = len(groups)
        for index, group_rows in enumerate(groups.values(), 1):
            row = group_rows[0]
            if progress_callback and (index == 1 or index % 50 == 0 or index == total):
                progress_callback(index, total, row)
            doc_type = self._doc_type(kind, self.value("account.doc_type_indic", row, profile, "FATCA1" if kind == "fatca" else "OECD1"))
            doc_ref = self._explicit_identifier_value("account.doc_ref_id", row, profile) or self._new_id(f"{kind}-account-doc", profile, file_hash)
            self.identifier_store.add(f"{kind}-account-doc", doc_ref, file_hash)
            account = AccountReport(
                doc_spec=DocSpec(doc_type, doc_ref),
                account_number=self.value("account.account_number", row, profile, f"ACC-{row.get('_excel_row', 1)}"),
                account_number_type=self.value("account.account_number_type", row, profile, "OECD602"),
                closed_account=self._optional_bool(self.value("account.closed", row, profile)),
                account_holder=self._holder(kind, row, profile),
                controlling_persons=self._controlling_persons(row, profile) if kind == "crs" else [],
                substantial_owners=self._substantial_owners(row, profile) if kind == "fatca" else [],
                account_balance=to_decimal(self.value("account.balance", row, profile, "0")),
                account_currency=self._currency(kind, row, profile),
                payments=self._payments(kind, group_rows, profile),
                crs_dd_procedure=self.value("account.crs_dd_procedure", row, profile, "CRS1201"),
                crs_account_type=self.value("account.crs_account_type", row, profile, "CRS1101"),
                crs_joint_account_number=self.value("account.crs_joint_account_number", row, profile),
            )
            accounts.append(account)
        return accounts

    def _holder(self, kind: str, row: dict[str, Any], profile: MappingProfile) -> Party:
        holder_kind = self.value("holder.kind", row, profile, "individual").lower()
        is_org = holder_kind.startswith(("org", "ent", "jur", "organisation", "organization"))
        tin_issued_by = country_code(self.value("holder.tin_issued_by", row, profile, str(row.get("_tax_identifier_issued_by", "BR"))))
        fatca_tin_decision = FatcaMissingTinPolicy().decide_xml_representation(row, profile) if kind == "fatca" else None
        tins = fatca_tin_decision.tins if fatca_tin_decision else [TIN(v, tin_issued_by) for v in split_values(self.value("holder.tin", row, profile))]
        acct_holder_type = self.value("holder.acct_holder_type", row, profile, "CRS101" if kind == "crs" else "FATCA101")
        if kind == "fatca" and acct_holder_type.startswith("CRS"):
            acct_holder_type = "FATCA101"
        return Party(
            kind="organisation" if is_org else "individual",
            res_country_codes=[country_code(v) for v in split_values(self.value("holder.res_country", row, profile, "BR"))],
            name=Name(
                first_name=self.value("holder.first_name", row, profile, "Nome"),
                last_name=self.value("holder.last_name", row, profile, "Sobrenome"),
                organisation_name=self.value("holder.organisation_name", row, profile, "Organizacao"),
            ),
            address=Address(
                country_code=country_code(self.value("holder.address_country", row, profile, "BR")),
                address_free=self.value("holder.address_free", row, profile, "Endereco nao informado"),
                legal_address_type=self.value("holder.address_type", row, profile),
            ),
            tins=tins,
            documento_brasileiro=str(row.get("_documento_brasileiro", "")),
            tipo_documento_brasileiro=str(row.get("_tipo_documento_brasileiro", "")),
            cpf=str(row.get("_cpf", "")),
            cnpj=str(row.get("_cnpj", "")),
            fatca_us_tin=tins[0].value if kind == "fatca" and tins else "",
            fatca_us_tin_status=(fatca_tin_decision.status if fatca_tin_decision else str(row.get("_fatca_us_tin_status", ""))),
            fatca_us_tin_reason=(fatca_tin_decision.reason if fatca_tin_decision else str(row.get("_fatca_us_tin_reason", ""))),
            fatca_us_tin_issued_by=tins[0].issued_by if kind == "fatca" and tins else str(row.get("_fatca_us_tin_issued_by", "")),
            fatca_us_tin_policy=(fatca_tin_decision.policy if fatca_tin_decision else str(row.get("_fatca_us_tin_policy", ""))),
            fatca_us_tin_blocking=("sim" if fatca_tin_decision and fatca_tin_decision.blocking else str(row.get("_fatca_us_tin_blocking", ""))),
            birth_date="" if is_org else self.value("holder.birth_date", row, profile),
            acct_holder_type=acct_holder_type,
            crs_self_cert=self.value("holder.crs_self_cert", row, profile, "CRS901"),
        )

    def _payments(self, kind: str, rows: list[dict[str, Any]], profile: MappingProfile) -> list[Payment]:
        payments: list[Payment] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            payment_type = self.value("payment.type", row, profile)
            amount = self.value("payment.amount", row, profile)
            if not payment_type or not amount:
                continue
            currency = self.value("payment.currency", row, profile, self._currency(kind, row, profile))
            item = (payment_type, amount, currency)
            if item in seen:
                continue
            seen.add(item)
            payments.append(Payment(payment_type, to_decimal(amount), currency_code(currency)))
        return payments

    def _controlling_persons(self, row: dict[str, Any], profile: MappingProfile) -> list[Party]:
        prepared_records = [record for record in row.get("_controlling_persons", []) if isinstance(record, ControllingPersonRecord)]
        if prepared_records:
            return [
                Party(
                    kind="individual",
                    res_country_codes=[country_code(record.tax_residence or "BR")],
                    name=Name(first_name=record.first_name or "Nome", last_name=record.last_name or "Sobrenome", name_type=record.name_type),
                    address=Address(
                        country_code(record.country or record.tax_residence or "BR"),
                        address_free=", ".join(part for part in (record.city, record.country) if part) or "Endereco nao informado",
                        legal_address_type=record.address_type,
                    ),
                    tins=[TIN(record.normalized_tin, country_code(record.tin_issued_by or "BR"))],
                    birth_date=record.birth_date,
                    crs_controlling_person_types=[record.controlling_person_type or "CRS801"],
                    crs_controlling_self_cert="CRS1001",
                )
                for record in prepared_records
            ]
        first_names = split_values(self.value("controlling.first_name", row, profile))
        last_names = split_values(self.value("controlling.last_name", row, profile))
        if not first_names and not last_names:
            return []
        countries = split_values(self.value("controlling.res_country", row, profile, "BR"))
        addresses = split_values(self.value("controlling.address_free", row, profile, "Endereco nao informado"))
        address_countries = split_values(self.value("controlling.address_country", row, profile, "BR"))
        tins = split_values(self.value("controlling.tin", row, profile))
        tin_country = country_code(self.value("controlling.tin_issued_by", row, profile, "BR"))
        types = split_values(self.value("controlling.type", row, profile, "CRS801"))
        self_cert = self.value("controlling.self_cert", row, profile, "CRS1001")
        count = max(len(first_names), len(last_names), 1)
        parties: list[Party] = []
        for idx in range(count):
            parties.append(
                Party(
                    kind="individual",
                    res_country_codes=[country_code(c) for c in (countries or ["BR"])],
                    name=Name(
                        first_name=first_names[idx] if idx < len(first_names) else (first_names[0] if first_names else "Nome"),
                        last_name=last_names[idx] if idx < len(last_names) else (last_names[0] if last_names else "Sobrenome"),
                    ),
                    address=Address(
                        country_code(address_countries[idx] if idx < len(address_countries) else address_countries[0]),
                        address_free=addresses[idx] if idx < len(addresses) else addresses[0],
                    ),
                    tins=[TIN(value, tin_country) for value in tins],
                    crs_controlling_person_types=types,
                    crs_controlling_self_cert=self_cert,
                )
            )
        return parties

    def _substantial_owners(self, row: dict[str, Any], profile: MappingProfile) -> list[Party]:
        first_names = split_values(self.value("substantial.first_name", row, profile))
        last_names = split_values(self.value("substantial.last_name", row, profile))
        org_names = split_values(self.value("substantial.organisation_name", row, profile))
        if not first_names and not last_names and not org_names:
            return []
        kind = self.value("substantial.kind", row, profile, "individual").lower()
        is_org = kind.startswith(("org", "ent", "jur"))
        countries = split_values(self.value("substantial.res_country", row, profile, "BR"))
        addresses = split_values(self.value("substantial.address_free", row, profile, "Endereco nao informado"))
        address_countries = split_values(self.value("substantial.address_country", row, profile, "BR"))
        tins = split_values(self.value("substantial.tin", row, profile))
        tin_country = country_code(self.value("substantial.tin_issued_by", row, profile, "BR"))
        count = max(len(org_names) if is_org else len(first_names), len(last_names), 1)
        parties: list[Party] = []
        for idx in range(count):
            parties.append(
                Party(
                    kind="organisation" if is_org else "individual",
                    res_country_codes=[country_code(c) for c in (countries or ["BR"])],
                    name=Name(
                        first_name=first_names[idx] if idx < len(first_names) else (first_names[0] if first_names else "Nome"),
                        last_name=last_names[idx] if idx < len(last_names) else (last_names[0] if last_names else "Sobrenome"),
                        organisation_name=org_names[idx] if idx < len(org_names) else (org_names[0] if org_names else "Organizacao"),
                    ),
                    address=Address(country_code(address_countries[idx] if idx < len(address_countries) else address_countries[0]), addresses[idx] if idx < len(addresses) else addresses[0]),
                    tins=[TIN(value, tin_country) for value in tins],
                )
            )
        return parties

    def _optional_bool(self, value: str) -> str:
        if not value:
            return ""
        return to_bool(value)

    def _message_value(self, kind: str, name: str, row: dict[str, Any], profile: MappingProfile, default: str) -> str:
        kind_field = f"{kind}.message.{name}"
        if kind_field in profile.field_mappings:
            return self.value(kind_field, row, profile, default)
        if name == "receiving_country":
            return default
        return self.value(f"message.{name}", row, profile, default)

    def _currency(self, kind: str, row: dict[str, Any], profile: MappingProfile) -> str:
        kind_field = f"{kind}.account.currency"
        if kind_field in profile.field_mappings:
            return currency_code(self.value(kind_field, row, profile, PROJECT_DEFAULT_CURRENCY))
        return currency_code(self.value("account.currency", row, profile, PROJECT_DEFAULT_CURRENCY))

    def _doc_type(self, kind: str, value: str) -> str:
        if kind == "fatca" and value.startswith("OECD"):
            return "FATCA1"
        if kind == "crs" and value.startswith("FATCA"):
            return "OECD1"
        return value

    def _auto_value(self, field: str, profile: MappingProfile) -> str:
        if field == "message.timestamp":
            return datetime.now().replace(microsecond=0).isoformat()
        if field == "message.reporting_period":
            return f"{datetime.now().year - 1}-12-31"
        if field.endswith("doc_ref_id") or field.endswith("message_ref_id"):
            return self._new_id(field, profile, "")
        return ""

    def _explicit_identifier_value(self, field: str, row: dict[str, Any], profile: MappingProfile) -> str:
        rule = profile.field_mappings.get(field)
        if not rule or rule.source == "auto":
            return ""
        return self.value(field, row, profile)

    def _new_id(self, kind: str, profile: MappingProfile, file_hash: str) -> str:
        prefix = profile.identifier_config.prefix or DITC_DEFAULT_PREFIX
        country = profile.identifier_config.country or "BR"
        if prefix.strip().upper() == "AUTO":
            prefix = DITC_DEFAULT_PREFIX
        if not profile.identifier_config.use_uuid:
            start = self._sequence_next.get(kind, 0)
            for sequence in range(start, 1_000_000):
                value = self._ditc_sequence_id(kind, prefix, country, sequence)
                if not self.identifier_store.exists(kind, value):
                    self._sequence_next[kind] = sequence + 1
                    logger.info("TRACE_BUTTON_PIPELINE MappingService._new_id kind=%s generator=DITC_SEQUENCE value=%s", kind, value)
                    return value
            raise RuntimeError("Nao foi possivel gerar identificador sequencial unico.")
        for _ in range(100):
            value = f"{prefix}-{country}-{uuid4().hex}"
            if not self.identifier_store.exists(kind, value):
                logger.info("TRACE_BUTTON_PIPELINE MappingService._new_id kind=%s generator=INTERNAL_UUID value=%s", kind, value)
                return value
        raise RuntimeError("Nao foi possivel gerar identificador unico.")

    def _ditc_sequence_id(self, kind: str, prefix: str, country: str, sequence: int) -> str:
        clean_prefix = "".join(char for char in prefix if char.isalnum())
        clean_country = "".join(char for char in country if char.isalnum())[:2] or "BR"
        kind_code = "F" if kind.startswith("fatca") else "C" if kind.startswith("crs") else "X"
        if "message" in kind:
            return f"{clean_prefix}{kind_code}{sequence:03d}"
        if "fi-doc" in kind:
            return f"{clean_prefix}FI{kind_code}I107442{sequence:03d}"
        if "account-doc" in kind:
            return f"{clean_prefix}FI{kind_code}{clean_country}107442{sequence:03d}"
        if "nil" in kind:
            return f"{clean_prefix}{kind_code}NIL{sequence:03d}"
        return f"{clean_prefix}{kind_code}{sequence:03d}"



def infer_default_profile(headers: list[str]) -> MappingProfile:
    profile = MappingProfile()
    aliases = {
        "account.account_number": ["numconta", "accountnumber", "account number*", "account number", "numero da conta"],
        "account.account_number_type": ["account number type", "tipo do numero da conta"],
        "account.closed": ["closed account?", "closed account", "conta encerrada"],
        "account.balance": ["saldototal", "saldo da conta em 31/12/2025", "saldo total", "account balance", "saldo"],
        "account.currency": ["currency", "moeda"],
        "account.doc_type_indic": ["document type"],
        "holder.first_name": ["firstname", "first name*", "first name", "nome"],
        "holder.last_name": ["lastname", "last name*", "last name", "sobrenome"],
        "holder.organisation_name": ["nomecliente", "name*", "organisation name", "nome organizacao"],
        "holder.res_country": ["pais", "país de residencia fiscal", "pais de residencia fiscal", "tax residence", "tax residence*", "country of residence", "residencia fiscal"],
        "holder.tin": ["documentocliente", "identification number / cpf", "documento cliente", "tin", "tax identification number (tin)", "identification number"],
        "holder.tin_issued_by": ["tin issued by", "pais emissor tin"],
        "holder.birth_date": ["data de nascimento", "birth date", "birthdate"],
        "holder.acct_holder_type": ["account holder type"],
        "holder.address_type": ["address type", "tipo endereco"],
        "holder.address_country": ["pais", "country", "country*", "pais endereco"],
        "holder.address_free": ["endereco", "street", "address free", "address"],
        "payment.type": ["payment type", "tipo pagamento"],
        "payment.amount": ["payment amount", "amount", "pagamento"],
        "fatca.us_tin": ["us_tax_id", "us tax id", "fatca_us_tin"],
        "fatca.us_tin_issued_by": ["us_tax_id_issued_by", "us tax id issued by", "fatca_us_tin_issued_by"],
        "fatca.us_tin_status": ["us_tax_id_status", "us tax id status", "fatca_us_tin_status"],
        "fatca.us_tin_reason": ["us_tax_id_reason", "us tax id reason", "fatca_us_tin_reason"],
    }
    lower = {header.lower(): header for header in headers}
    for field, names in aliases.items():
        match = next((lower[name] for name in names if name in lower), "")
        if match:
            profile.field_mappings[field] = MappingRule("column", match)

    if "nomecliente" in lower:
        profile.field_mappings["holder.first_name"] = MappingRule("column", lower["nomecliente"], transformations=["first_name"])
        profile.field_mappings["holder.last_name"] = MappingRule("column", lower["nomecliente"], transformations=["last_name"])
        profile.field_mappings["holder.organisation_name"] = MappingRule("column", lower["nomecliente"])
    if "name" in lower:
        profile.field_mappings["holder.organisation_name"] = MappingRule("column", lower["name"])
    if "tipo de documento" in lower:
        profile.field_mappings["holder.kind"] = MappingRule("column", lower["tipo de documento"], transformations=["pf_pj_kind"])
    if "documenttype" in lower:
        profile.field_mappings["holder.kind"] = MappingRule("column", lower["documenttype"], transformations=["pf_pj_kind"])
    if "documentocliente" in lower:
        profile.field_mappings["holder.tin"] = MappingRule("column", lower["documentocliente"], transformations=["strip_tax_mask"])
    if "identification number / cpf" in lower:
        profile.field_mappings["holder.tin"] = MappingRule("column", lower["identification number / cpf"], transformations=["strip_tax_mask"])
    if "pais" in lower:
        profile.field_mappings["holder.tin_issued_by"] = MappingRule("column", lower["pais"], transformations=["country_code"])
    if "tin issued by" in lower:
        profile.field_mappings["holder.tin_issued_by"] = MappingRule("column", lower["tin issued by"], transformations=["country_code"])
    if "document type" in lower:
        profile.field_mappings["account.doc_type_indic"] = MappingRule("column", lower["document type"], transformations=["code_prefix"])
    if "address type" in lower:
        profile.field_mappings["holder.address_type"] = MappingRule("column", lower["address type"], transformations=["code_prefix"])
    if "data de nascimento" in lower:
        profile.field_mappings["holder.birth_date"] = MappingRule("column", lower["data de nascimento"], transformations=["date"])
    address_parts = [lower[key] for key in ("endereco", "cidade", "estado", "pais") if key in lower]
    if not address_parts:
        address_parts = [lower[key] for key in ("street", "city", "country") if key in lower]
    if address_parts:
        profile.field_mappings["holder.address_free"] = MappingRule("calculated", ";".join(address_parts))
    if "numconta" in lower:
        profile.grouping.account_key = lower["numconta"]
    if "accountnumber" in lower:
        profile.grouping.account_key = lower["accountnumber"]

    defaults = {
        "message.sending_company_in": "FI107442",
        "message.transmitting_country": "KY",
        "message.receiving_country": "BR",
        "crs.message.transmitting_country": "KY",
        "crs.message.receiving_country": "BR",
        "fatca.message.transmitting_country": "KY",
        "fatca.message.receiving_country": "US",
        "message.message_type_indic": "CRS701",
        "message.reporting_period": "2025-12-31",
        "reporting_fi.name": "BANCO BS2 S.A.",
        "reporting_fi.in": "FI107442",
        "reporting_fi.issued_by": "KY",
        "reporting_fi.res_country": "KY",
        "reporting_fi.address_country": "KY",
        "reporting_fi.address_free": "South Church Street, 103, 5TH Floor, POB 1353, KY1-1108, George Town",
        "reporting_fi.doc_type_indic": "OECD1",
        "reporting_fi.filer_category": "FATCA601",
        "account.doc_type_indic": "OECD1",
        "holder.crs_self_cert": "CRS901",
        "account.crs_dd_procedure": "CRS1201",
        "account.crs_account_type": "CRS1101",
        "account.currency": PROJECT_DEFAULT_CURRENCY,
        "crs.account.currency": PROJECT_DEFAULT_CURRENCY,
        "fatca.account.currency": PROJECT_DEFAULT_CURRENCY,
        "fatca.us_tin": "",
        "fatca.us_tin_issued_by": "US",
        "fatca.us_tin_status": "NOT_COLLECTED",
        "fatca.us_tin_reason": "US Tax ID nao coletado na origem.",
        "fatca.missing_us_tin_policy": TECHNICAL_TEST_POLICY,
    }
    for field, value in defaults.items():
        profile.field_mappings.setdefault(field, MappingRule("fixed", fixed_value=value))
    profile.field_mappings.setdefault("message.timestamp", MappingRule("auto"))
    profile.field_mappings.setdefault("message.message_ref_id", MappingRule("auto"))
    profile.field_mappings.setdefault("reporting_fi.doc_ref_id", MappingRule("auto"))
    profile.field_mappings.setdefault("account.doc_ref_id", MappingRule("auto"))
    profile.identifier_config.prefix = "KY2025BRFI107442"
    profile.identifier_config.country = "BR"
    profile.identifier_config.use_uuid = False
    return profile
