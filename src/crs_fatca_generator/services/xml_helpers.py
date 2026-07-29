from __future__ import annotations

import os
import tempfile
from pathlib import Path

from lxml import etree


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


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def add(parent: etree._Element, ns: str, tag: str, text: object = "", attrib: dict[str, str] | None = None) -> etree._Element:
    elem = etree.SubElement(parent, q(ns, tag), attrib=attrib or {})
    if text not in (None, ""):
        elem.text = str(text)
    return elem


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
