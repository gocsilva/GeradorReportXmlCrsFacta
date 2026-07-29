from __future__ import annotations

import argparse
import sys
from pathlib import Path

from crs_fatca_generator.infrastructure.logging_config import configure_logging
from crs_fatca_generator.infrastructure.paths import default_crs_schema, default_fatca_schema
from crs_fatca_generator.models.mapping import MappingProfile, MappingRule, OutputConfig
from crs_fatca_generator.services.excel_reader import ExcelReader
from crs_fatca_generator.services.generation_service import GenerationService
from crs_fatca_generator.services.mapping_service import infer_default_profile, missing_simple_columns, simple_output_paths


def build_sample_profile(output_dir: Path) -> MappingProfile:
    profile = MappingProfile(name="Amostra automatica")
    profile.output = OutputConfig(str(output_dir / "CRS_teste.xml"), str(output_dir / "FATCA_teste.xml"))
    fixed = {
        "message.transmitting_country": "KY",
        "message.receiving_country": "BR",
        "message.reporting_period": "2025-12-31",
        "message.message_type_indic": "CRS701",
        "reporting_fi.name": "BANCO BS2 S.A.",
        "reporting_fi.in": "FI107442",
        "reporting_fi.issued_by": "KY",
        "reporting_fi.address_country": "KY",
        "reporting_fi.address_free": "South Church Street, 103, 5TH Floor, POB 1353, KY1-1108, George Town",
        "reporting_fi.doc_type_indic": "OECD1",
        "reporting_fi.filer_category": "FATCA601",
        "account.doc_type_indic": "OECD1",
        "account.account_number": "ACC1",
        "account.balance": "1000,00",
        "account.currency": "USD",
        "account.crs_dd_procedure": "CRS1201",
        "account.crs_account_type": "CRS1101",
        "holder.kind": "individual",
        "holder.first_name": "Ana",
        "holder.last_name": "Silva",
        "holder.res_country": "BR",
        "holder.address_country": "BR",
        "holder.address_free": "Rua B 2",
        "holder.crs_self_cert": "CRS901",
        "fatca.missing_us_tin_policy": "TECHNICAL_TEST_ONLY",
    }
    for key, value in fixed.items():
        profile.field_mappings[key] = MappingRule("fixed", fixed_value=value)
    for key in ("message.timestamp", "message.message_ref_id", "reporting_fi.doc_ref_id", "account.doc_ref_id"):
        profile.field_mappings[key] = MappingRule("auto")
    profile.identifier_config.prefix = "KY2025BRFI107442"
    profile.identifier_config.country = "BR"
    profile.identifier_config.use_uuid = False
    return profile


def generate_samples(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    service = GenerationService(default_crs_schema(), default_fatca_schema())
    profile = build_sample_profile(output_dir)
    results = service.generate(["crs", "fatca"], [{"_excel_row": 2}], profile, overwrite=True)
    for result in results:
        print(f"{result.kind.upper()} {result.xml_path} valid={result.valid}")
        for issue in result.issues:
            print(f"{issue.code}: {issue.message}")
    return 0 if all(result.valid for result in results) else 2


def generate_from_excel(excel_path: Path, sheet_name: str | None = None) -> int:
    reader = ExcelReader()
    sheets = reader.list_sheets(excel_path)
    sheet = sheet_name or sheets[0]
    preview = reader.preview(excel_path, sheet, 1)
    missing = missing_simple_columns(preview.headers)
    if missing:
        print("Faltam colunas obrigatorias no Excel:")
        for column in missing:
            print(f"- {column}")
        return 3
    rows = reader.read_rows(excel_path, sheet, 1)
    profile = infer_default_profile(preview.headers)
    profile.output = simple_output_paths(excel_path)
    results = GenerationService(default_crs_schema(), default_fatca_schema()).generate(["crs", "fatca"], rows, profile, excel_path, overwrite=True)
    for result in results:
        print(f"{result.kind.upper()} {result.xml_path} valid={result.valid}")
        for issue in result.issues:
            print(f"{issue.code}: {issue.message}")
    return 0 if all(result.valid for result in results) else 2


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Gerador CRS/FATCA XML")
    parser.add_argument("--self-test", action="store_true", help="Executa teste basico sem abrir GUI.")
    parser.add_argument("--generate-samples", type=Path, help="Gera XMLs de teste na pasta indicada.")
    parser.add_argument("--generate-from-excel", type=Path, help="Gera CRS/FATCA automaticamente a partir do Excel informado.")
    parser.add_argument("--sheet", help="Aba do Excel para --generate-from-excel.")
    args = parser.parse_args(argv)
    if args.self_test:
        return generate_samples(Path("tests") / "fixtures")
    if args.generate_samples:
        return generate_samples(args.generate_samples)
    if args.generate_from_excel:
        return generate_from_excel(args.generate_from_excel, args.sheet)
    from crs_fatca_generator.gui.main_window import run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
