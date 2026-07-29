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


def test_read_rows_reporta_progresso_com_total_e_linha_atual(tmp_path: Path) -> None:
    path = tmp_path / "entrada.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Dados"
    ws.append(["AccountNumber", "Name"])
    for index in range(1, 206):
        ws.append([f"ACC{index}", f"Cliente {index}"])
    wb.save(path)

    events: list[tuple[int, int, int, str]] = []

    rows = ExcelReader().read_rows(
        path,
        "Dados",
        1,
        progress_callback=lambda processed, total, excel_row, row: events.append(
            (processed, total, excel_row, str(row["AccountNumber"]))
        ),
    )

    assert len(rows) == 205
    assert events[0] == (1, 205, 2, "ACC1")
    assert events[-1] == (205, 205, 206, "ACC205")
    assert (100, 205, 101, "ACC100") in events
    assert (200, 205, 201, "ACC200") in events
