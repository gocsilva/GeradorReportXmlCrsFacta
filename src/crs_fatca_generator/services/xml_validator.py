from __future__ import annotations

from pathlib import Path

from lxml import etree

from crs_fatca_generator.models.domain import ValidationIssue
from crs_fatca_generator.security.xml_security import secure_xml_parser
from .schema_loader import SchemaLoader


class XmlValidator:
    def validate_file(self, xml_path: Path, schema_path: Path, kind: str) -> list[ValidationIssue]:
        bundle = SchemaLoader().load(kind, "", schema_path)
        parser = secure_xml_parser()
        doc = etree.parse(str(xml_path), parser)
        valid = bundle.xml_schema.validate(doc)
        if valid:
            return []
        return [
            ValidationIssue(
                level="erro",
                code="XSD",
                message=error.message,
                field=error.path or "",
                excel_row=error.line,
                suggestion="Revise o campo indicado, a ordem dos elementos ou o valor permitido pelo XSD.",
            )
            for error in bundle.xml_schema.error_log
        ]

    def validate_tree(self, tree: etree._ElementTree, schema_path: Path, kind: str) -> list[ValidationIssue]:
        bundle = SchemaLoader().load(kind, "", schema_path)
        valid = bundle.xml_schema.validate(tree)
        if valid:
            return []
        return [
            ValidationIssue("erro", "XSD", error.message, error.path or "", error.line, "Ajuste o XML conforme o schema selecionado.")
            for error in bundle.xml_schema.error_log
        ]
