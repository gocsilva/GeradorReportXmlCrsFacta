from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

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
from crs_fatca_generator.services.xml_splitter_service import DITC_CRS_MAX_MB, XmlSplitterService


logger = logging.getLogger(__name__)


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
        ignore_invalid_records: bool = False,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[GenerationResult]:
        results: list[GenerationResult] = []
        self._emit_progress(progress_callback, "Preparando dados", "", 0, len(rows), "")
        file_hash = sha256_file(excel_path) if excel_path and excel_path.exists() else ""
        data_service = DataPreparationService()
        prepared = data_service.prepare(rows, profile, progress_callback=progress_callback)
        if prepared.issues and ignore_invalid_records:
            logger.info("IGNORE_INVALID_RECORDS requested issues=%s", len(prepared.issues))
            prepared = data_service.ignore_issue_rows(prepared, profile, progress_callback=progress_callback)
        self._emit_progress(progress_callback, "Preparando dados", "", len(rows), len(rows), "")
        audit_csv, audit_xlsx, audit_json = self._audit_paths(profile, excel_path)
        audit_summary = self._audit_summary(prepared, audit_csv, audit_xlsx, audit_json)
        reports: dict[str, object] = {}
        if prepared.issues:
            for kind in kinds:
                output_path = self._output_path(kind, profile)
                results.append(GenerationResult(kind, str(output_path), False, prepared.issues, {**audit_summary, **self._fiscal_summary(kind, profile), "status": "nao gerado"}))
            audit_total = max(len(prepared.original_rows), 1)
            self._emit_progress(progress_callback, "Gerando auditoria: iniciando", "", 0, audit_total, "")
            self._flush_identifier_store()
            data_service.write_audit(prepared, self._audit_dir(profile), self._audit_stem(profile, excel_path), profile, excel_path, file_hash, results, reports, progress_callback)
            self._emit_progress(progress_callback, "Gerando auditoria: finalizada", "", audit_total, audit_total, "")
            return results
        for kind in kinds:
            kind_name = kind.upper()
            kind_rows = prepared.rows
            fatca_usperson_summary: dict[str, int | str] = {}
            if kind == "fatca":
                kind_rows, skipped_rows, filter_status = self._rows_by_us_person(prepared.rows)
                fatca_usperson_summary = {
                    "filtro_fatca_usperson": filter_status,
                    "linhas_fatca_usadas": len(kind_rows),
                    "linhas_fatca_ignoradas_por_usperson": skipped_rows,
                }
                if filter_status == "aplicado":
                    self._emit_progress(progress_callback, "Filtrando FATCA por USPerson", kind_name, len(kind_rows), len(prepared.rows), "")
            schema_path = self.crs_schema if kind == "crs" else self.fatca_schema
            self._emit_progress(progress_callback, "Carregando schema", kind_name, 0, 1, schema_path.name)
            enums = SchemaInspector().enums(schema_path)
            bundle = SchemaLoader().load(kind, "3.0" if kind == "crs" else "2.0.1", schema_path)
            self._emit_progress(progress_callback, "Carregando schema", kind_name, 1, 1, schema_path.name)

            def mapping_progress(processed: int, total: int, row: dict[str, Any]) -> None:
                self._emit_progress(progress_callback, "Montando dados", kind_name, processed, total, self._row_label(row))

            self._emit_progress(progress_callback, "Montando dados", kind_name, 0, len(kind_rows), "")
            report_rows = kind_rows
            force_empty_accounts = kind == "fatca" and not kind_rows and bool(prepared.rows)
            if force_empty_accounts:
                report_rows = [prepared.rows[0]]
            report = self.mapping_service.build_report(kind, report_rows, profile, file_hash, progress_callback=mapping_progress)
            if force_empty_accounts:
                report.accounts = []
            self._emit_progress(progress_callback, "Montando dados", kind_name, len(getattr(report, "accounts", [])), len(getattr(report, "accounts", [])), "")
            reports[kind] = report
            self._emit_progress(progress_callback, "Validando regras", kind_name, 0, 1, "")
            business_issues = self.business_validator.validate(report, enums)
            self._emit_progress(progress_callback, "Validando regras", kind_name, 1, 1, "")
            output_path = self._output_path(kind, profile)
            if output_path.exists() and not overwrite:
                business_issues.append(
                    ValidationIssue("erro", "OUT001", f"O arquivo ja existe: {output_path}", "saida", suggestion="Escolha outro nome ou confirme sobrescrita.")
                )
            if any(issue.level == "erro" for issue in business_issues):
                results.append(GenerationResult(kind, str(output_path), False, business_issues, {**self._summary(report, "nao gerado"), **audit_summary, **self._fiscal_summary(kind, profile), **fatca_usperson_summary}))
                continue
            accounts_total = max(len(getattr(report, "accounts", [])), 1)

            def write_progress(processed: int, total: int, account: object) -> None:
                self._emit_progress(progress_callback, "Escrevendo XML", kind_name, processed, total, self._account_label(account))

            def part_progress(processed: int, total: int, name: str) -> None:
                self._emit_progress(progress_callback, "Separando XML por tamanho", kind_name, processed, total, name)

            self._emit_progress(progress_callback, "Escrevendo XML", kind_name, 0, accounts_total, str(output_path.name))
            size_limit = self._effective_size_limit_mb(kind, profile)
            if size_limit > 0:
                written = XmlSplitterService().write_report_parts(kind, report, output_path, profile.output.pretty_print, size_limit, progress_callback=part_progress, write_progress_callback=write_progress)
            elif kind == "crs":
                written = [(output_path, CrsGenerator().write(report, output_path, profile.output.pretty_print, progress_callback=write_progress))]
            else:
                written = [(output_path, FatcaGenerator().write(report, output_path, profile.output.pretty_print, progress_callback=write_progress))]
            self._emit_progress(progress_callback, "Escrevendo XML", kind_name, accounts_total, accounts_total, str(output_path.name))
            self._emit_progress(progress_callback, "Validando XSD", kind_name, 0, 1, schema_path.name)
            xsd_issues: list[ValidationIssue] = []
            for part_index, (part_path, tree) in enumerate(written, 1):
                self._emit_progress(progress_callback, "Validando XSD", kind_name, part_index, len(written), part_path.name)
                xsd_issues.extend(self.xml_validator.validate_tree(tree, schema_path, kind))
            self._emit_progress(progress_callback, "Validando XSD", kind_name, 1, 1, schema_path.name)
            valid = not xsd_issues
            xml_paths = [str(path) for path, _tree in written]
            results.append(
                GenerationResult(
                    kind=kind,
                    xml_path="; ".join(xml_paths),
                    valid=valid,
                    issues=xsd_issues,
                    summary={
                        **self._summary(report, "valido" if valid else "invalido"),
                        **audit_summary,
                        **self._fiscal_summary(kind, profile),
                        **fatca_usperson_summary,
                        "schema_hashes": ",".join(bundle.hashes.values()),
                        "arquivos_xml": "; ".join(xml_paths),
                        "quantidade_arquivos_xml": len(xml_paths),
                        "limite_mb": size_limit,
                        "limite_configurado_mb": self._configured_size_limit_mb(kind, profile),
                        "regra_divisao_xml": self._split_rule_label(kind, size_limit),
                        "limite_crs_ditc_auto": "sim" if kind == "crs" and profile.output.crs_size_limit_mb <= 0 else "nao",
                    },
                )
            )
        audit_total = max(len(prepared.original_rows), 1)
        self._emit_progress(progress_callback, "Gerando auditoria: iniciando", "", 0, audit_total, "")
        self._flush_identifier_store()
        data_service.write_audit(prepared, self._audit_dir(profile), self._audit_stem(profile, excel_path), profile, excel_path, file_hash, results, reports, progress_callback)
        self._emit_progress(progress_callback, "Gerando auditoria: finalizada", "", audit_total, audit_total, "")
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

    def _effective_size_limit_mb(self, kind: str, profile: MappingProfile) -> int:
        if kind == "crs":
            configured = int(profile.output.crs_size_limit_mb or 0)
            if configured <= 0:
                return DITC_CRS_MAX_MB
            return min(configured, DITC_CRS_MAX_MB)
        return int(profile.output.fatca_size_limit_mb or 0)

    def _configured_size_limit_mb(self, kind: str, profile: MappingProfile) -> int:
        if kind == "crs":
            return int(profile.output.crs_size_limit_mb or 0)
        return int(profile.output.fatca_size_limit_mb or 0)

    def _split_rule_label(self, kind: str, size_limit: int) -> str:
        if size_limit <= 0:
            return "sem_limite"
        if kind == "crs":
            return "crs_pais_receptor_lotes_2000_limite_mb_message_ref_unico"
        return "fatca_limite_mb_message_ref_unico"

    def _flush_identifier_store(self) -> None:
        flush = getattr(self.mapping_service.identifier_store, "flush", None)
        if callable(flush):
            flush()

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

    def _rows_by_us_person(self, rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], int, str]:
        if not any(_usperson_value(row) is not None for row in rows):
            return rows, 0, "coluna_ausente"
        filtered = [row for row in rows if _is_true_value(_usperson_value(row))]
        return filtered, len(rows) - len(filtered), "aplicado"

    def _emit_progress(
        self,
        progress_callback: Callable[[dict[str, Any]], None] | None,
        phase: str,
        kind: str,
        processed: int,
        total: int,
        current_record: str,
    ) -> None:
        logger.info("PROGRESS phase=%s kind=%s processed=%s total=%s current=%s", phase, kind, processed, total, current_record)
        if progress_callback:
            progress_callback(
                {
                    "phase": phase,
                    "kind": kind,
                    "processed": processed,
                    "total": total,
                    "current_record": current_record,
                }
            )

    def _row_label(self, row: dict[str, Any]) -> str:
        excel_row = row.get("_excel_row", "")
        account = row.get("AccountNumber") or row.get("NumConta") or ""
        document = row.get("Identification Number / CPF") or row.get("DocumentoCliente") or ""
        if account:
            return f"linha {excel_row} | conta {account}"
        if document:
            return f"linha {excel_row} | documento {document}"
        return f"linha {excel_row}".strip()

    def _account_label(self, account: object) -> str:
        value = str(getattr(account, "account_number", "") or "")
        doc_ref = getattr(getattr(account, "doc_spec", None), "doc_ref_id", "")
        if value:
            return f"conta {value}"
        if doc_ref:
            return f"doc {doc_ref}"
        return ""


def _usperson_value(row: dict[str, object]) -> object | None:
    for key, value in row.items():
        normalized = "".join(char for char in str(key).lower() if char.isalnum())
        if normalized == "usperson":
            return value
    return None


def _is_true_value(value: object | None) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"true", "1", "sim", "s", "yes", "y", "verdadeiro", "x"}
