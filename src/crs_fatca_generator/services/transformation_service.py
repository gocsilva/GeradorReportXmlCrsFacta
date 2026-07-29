from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from crs_fatca_generator.security.masking import remove_control_chars


EMPTY_MARKERS = {"", "none", "null", "nan", "NaN", "N/A", "n/a"}


def is_empty(value: Any) -> bool:
    return value is None or str(value).strip() in EMPTY_MARKERS


def normalize_text(value: Any) -> str:
    if is_empty(value):
        return ""
    text = remove_control_chars(str(value))
    return re.sub(r"\s+", " ", text).strip()


def split_values(value: Any) -> list[str]:
    text = normalize_text(value)
    if not text:
        return []
    return [part.strip() for part in re.split(r"[;|]", text) if part.strip()]


def to_bool(value: Any) -> str:
    text = normalize_text(value).lower()
    if text in {"sim", "s", "yes", "y", "1", "true", "verdadeiro"}:
        return "true"
    if text in {"nao", "não", "n", "no", "0", "false", "falso"}:
        return "false"
    raise ValueError(f"Booleano invalido: {value!r}")


def to_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = normalize_text(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        pass
    raise ValueError(f"Data invalida: {value!r}")


def to_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    text = normalize_text(value)
    if not text:
        return datetime.now().replace(microsecond=0).isoformat()
    try:
        return datetime.fromisoformat(text).replace(microsecond=0).isoformat()
    except ValueError:
        d = to_date(text)
        return f"{d}T00:00:00"


def to_decimal(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        decimal = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"Decimal invalido: {value!r}") from exc
    return format(decimal, "f")


def strip_mask(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", normalize_text(value))


def country_code(value: Any) -> str:
    text = normalize_text(value).upper()
    if len(text) >= 2:
        return text[:2]
    return text


def currency_code(value: Any) -> str:
    text = normalize_text(value).upper()
    if len(text) >= 3:
        return text[:3]
    return text


def code_prefix(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    return re.split(r"\s+-\s+|\s+", text, maxsplit=1)[0].strip()


def first_name(value: Any) -> str:
    parts = normalize_text(value).split()
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return parts[0]


def last_name(value: Any) -> str:
    parts = normalize_text(value).split()
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return " ".join(parts[1:])


def pf_pj_kind(value: Any) -> str:
    text = normalize_text(value).upper()
    if text in {"PF", "FISICA", "PESSOA FISICA", "INDIVIDUAL"}:
        return "individual"
    if text in {"PJ", "JURIDICA", "PESSOA JURIDICA", "ORGANISATION", "ORGANIZATION"}:
        return "organisation"
    return text.lower()


TRANSFORMS = {
    "trim": normalize_text,
    "upper": lambda v: normalize_text(v).upper(),
    "lower": lambda v: normalize_text(v).lower(),
    "remove_invisible": lambda v: remove_control_chars(str(v)),
    "normalize_spaces": normalize_text,
    "date": to_date,
    "datetime": to_datetime,
    "boolean": to_bool,
    "decimal": to_decimal,
    "strip_tax_mask": strip_mask,
    "strip_giin_tin_mask": strip_mask,
    "country_code": country_code,
    "currency_code": currency_code,
    "code_prefix": code_prefix,
    "first_name": first_name,
    "last_name": last_name,
    "pf_pj_kind": pf_pj_kind,
}


def apply_transformations(value: Any, transformations: list[str] | None) -> str:
    current = value
    for name in transformations or []:
        func = TRANSFORMS.get(name)
        if func is None:
            raise ValueError(f"Transformacao desconhecida: {name}")
        current = func(current)
    return normalize_text(current)
