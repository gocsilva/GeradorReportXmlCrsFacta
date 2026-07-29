from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from crs_fatca_generator.security.xml_security import secure_xml_parser
from .file_hash import sha256_file


@dataclass
class SchemaBundle:
    kind: str
    version: str
    main_schema: Path
    namespace: str
    root_element: str
    imported_files: list[Path]
    hashes: dict[str, str]
    xml_schema: etree.XMLSchema


class LocalResolver(etree.Resolver):
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def resolve(self, url: str, pubid: str, context: object) -> object:
        candidate = (self.base_dir / url).resolve()
        base = self.base_dir.resolve()
        if candidate.exists() and (candidate == base or base in candidate.parents or candidate.parent == base):
            return self.resolve_filename(str(candidate), context)
        return None


class SchemaLoader:
    def load(self, kind: str, version: str, schema_path: Path) -> SchemaBundle:
        parser = secure_xml_parser()
        parser.resolvers.add(LocalResolver(schema_path.parent))
        doc = etree.parse(str(schema_path), parser)
        schema = etree.XMLSchema(doc)
        root = doc.getroot()
        xs = {"xs": "http://www.w3.org/2001/XMLSchema", "xsd": "http://www.w3.org/2001/XMLSchema"}
        imports = [
            (schema_path.parent / item.get("schemaLocation")).resolve()
            for item in root.xpath("./xs:import | ./xsd:import", namespaces=xs)
            if item.get("schemaLocation")
        ]
        root_elements = root.xpath("./xs:element | ./xsd:element", namespaces=xs)
        root_element = root_elements[0].get("name") if root_elements else ""
        files = [schema_path.resolve(), *imports]
        hashes = {file.name: sha256_file(file) for file in files if file.exists()}
        return SchemaBundle(
            kind=kind,
            version=version,
            main_schema=schema_path.resolve(),
            namespace=root.get("targetNamespace") or "",
            root_element=root_element,
            imported_files=imports,
            hashes=hashes,
            xml_schema=schema,
        )
