from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from crs_fatca_generator import APP_VERSION
from .file_hash import sha256_file


@dataclass
class AuditReport:
    created_at: str
    app_version: str
    excel_file: str
    excel_sha256: str
    sheet_name: str
    records: int
    schema: str
    schema_hashes: dict[str, str]
    profile: str
    errors: int
    warnings: int
    xml_file: str
    xml_sha256: str
    validation_result: str


class AuditService:
    def build(
        self,
        excel_file: Path,
        sheet_name: str,
        records: int,
        schema: str,
        schema_hashes: dict[str, str],
        profile: str,
        errors: int,
        warnings: int,
        xml_file: Path,
        valid: bool,
    ) -> AuditReport:
        return AuditReport(
            created_at=datetime.now().isoformat(timespec="seconds"),
            app_version=APP_VERSION,
            excel_file=str(excel_file),
            excel_sha256=sha256_file(excel_file) if excel_file.exists() else "",
            sheet_name=sheet_name,
            records=records,
            schema=schema,
            schema_hashes=schema_hashes,
            profile=profile,
            errors=errors,
            warnings=warnings,
            xml_file=str(xml_file),
            xml_sha256=sha256_file(xml_file) if xml_file.exists() else "",
            validation_result="valido" if valid else "invalido",
        )

    def export_json(self, report: AuditReport, path: Path) -> None:
        path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")

    def export_txt(self, report: AuditReport, path: Path) -> None:
        lines = [f"{key}: {value}" for key, value in asdict(report).items()]
        path.write_text("\n".join(lines), encoding="utf-8")
