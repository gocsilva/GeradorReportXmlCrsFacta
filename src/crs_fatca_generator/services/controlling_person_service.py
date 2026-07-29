from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from crs_fatca_generator.models.domain import ValidationIssue
from crs_fatca_generator.security.masking import mask_value
from crs_fatca_generator.services.tax_identifier_service import classify_tax_identifier
from crs_fatca_generator.services.transformation_service import code_prefix, country_code, normalize_text, to_date


CONTROLLING_BLOCK_START_INDEX = 23
CONTROLLING_PERSON_TYPES = {f"CRS{number}" for number in range(800, 814)}
EMPTY_MARKERS = {"", "NULL", "N/A", "NA", "NONE", "-", "NAN"}
FILLED_FIELDS = {"First Name", "Last Name", "Identification Number", "Controlling Person Type", "Tax Residence", "Birth Date"}


@dataclass(frozen=True)
class ControllingPersonRecord:
    excel_row: int | None
    account_number: str
    holder_document: str
    holder_name: str
    block_index: int
    name_type: str
    first_name: str
    last_name: str
    controlling_person_type: str
    tax_residence: str
    raw_tin: str
    normalized_tin: str
    tin_issued_by: str
    address_type: str
    country: str
    city: str
    birth_date: str
    result: str = "INCLUIDO"
    reason: str = ""
    normalized: bool = False

    def audit_row(self, processing_id: str, doc_ref_id: str = "") -> dict[str, object]:
        controller_name = " ".join(part for part in (self.first_name, self.last_name) if part)
        return {
            "processing_id": processing_id,
            "linha da origem": self.excel_row or "",
            "conta": mask_value(self.account_number),
            "documento da empresa": mask_value(self.holder_document),
            "nome da empresa": self.holder_name,
            "indice do bloco": self.block_index,
            "nome do controlador": controller_name,
            "documento mascarado": mask_value(self.normalized_tin),
            "documento bruto": mask_value(self.raw_tin),
            "documento normalizado": mask_value(self.normalized_tin),
            "pais de residencia fiscal": self.tax_residence,
            "pais emissor do TIN": self.tin_issued_by,
            "tipo de controlador": self.controlling_person_type,
            "data de nascimento": self.birth_date,
            "resultado da validacao": self.result,
            "inclusao ou exclusao": "incluido" if self.result == "INCLUIDO" else "excluido",
            "motivo": self.reason,
            "DocRefId do AccountReport": doc_ref_id,
        }


def detect_controlling_person_blocks(headers: list[str]) -> list[dict[str, int]]:
    starts = [
        index
        for index, header in enumerate(headers)
        if index >= CONTROLLING_BLOCK_START_INDEX and _header_key(header) == "name type"
    ]
    blocks: list[dict[str, int]] = []
    for block_index, start in enumerate(starts, 1):
        end = starts[block_index] if block_index < len(starts) else len(headers)
        field_indexes: dict[str, int] = {}
        for index in range(start, end):
            header = _canonical_header(headers[index])
            if header in {
                "Name Type",
                "First Name",
                "Last Name",
                "Controlling Person Type",
                "Tax Residence",
                "Identification Number",
                "TIN Issued By",
                "Address Type",
                "Country",
                "City",
                "Birth Date",
            }:
                field_indexes.setdefault(header, index)
        if field_indexes:
            blocks.append(field_indexes)
    return blocks


def extract_controlling_persons(row: dict[str, Any]) -> tuple[list[ControllingPersonRecord], list[ValidationIssue], dict[str, int]]:
    headers = list(row.get("_headers") or [])
    raw_values = list(row.get("_raw_values") or [])
    blocks = detect_controlling_person_blocks(headers)
    records: list[ControllingPersonRecord] = []
    issues: list[ValidationIssue] = []
    empty_blocks = 0
    normalized_cpfs = 0
    invalid_cpfs = 0
    seen_documents: set[str] = set()
    excel_row = _excel_row(row)
    account = _row_value(row, "AccountNumber", "NumConta")
    holder_document = normalize_text(row.get("_documento_brasileiro") or _row_value(row, "Identification Number / CPF", "DocumentoCliente"))
    holder_name = _row_value(row, "Name", "NomeCliente")

    for block_index, block in enumerate(blocks, 1):
        values = {name: _value_at(raw_values, index) for name, index in block.items()}
        if not _block_filled(values):
            empty_blocks += 1
            continue

        first_name = normalize_text(values.get("First Name")).upper()
        last_name = normalize_text(values.get("Last Name")).upper()
        raw_tin = normalize_text(values.get("Identification Number"))
        tin_issued_by = country_code(values.get("TIN Issued By") or values.get("Tax Residence") or values.get("Country") or "BR")
        tax_residence = country_code(values.get("Tax Residence") or values.get("Country") or tin_issued_by or "BR")
        controlling_type = code_prefix(values.get("Controlling Person Type") or "CRS801")
        address_type = code_prefix(values.get("Address Type"))
        country = country_code(values.get("Country") or tax_residence or "BR")
        birth_date = _safe_date(values.get("Birth Date"))
        name_type = code_prefix(values.get("Name Type"))
        reason_parts: list[str] = []
        normalized_tin = ""
        normalized = False

        if not first_name or not last_name:
            reason_parts.append("Nome do controlador ausente ou incompleto.")
        if not raw_tin:
            reason_parts.append("Documento do controlador ausente.")
        if not tin_issued_by:
            reason_parts.append("Pais emissor do TIN ausente.")
        if controlling_type not in CONTROLLING_PERSON_TYPES:
            reason_parts.append(f"Tipo de controlador invalido: {controlling_type or 'vazio'}.")
        if values.get("Birth Date") and not birth_date:
            reason_parts.append("Data de nascimento invalida.")

        if raw_tin and tin_issued_by:
            try:
                classified = classify_tax_identifier(raw_tin, "PF", tin_issued_by)
            except ValueError as exc:
                classified = None
                reason_parts.append(str(exc))
            if classified:
                normalized_tin = classified.normalized
                normalized = normalize_text(raw_tin) != classified.normalized
                if tin_issued_by == "BR" and classified.kind == "CPF" and normalized:
                    normalized_cpfs += 1
                if not classified.valid:
                    invalid_cpfs += 1
                    reason_parts.append(classified.message or "CPF invalido.")
        if normalized_tin and normalized_tin in seen_documents:
            reason_parts.append("Controlador duplicado no mesmo AccountReport.")
        if normalized_tin:
            seen_documents.add(normalized_tin)

        result = "EXCLUIDO" if reason_parts else "INCLUIDO"
        record = ControllingPersonRecord(
            excel_row=excel_row,
            account_number=account,
            holder_document=holder_document,
            holder_name=holder_name,
            block_index=block_index,
            name_type=name_type,
            first_name=first_name,
            last_name=last_name,
            controlling_person_type=controlling_type or "CRS801",
            tax_residence=tax_residence or "BR",
            raw_tin=raw_tin,
            normalized_tin=normalized_tin,
            tin_issued_by=tin_issued_by or "BR",
            address_type=address_type,
            country=country or tax_residence or "BR",
            city=normalize_text(values.get("City")),
            birth_date=birth_date,
            result=result,
            reason="; ".join(reason_parts),
            normalized=normalized,
        )
        records.append(record)
        if reason_parts:
            issues.append(
                ValidationIssue(
                    "erro",
                    "CP001",
                    f"Controlador bloco {block_index}: " + "; ".join(reason_parts),
                    "ControllingPerson",
                    excel_row,
                    "Corrija os dados do controlador no Excel.",
                )
            )

    metrics = {
        "blocks_detected": len(blocks),
        "empty_blocks": empty_blocks,
        "valid_blocks": sum(1 for record in records if record.result == "INCLUIDO"),
        "received_blocks": len(records),
        "normalized_cpfs": normalized_cpfs,
        "invalid_cpfs": invalid_cpfs,
    }
    return records, issues, metrics


def _header_key(value: Any) -> str:
    text = normalize_text(value)
    text = "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))
    return text.casefold()


def _canonical_header(value: Any) -> str:
    key = _header_key(value)
    aliases = {
        "name type": "Name Type",
        "first name": "First Name",
        "last name": "Last Name",
        "controlling person type": "Controlling Person Type",
        "tax residence": "Tax Residence",
        "identification number": "Identification Number",
        "tin issued by": "TIN Issued By",
        "address type": "Address Type",
        "country": "Country",
        "city": "City",
        "birth date": "Birth Date",
    }
    return aliases.get(key, normalize_text(value))


def _value_at(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else ""


def _is_empty_value(value: Any) -> bool:
    return normalize_text(value).upper() in EMPTY_MARKERS


def _block_filled(values: dict[str, Any]) -> bool:
    return any(not _is_empty_value(values.get(field)) for field in FILLED_FIELDS)


def _safe_date(value: Any) -> str:
    if _is_empty_value(value):
        return ""
    try:
        return to_date(value)
    except ValueError:
        return ""


def _row_value(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if not _is_empty_value(value):
            return normalize_text(value)
    return ""


def _excel_row(row: dict[str, Any]) -> int | None:
    try:
        return int(row.get("_excel_row") or 0) or None
    except (TypeError, ValueError):
        return None
