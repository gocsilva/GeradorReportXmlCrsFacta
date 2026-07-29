from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from crs_fatca_generator.services.transformation_service import normalize_text


@dataclass(frozen=True)
class TaxIdentifier:
    original: str
    normalized: str
    kind: str
    issued_by: str
    valid: bool
    message: str = ""


def digits_only(value: Any) -> str:
    return re.sub(r"\D", "", normalize_document_text(value))


def normalize_document_text(value: Any) -> str:
    text = normalize_text(value)
    if re.fullmatch(r"[+-]?\d+(?:[,.]\d+)?[eE][+-]?\d+", text):
        raise ValueError("Documento em notacao cientifica nao pode ser recuperado com seguranca.")
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def classify_tax_identifier(value: Any, person_type: Any, country: Any = "BR") -> TaxIdentifier:
    original = normalize_text(value)
    issued_by = normalize_text(country).upper()[:2] or "BR"
    kind_text = normalize_text(person_type).upper()
    is_pf = kind_text in {"PF", "FISICA", "PESSOA FISICA", "INDIVIDUAL"}
    is_pj = kind_text in {"PJ", "JURIDICA", "PESSOA JURIDICA", "ORGANISATION", "ORGANIZATION"}
    doc_digits = digits_only(value)

    if issued_by == "BR" and is_pf:
        if len(doc_digits) > 11:
            return TaxIdentifier(original, doc_digits, "CPF", issued_by, False, "CPF possui mais de 11 digitos.")
        cpf = doc_digits.zfill(11)
        return TaxIdentifier(original, cpf, "CPF", issued_by, validate_cpf(cpf), "CPF invalido." if not validate_cpf(cpf) else "")

    if issued_by == "BR" and is_pj:
        if len(doc_digits) > 14:
            return TaxIdentifier(original, doc_digits, "CNPJ", issued_by, False, "CNPJ possui mais de 14 digitos.")
        cnpj = doc_digits.zfill(14)
        return TaxIdentifier(original, cnpj, "CNPJ", issued_by, validate_cnpj(cnpj), "CNPJ invalido." if not validate_cnpj(cnpj) else "")

    if not doc_digits:
        return TaxIdentifier(original, "", "TIN", issued_by, False, "Documento fiscal vazio.")
    return TaxIdentifier(original, doc_digits, "TIN", issued_by, True)


def validate_cpf(value: str) -> bool:
    cpf = digits_only(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for position in (9, 10):
        total = sum(int(cpf[index]) * (position + 1 - index) for index in range(position))
        digit = (total * 10) % 11
        if digit == 10:
            digit = 0
        if digit != int(cpf[position]):
            return False
    return True


def validate_cnpj(value: str) -> bool:
    cnpj = digits_only(value)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    weights_first = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights_second = [6] + weights_first
    for weights, position in ((weights_first, 12), (weights_second, 13)):
        total = sum(int(cnpj[index]) * weight for index, weight in enumerate(weights))
        digit = 11 - (total % 11)
        if digit >= 10:
            digit = 0
        if digit != int(cnpj[position]):
            return False
    return True
