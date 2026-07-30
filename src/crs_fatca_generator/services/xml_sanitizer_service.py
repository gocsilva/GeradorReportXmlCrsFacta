from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from crs_fatca_generator.services.xml_helpers import atomic_write, sanitize_xml_text, strip_invalid_xml_chars


@dataclass
class XmlSanitizationResult:
    input_path: Path
    output_path: Path
    text_nodes_changed: int = 0
    attributes_changed: int = 0
    invalid_chars_removed: int = 0
    used_recovery_parser: bool = False


class XmlSanitizerService:
    def sanitize_file(self, input_path: Path, output_path: Path | None = None) -> XmlSanitizationResult:
        if not input_path.exists():
            raise FileNotFoundError(f"XML nao encontrado: {input_path}")
        target = output_path or input_path.with_name(f"{input_path.stem}_limpo{input_path.suffix or '.xml'}")
        raw = input_path.read_text(encoding="utf-8", errors="replace")
        stripped = strip_invalid_xml_chars(raw)
        result = XmlSanitizationResult(
            input_path=input_path,
            output_path=target,
            invalid_chars_removed=max(len(raw) - len(stripped), 0),
        )
        root = self._parse_xml(stripped, result)
        self._sanitize_tree(root, result)
        atomic_write(etree.ElementTree(root), target, True)
        return result

    def _parse_xml(self, text: str, result: XmlSanitizationResult) -> etree._Element:
        strict_parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
        try:
            return etree.fromstring(text.encode("utf-8"), strict_parser)
        except etree.XMLSyntaxError:
            recovery_parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, remove_blank_text=False)
            result.used_recovery_parser = True
            return etree.fromstring(text.encode("utf-8"), recovery_parser)

    def _sanitize_tree(self, root: etree._Element, result: XmlSanitizationResult) -> None:
        for element in root.iter():
            if element.text and element.text.strip():
                cleaned = sanitize_xml_text(element.text)
                if cleaned != element.text:
                    element.text = cleaned
                    result.text_nodes_changed += 1
            if element.tail and element.tail.strip():
                cleaned = sanitize_xml_text(element.tail)
                if cleaned != element.tail:
                    element.tail = cleaned
                    result.text_nodes_changed += 1
            for key, value in list(element.attrib.items()):
                cleaned = sanitize_xml_text(value)
                if cleaned != value:
                    element.set(key, cleaned)
                    result.attributes_changed += 1
