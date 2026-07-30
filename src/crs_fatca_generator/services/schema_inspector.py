from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lxml import etree

from crs_fatca_generator.security.xml_security import secure_xml_parser


XS = {"xs": "http://www.w3.org/2001/XMLSchema", "xsd": "http://www.w3.org/2001/XMLSchema"}


@dataclass
class SchemaField:
    path: str
    namespace: str
    xsd_type: str
    min_occurs: str
    max_occurs: str
    required: bool
    documentation: str
    enum_values: list[str]


@dataclass
class SchemaInspection:
    schema_path: Path
    namespace: str
    root_element: str
    imports: list[str]
    enums: dict[str, list[str]]
    fields: list[SchemaField]


class SchemaInspector:
    def inspect(self, schema_path: Path) -> SchemaInspection:
        parser = secure_xml_parser()
        doc = etree.parse(str(schema_path), parser)
        root = doc.getroot()
        namespace = root.get("targetNamespace") or ""
        imports = [imp.get("schemaLocation") or "" for imp in root.xpath("./xs:import | ./xsd:import", namespaces=XS)]
        enums = self.enums(schema_path)
        root_elements = root.xpath("./xs:element | ./xsd:element", namespaces=XS)
        root_element = root_elements[0].get("name") if root_elements else ""
        fields = self._collect_top_level_fields(doc, root_element, namespace)
        return SchemaInspection(schema_path, namespace, root_element, imports, enums, fields)

    def enums(self, schema_path: Path) -> dict[str, list[str]]:
        resolved = schema_path.resolve()
        return {key: list(values) for key, values in _enums_cached(str(resolved), _schema_fingerprint(resolved)).items()}

    def _collect_top_level_fields(self, doc: etree._ElementTree, root_element: str, namespace: str) -> list[SchemaField]:
        fields: list[SchemaField] = []
        for elem in doc.xpath(".//xs:element | .//xsd:element", namespaces=XS):
            name = elem.get("name")
            if not name:
                continue
            documentation = " ".join(
                text.strip()
                for text in elem.xpath(".//xs:documentation/text() | .//xsd:documentation/text()", namespaces=XS)
                if text and text.strip()
            )
            min_occurs = elem.get("minOccurs", "1")
            max_occurs = elem.get("maxOccurs", "1")
            fields.append(
                SchemaField(
                    path=f"{root_element}/.../{name}" if root_element and name != root_element else name,
                    namespace=namespace,
                    xsd_type=elem.get("type", ""),
                    min_occurs=min_occurs,
                    max_occurs=max_occurs,
                    required=min_occurs != "0",
                    documentation=documentation,
                    enum_values=[],
                )
            )
        return fields


@lru_cache(maxsize=16)
def _enums_cached(schema_path_text: str, _fingerprint: tuple[tuple[str, int], ...]) -> dict[str, tuple[str, ...]]:
    schema_path = Path(schema_path_text)
    result: dict[str, tuple[str, ...]] = {}
    for xsd in [schema_path, *schema_path.parent.glob("*.xsd")]:
        doc = etree.parse(str(xsd), secure_xml_parser())
        for simple_type in doc.xpath(".//xs:simpleType | .//xsd:simpleType", namespaces=XS):
            name = simple_type.get("name")
            values = tuple(value for value in (enum.get("value") for enum in simple_type.xpath(".//xs:enumeration | .//xsd:enumeration", namespaces=XS)) if value)
            if name and values:
                result[name] = values
    return result


def _schema_fingerprint(schema_path: Path) -> tuple[tuple[str, int], ...]:
    files = [schema_path, *schema_path.parent.glob("*.xsd")]
    return tuple(sorted((str(file.resolve()), file.stat().st_mtime_ns) for file in files if file.exists()))
