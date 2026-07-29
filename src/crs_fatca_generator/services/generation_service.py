from __future__ import annotations

from datetime import datetime
from pathlib import Path

from crs_fatca_generator.models.domain import GenerationResult, ValidationIssue
from crs_fatca_generator.models.mapping import MappingProfile
from crs_fatca_generator.services.business_validator import BusinessValidator
from crs_fatca_generator.services.crs_generator import CrsGenerator
from crs_fatca_generator.services.data_preparation_service import DataPreparationService, PreparedData
from crs_fatca_generator.services.fatca_generator import FatcaGenerator
from crs_fatca_generator.services.file_hash import sha256_file
from crs_fatca_generator.services.fatca_missing_tin_policy import DEFAULT_MISSING_US_TIN_POLICY, TECHNICAL_TEST_POLICY
from crs_fatca_generator.services.mapping_service import MappingService
from crs_fatca_generator.services.schema_inspector import SchemaInspector
from crs_fatca_generator.services.schema_loader import SchemaLoader
from crs_fatca_generator.services.xml_validator import XmlValidator


class GenerationService:
    def __init__(self, crs_schema: Path, fatca_schema: Path) -> None:
        self.crs_schema = crs_schema
        self.fatca_schema = fatca_schema
        self.mapping_service = MappingService()
        self.business_validator = BusinessValidator()
        self.xml_validator = XmlValidator()

    def generate(
        self,
        kinds: list[str],
        rows: list[dict[str, object]],
        profile: MappingProfile,
        excel_path: Path | None = None,
        overwrite: bool = False,
    ) -> list[GenerationResult]:
        results: list[GenerationResult] = []
        file_hash = sha256_file(excel_path) if excel_path and excel_path.exists() else ""
        data_service = DataPreparationService()
        prepared = data_service.prepare(rows, profile)
        audit_csv, audit_xlsx, audit_json = self._audit_paths(profile, excel_path)
        audit_summary = self._audit_summary(prepared, audit_csv, audit_xlsx, audit_json)
        reports: dict[str, object] = {}
        if prepared.issues:
            for kind in kinds:
                output_path = self._output_path(kind, profile)
                results.append(GenerationResult(kind, str(output_path), False, prepared.issues, {**audit_summary, **self._fiscal_summary(kind, profile), "status": "nao gerado"}))
            data_service.write_audit(prepared, self._audit_dir(profile), self._audit_stem(profile, excel_path), profile, excel_path, file_hash, results, reports)
            return results
        for kind in kinds:
            schema_path = self.crs_schema if kind == "crs" else self.fatca_schema
            enums = SchemaInspector().enums(schema_path)
            bundle = SchemaLoader().load(kind, "3.0" if kind == "crs" else "2.0.1", schema_path)
            report = self.mapping_service.build_report(kind, prepared.rows, profile, file_hash)
            reports[kind] = report
            business_issues = self.business_validator.validate(report, enums)
            output_path = self._output_path(kind, profile)
            if output_path.exists() and not overwrite:
                business_issues.append(
                    ValidationIssue("erro", "OUT001", f"O arquivo ja existe: {output_path}", "saida", suggestion="Escolha outro nome ou confirme sobrescrita.")
                )
            if any(issue.level == "erro" for issue in business_issues):
                results.append(GenerationResult(kind, str(output_path), False, business_issues, {**self._summary(report, "nao gerado"), **audit_summary, **self._fiscal_summary(kind, profile)}))
                continue
            tree = CrsGenerator().write(report, output_path, profile.output.pretty_print) if kind == "crs" else FatcaGenerator().write(report, output_path, profile.output.pretty_print)
            xsd_issues = self.xml_validator.validate_tree(tree, schema_path, kind)
            valid = not xsd_issues
            results.append(
                GenerationResult(
                    kind=kind,
                    xml_path=str(output_path),
                    valid=valid,
                    issues=xsd_issues,
                    summary={**self._summary(report, "valido" if valid else "invalido"), **audit_summary, **self._fiscal_summary(kind, profile), "schema_hashes": ",".join(bundle.hashes.values())},
                )
            )
        data_service.write_audit(prepared, self._audit_dir(profile), self._audit_stem(profile, excel_path), profile, excel_path, file_hash, results, reports)
        return results

    def _output_path(self, kind: str, profile: MappingProfile) -> Path:
        raw = profile.output.crs_path if kind == "crs" else profile.output.fatca_path
        if not raw:
            raw = f"{kind.upper()}_teste.xml"
        path = Path(raw)
        if profile.output.append_timestamp_to_name:
            suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = path.with_name(f"{path.stem}_{suffix}{path.suffix or '.xml'}")
        if path.suffix.lower() != ".xml":
            path = path.with_suffix(".xml")
        return path

    def _summary(self, report: object, status: str) -> dict[str, int | str]:
        accounts = len(getattr(report, "accounts", []))
        payments = sum(len(account.payments) for account in getattr(report, "accounts", []))
        return {
            "status": status,
            "contas": accounts,
            "pagamentos": payments,
            "nil_report": "sim" if getattr(report, "nil_report", None) else "nao",
        }

    def _audit_dir(self, profile: MappingProfile) -> Path:
        for raw in (profile.output.crs_path, profile.output.fatca_path):
            if raw:
                return Path(raw).parent
        return Path.cwd()

    def _audit_stem(self, profile: MappingProfile, excel_path: Path | None) -> str:
        if excel_path and excel_path.name:
            return excel_path.stem
        for raw in (profile.output.crs_path, profile.output.fatca_path):
            if raw:
                return Path(raw).stem
        return "processamento"

    def _audit_paths(self, profile: MappingProfile, excel_path: Path | None) -> tuple[Path, Path, Path]:
        output_dir = self._audit_dir(profile)
        stem = self._audit_stem(profile, excel_path)
        return (
            output_dir / f"{stem}_relatorio_auditoria.csv",
            output_dir / f"{stem}_relatorio_auditoria.xlsx",
            output_dir / f"{stem}_manifesto_auditoria.json",
        )

    def _audit_summary(self, prepared: PreparedData, csv_path: Path, xlsx_path: Path, json_path: Path) -> dict[str, int | str]:
        removals = sum(1 for event in prepared.events if event.event_type == "REMOVIDO")
        adjustments = sum(1 for event in prepared.events if event.event_type == "AJUSTE")
        return {
            "linhas_preparadas": len(prepared.rows),
            "remocoes_auditoria": removals,
            "ajustes_auditoria": adjustments,
            "erros_auditoria": len(prepared.issues),
            "relatorio_auditoria_csv": str(csv_path),
            "relatorio_auditoria_xlsx": str(xlsx_path),
            "manifesto_auditoria_json": str(json_path),
        }

    def _fiscal_summary(self, kind: str, profile: MappingProfile) -> dict[str, str]:
        if kind != "fatca":
            return {}
        rule = profile.field_mappings.get("fatca.missing_us_tin_policy")
        policy = rule.fixed_value if rule and rule.source == "fixed" else DEFAULT_MISSING_US_TIN_POLICY
        if policy in {DEFAULT_MISSING_US_TIN_POLICY, "BLOCK_GENERATION"}:
            return {
                "arquivo_teste": "nao",
                "status_fiscal": "bloqueado_por_us_tax_id",
            }
        if policy in {TECHNICAL_TEST_POLICY, "PENDING_FISCAL_CONFIRMATION"}:
            return {
                "arquivo_teste": "sim",
                "status_fiscal": "pendente_confirmacao_us_tax_id",
            }
        return {"arquivo_teste": "nao", "status_fiscal": "conforme_politica_configurada"}
