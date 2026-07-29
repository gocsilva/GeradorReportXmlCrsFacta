from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from crs_fatca_generator.services.excel_reader import ExcelReader


def make_book(path: Path, header_row: int = 1) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Dados"
    for _ in range(header_row - 1):
        ws.append([""])
    ws.append(["Account number*", "First name*", "Last name*", "Saldo"])
    ws.append(["ACC1", "Ana", "Silva", 10.5])
    wb.save(path)


def test_le_xlsx_com_cabecalho_em_outra_linha(tmp_path: Path) -> None:
    path = tmp_path / "entrada com acentos.xlsx"
    make_book(path, header_row=3)
    preview = ExcelReader().preview(path, "Dados", header_row=3)
    assert preview.headers[:2] == ["Account number*", "First name*"]
    assert preview.rows[0]["Saldo"] == 10.5


def test_le_xlsm_sem_executar_macro(tmp_path: Path) -> None:
    path = tmp_path / "entrada.xlsm"
    make_book(path)
    preview = ExcelReader().preview(path, "Dados", header_row=1)
    assert preview.active_sheet == "Dados"
