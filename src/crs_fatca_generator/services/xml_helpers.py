from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from html import unescape
from pathlib import Path

from lxml import etree

from crs_fatca_generator.security.masking import remove_control_chars


XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
CRS_NS = "urn:oecd:ties:crs:v2"
CRS_STF_NS = "urn:oecd:ties:crsstf:v5"
CRS_CFC_NS = "urn:oecd:ties:commontypesfatcacrs:v2"
CRS_ISO_NS = "urn:oecd:ties:isocrstypes:v1"
CRS_FTCA_V1_NS = "urn:oecd:ties:fatca:v1"

FATCA_NS = "urn:oecd:ties:fatca:v2"
FATCA_SFA_NS = "urn:oecd:ties:stffatcatypes:v2"
FATCA_STF_NS = "urn:oecd:ties:stf:v4"
FATCA_ISO_NS = "urn:oecd:ties:isofatcatypes:v1"
CRS_STRICT_TEXT_NAMESPACES = {CRS_NS, CRS_STF_NS, CRS_CFC_NS, CRS_ISO_NS, CRS_FTCA_V1_NS}
PORTAL_PROHIBITED_TEXT_PATTERNS = (
    ("&amp;", " e "),
    ("&lt;", " "),
    ("&gt;", " "),
    ("&apos;", ""),
    ("&quot;", ""),
    ("&#", ""),
    ("&", " e "),
    ("<", " "),
    (">", " "),
    ("'", ""),
    ('"', ""),
    ("--", "-"),
    ("/*", "/"),
)
STRICT_TEXT_ALLOWED_CHARS = re.compile(r"[^A-Za-z0-9 ]")
PORTAL_ALLOWED_TEXT_CHARS = re.compile(r"[^A-Za-z0-9 .,;:()_+\-=]")
DECIMAL_ALLOWED_CHARS = re.compile(r"[^0-9.\-]")
DATE_ALLOWED_CHARS = re.compile(r"[^0-9\-]")
TIMESTAMP_ALLOWED_CHARS = re.compile(r"[^0-9T:\-.+Z]")
SCHEMA_LOCATION_ALLOWED_CHARS = re.compile(r"[^A-Za-z0-9 .:_/\-]")
DECIMAL_TEXT_TAGS = {"AccountBalance", "PaymentAmnt"}
DATE_TEXT_TAGS = {"ReportingPeriod", "BirthDate"}
TIMESTAMP_TEXT_TAGS = {"Timestamp"}


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def add(parent: etree._Element, ns: str, tag: str, text: object = "", attrib: dict[str, str] | None = None) -> etree._Element:
    strict_text = ns in CRS_STRICT_TEXT_NAMESPACES
    clean_attrib = {key: sanitize_xml_attribute(value, key, strict_text=strict_text) for key, value in (attrib or {}).items()}
    elem = etree.SubElement(parent, q(ns, tag), attrib=clean_attrib)
    if text not in (None, ""):
        elem.text = sanitize_xml_text(text, tag, strict_text=strict_text)
    return elem


def sanitize_xml_text(value: object, tag: str | None = None, strict_text: bool = False) -> str:
    text = _repair_mojibake(strip_invalid_xml_chars(str(value)))
    text = unescape(strip_invalid_xml_chars(text))
    text = _ascii_only(text)
    text = _remove_portal_prohibited_text(text)
    local_tag = _local_name(tag or "")
    if local_tag in DECIMAL_TEXT_TAGS:
        text = DECIMAL_ALLOWED_CHARS.sub("", text)
    elif local_tag in DATE_TEXT_TAGS:
        text = DATE_ALLOWED_CHARS.sub("", text)
    elif local_tag in TIMESTAMP_TEXT_TAGS:
        text = TIMESTAMP_ALLOWED_CHARS.sub("", text)
    elif strict_text:
        text = STRICT_TEXT_ALLOWED_CHARS.sub(" ", text)
    else:
        text = PORTAL_ALLOWED_TEXT_CHARS.sub(" ", text)
    text = _remove_portal_prohibited_text(text)
    return re.sub(r"\s+", " ", text).strip()


def sanitize_xml_attribute(value: object, attr_name: str | None = None, strict_text: bool = False) -> str:
    text = _repair_mojibake(strip_invalid_xml_chars(str(value)))
    text = unescape(strip_invalid_xml_chars(text))
    text = _ascii_only(text)
    text = _remove_portal_prohibited_text(text)
    local_name = _local_name(attr_name or "")
    if local_name == "schemaLocation":
        text = SCHEMA_LOCATION_ALLOWED_CHARS.sub(" ", text)
    elif local_name == "version":
        text = re.sub(r"[^0-9.]", "", text)
    elif strict_text:
        text = STRICT_TEXT_ALLOWED_CHARS.sub("", text)
    else:
        text = PORTAL_ALLOWED_TEXT_CHARS.sub(" ", text)
    text = _remove_portal_prohibited_text(text)
    return re.sub(r"\s+", " ", text).strip()


def _remove_portal_prohibited_text(value: str) -> str:
    text = value
    previous = None
    while text != previous:
        previous = text
        for pattern, replacement in PORTAL_PROHIBITED_TEXT_PATTERNS:
            text = text.replace(pattern, replacement)
    return text


def sanitize_xml_tree(root: etree._Element) -> None:
    for element in root.iter():
        qname = etree.QName(element)
        local_tag = qname.localname
        strict_text = qname.namespace in CRS_STRICT_TEXT_NAMESPACES
        if element.text and element.text.strip():
            element.text = sanitize_xml_text(element.text, local_tag, strict_text=strict_text)
        if element.tail and element.tail.strip():
            element.tail = sanitize_xml_text(element.tail)
        for key, value in list(element.attrib.items()):
            element.set(key, sanitize_xml_attribute(value, key, strict_text=strict_text))


def _local_name(name: str) -> str:
    if not name:
        return ""
    if name.startswith("{"):
        return name.rsplit("}", 1)[-1]
    if ":" in name:
        return name.rsplit(":", 1)[-1]
    return name


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
    sanitize_xml_tree(tree.getroot())
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
