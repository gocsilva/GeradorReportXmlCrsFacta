from __future__ import annotations

import re


SENSITIVE_WORDS = ("tin", "cpf", "cnpj", "giin", "account", "conta", "saldo", "name", "nome")


def mask_value(value: object, keep: int = 4) -> str:
    text = "" if value is None else str(value)
    if len(text) <= keep:
        return "*" * len(text)
    return "*" * max(0, len(text) - keep) + text[-keep:]


def mask_record(record: dict[str, object]) -> dict[str, object]:
    masked: dict[str, object] = {}
    for key, value in record.items():
        if any(word in key.lower() for word in SENSITIVE_WORDS):
            masked[key] = mask_value(value)
        else:
            masked[key] = value
    return masked


def remove_control_chars(value: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
