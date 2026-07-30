from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path

from lxml import etree

from crs_fatca_generator.security.masking import remove_control_chars


XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
CRS_NS = "urn:oecd:ties:crs:v3"
CRS_STF_NS = "urn:oecd:ties:crsstf:v5"
CRS_CFC_NS = "urn:oecd:ties:commontypesfatcacrs:v2"
CRS_ISO_NS = "urn:oecd:ties:isocrstypes:v1"
CRS_FTCA_V1_NS = "urn:oecd:ties:fatca:v1"

FATCA_NS = "urn:oecd:ties:fatca:v2"
FATCA_SFA_NS = "urn:oecd:ties:stffatcatypes:v2"
FATCA_STF_NS = "urn:oecd:ties:stf:v4"
FATCA_ISO_NS = "urn:oecd:ties:isofatcatypes:v1"
PORTAL_PROHIBITED_TEXT_PATTERNS = (
    ("&#", ""),
    ("&", " e "),
    ("<", " "),
    ("--", "-"),
    ("/*", "/"),
)


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def add(parent: etree._Element, ns: str, tag: str, text: object = "", attrib: dict[str, str] | None = None) -> etree._Element:
    clean_attrib = {key: sanitize_xml_text(value) for key, value in (attrib or {}).items()}
    elem = etree.SubElement(parent, q(ns, tag), attrib=clean_attrib)
    if text not in (None, ""):
        elem.text = sanitize_xml_text(text)
    return elem


def sanitize_xml_text(value: object) -> str:
    text = _repair_mojibake(strip_invalid_xml_chars(str(value)))
    text = strip_invalid_xml_chars(text)
    for pattern, replacement in PORTAL_PROHIBITED_TEXT_PATTERNS:
        text = text.replace(pattern, replacement)
    text = _ascii_only(text)
    return re.sub(r"\s+", " ", text).strip()


def strip_invalid_xml_chars(value: str) -> str:
    return "".join(
        char
        for char in remove_control_chars(str(value))
        if _is_valid_xml_10_char(char) and not _is_discouraged_xml_10_char(char)
    )


def _repair_mojibake(value: str) -> str:
    if not any(marker in value for marker in ("Ã", "Â", "â")):
        return value
    try:
        repaired = value.encode("latin1", errors="ignore").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if repaired else value


def _ascii_only(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _is_valid_xml_10_char(char: str) -> bool:
    codepoint = ord(char)
    return (
        codepoint in {0x09, 0x0A, 0x0D}
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _is_discouraged_xml_10_char(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x7F <= codepoint <= 0x84
        or 0x86 <= codepoint <= 0x9F
        or 0xFDD0 <= codepoint <= 0xFDEF
        or (codepoint & 0xFFFF) in {0xFFFE, 0xFFFF}
    )


def atomic_write(tree: etree._ElementTree, output_path: Path, pretty_print: bool = True) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=output_path.name, suffix=".tmp", dir=output_path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        tree.write(
            str(temp_path),
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=pretty_print,
        )
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
