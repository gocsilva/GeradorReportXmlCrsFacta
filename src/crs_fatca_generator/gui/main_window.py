from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from time import monotonic
from typing import Any

from PySide6.QtCore import QObject, QSignalBlocker, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from crs_fatca_generator.infrastructure.paths import default_crs_schema, default_fatca_schema, logs_dir
from crs_fatca_generator.models.mapping import GroupingRules, MappingProfile, MappingRule, OutputConfig
from crs_fatca_generator.services.crs_generator import CrsGenerator
from crs_fatca_generator.services.excel_reader import ExcelReader
from crs_fatca_generator.services.fatca_generator import FatcaGenerator
from crs_fatca_generator.services.fields import FIELD_CATALOG
from crs_fatca_generator.services.file_hash import sha256_file
from crs_fatca_generator.services.generation_service import GenerationService
from crs_fatca_generator.services.mapping_service import MappingService, infer_default_profile, missing_simple_columns, simple_output_paths
from crs_fatca_generator.services.profile_service import ProfileService
from crs_fatca_generator.services.xml_splitter_service import XmlSplitterService
from crs_fatca_generator.security.masking import mask_value


logger = logging.getLogger(__name__)
DITC_DEFAULT_PREFIX = "KY2025BRFI107442"


def neutral_start_dir() -> str:
    documents = Path.home() / "Documents"
    return str(documents if documents.exists() else Path.home())


class GenerateWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)
    progress = Signal(str, str, int, int, str, str)
    log = Signal(str)

    def __init__(
        self,
        kinds: list[str],
        rows: list[dict[str, Any]],
        profile: MappingProfile,
        excel_path: Path,
        start_row: int | None = None,
        end_row: int | None = None,
        ignore_invalid_records: bool = False,
    ) -> None:
        super().__init__()
        self.kinds = kinds
        self.rows = rows
        self.profile = profile
        self.excel_path = excel_path
        self.start_row = start_row
        self.end_row = end_row
        self.ignore_invalid_records = ignore_invalid_records

    def run(self) -> None:
        try:
            rows = self.rows
            if self.excel_path and self.excel_path.exists() and self.profile.sheet_name:
                started_at = monotonic()
                self._log(f"Iniciando leitura do Excel: {self.excel_path.name}")

                def report_read_progress(processed: int, total: int, excel_row: int, row: dict[str, Any]) -> None:
                    elapsed = max(monotonic() - started_at, 0.001)
                    remaining = max(total - processed, 0)
                    seconds_left = int((elapsed / max(processed, 1)) * remaining)
                    self.progress.emit(
                        "Lendo Excel",
                        "",
                        processed,
                        total,
                        self._record_label(row, excel_row),
                        format_duration(seconds_left),
                    )
                    if self._should_log_progress(processed, total):
                        self._log(f"Lendo Excel: {processed}/{total} | linha {excel_row} | ETA {format_duration(seconds_left)}")

                logger.info(
                    "TRACE_BUTTON_PIPELINE GenerateWorker.run -> ExcelReader.read_rows sheet=%s header_row=%s start_row=%s end_row=%s",
                    self.profile.sheet_name,
                    self.profile.header_row,
                    self.start_row,
                    self.end_row,
                )
                rows = ExcelReader().read_rows(
                    self.excel_path,
                    self.profile.sheet_name,
                    self.profile.header_row,
                    self.start_row,
                    self.end_row,
                    progress_callback=report_read_progress,
                )
            if not rows:
                rows = [{"_excel_row": 0}]
            self._log(f"Leitura concluida. Registros carregados: {len(rows)}")
            self.progress.emit("Iniciando geracao", "", 0, max(len(rows), 1), "Leitura concluida", "calculando")
            logger.info(
                "TRACE_BUTTON_PIPELINE GenerateWorker.run -> GenerationService.generate kinds=%s rows=%s identifier_prefix=%s use_uuid=%s ignore_invalid_records=%s",
                self.kinds,
                len(rows),
                self.profile.identifier_config.prefix,
                self.profile.identifier_config.use_uuid,
                self.ignore_invalid_records,
            )
            service = GenerationService(default_crs_schema(), default_fatca_schema())
            phase_started_at: dict[tuple[str, str], float] = {}

            def report_generation_progress(event: dict[str, Any]) -> None:
                phase = str(event.get("phase") or "Processando")
                kind = str(event.get("kind") or "")
                processed = int(event.get("processed") or 0)
                total = int(event.get("total") or 0)
                key = (phase, kind)
                if processed == 0 or key not in phase_started_at:
                    phase_started_at[key] = monotonic()
                eta = "calculando"
                if processed > 0 and total > 0:
                    elapsed = max(monotonic() - phase_started_at[key], 0.001)
                    remaining = max(total - processed, 0)
                    eta = format_duration(int((elapsed / processed) * remaining))
                current_record = self._mask_progress_record(str(event.get("current_record") or ""))
                self.progress.emit(phase, kind, processed, total, current_record, eta)
                if self._should_log_progress(processed, total):
                    target = f" {kind}" if kind else ""
                    self._log(f"{phase}{target}: {processed}/{total} | atual: {current_record or '-'} | ETA {eta}")

            self._log("Chamando gerador CRS/FATCA.")
            self.finished.emit(
                service.generate(
                    self.kinds,
                    rows,
                    self.profile,
                    self.excel_path,
                    overwrite=True,
                    ignore_invalid_records=self.ignore_invalid_records,
                    progress_callback=report_generation_progress,
                )
            )
        except Exception as exc:
            self._log(f"Falha tecnica: {exc}")
            self.failed.emit(str(exc))

    def _log(self, message: str) -> None:
        logger.info("GUI_PROGRESS %s", message)
        self.log.emit(message)

    def _should_log_progress(self, processed: int, total: int) -> bool:
        if total <= 0:
            return True
        if processed in {0, 1, total}:
            return True
        interval = 1000 if total >= 10_000 else 100
        return processed % interval == 0

    def _record_label(self, row: dict[str, Any], excel_row: int) -> str:
        candidates = [
            row.get("AccountNumber"),
            row.get("NumConta"),
            row.get("Identification Number / CPF"),
            row.get("DocumentoCliente"),
            row.get("Name"),
            row.get("NomeCliente"),
        ]
        value = next((str(item).strip() for item in candidates if str(item or "").strip()), "")
        return f"linha {excel_row}" + (f" | {mask_value(value)}" if value else "")

    def _mask_progress_record(self, value: str) -> str:
        if not value:
            return ""
        if "|" in value:
            prefix, suffix = value.rsplit("|", 1)
            return f"{prefix.strip()} | {mask_value(suffix.strip())}"
        if any(marker in value.lower() for marker in ("conta", "documento", "doc ")):
            parts = value.rsplit(" ", 1)
            if len(parts) == 2:
                return f"{parts[0]} {mask_value(parts[1])}"
            return mask_value(value)
        return value


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CRS/FATCA XML Generator")
        self.resize(1180, 760)
        self.excel_path: Path | None = None
        self.rows: list[dict[str, Any]] = []
        self.preview_rows: list[dict[str, Any]] = []
        self.headers: list[str] = []
        self.profile = MappingProfile()
        self.profile_service = ProfileService()
        self.excel_reader = ExcelReader()
        self.thread: QThread | None = None
        self.worker: GenerateWorker | None = None
        self._progress_started_at: float | None = None
        self._progress_last_at: float | None = None
        self._progress_base_text = ""
        self._log_lines: list[str] = []
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(1000)
        self.progress_timer.timeout.connect(self.refresh_progress_status)
        self._build_ui()

    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._file_tab(), "1. Excel")
        self.tabs.addTab(self._type_tab(), "2. Declaração")
        self.tabs.addTab(self._general_tab(), "3. Informações")
        self.tabs.addTab(self._mapping_tab(), "4. Mapeamento")
        self.tabs.addTab(self._grouping_tab(), "5. Agrupamentos")
        self.tabs.addTab(self._generate_tab(), "6. Validação e geração")
        self.tabs.addTab(self._split_tab(), "7. Dividir XML")

        menu = self.menuBar().addMenu("Arquivo")
        open_profile = QAction("Abrir perfil", self)
        open_profile.triggered.connect(self.open_profile)
        save_profile = QAction("Salvar perfil", self)
        save_profile.triggered.connect(self.save_profile)
        clear_history = QAction("Limpar histórico local", self)
        clear_history.triggered.connect(self.clear_history)
        menu.addActions([open_profile, save_profile, clear_history])

    def _file_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.excel_path_edit = QLineEdit()
        self.excel_path_edit.setReadOnly(True)
        select = QPushButton("Selecionar Excel")
        select.clicked.connect(self.select_excel)
        row.addWidget(select)
        row.addWidget(self.excel_path_edit)
        layout.addLayout(row)
        simple_actions = QHBoxLayout()
        execute_now = QPushButton("Executar agora")
        execute_now.setObjectName("execute_now_button")
        execute_now.setMinimumHeight(44)
        execute_now.clicked.connect(self.execute_simple)
        simple_actions.addWidget(execute_now)
        layout.addLayout(simple_actions)
        self.missing_fields_label = QLabel("Selecione o Excel para verificar as colunas obrigatorias.")
        layout.addWidget(self.missing_fields_label)
        opts = QHBoxLayout()
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self.load_preview)
        self.header_row_spin = QSpinBox()
        self.header_row_spin.setRange(1, 200)
        self.header_row_spin.setValue(1)
        self.header_row_spin.valueChanged.connect(self.load_preview)
        self.start_row_spin = QSpinBox()
        self.start_row_spin.setRange(0, 1_000_000)
        self.end_row_spin = QSpinBox()
        self.end_row_spin.setRange(0, 1_000_000)
        opts.addWidget(QLabel("Aba"))
        opts.addWidget(self.sheet_combo)
        opts.addWidget(QLabel("Linha de cabeçalho"))
        opts.addWidget(self.header_row_spin)
        opts.addWidget(QLabel("Linha inicial"))
        opts.addWidget(self.start_row_spin)
        opts.addWidget(QLabel("Linha final"))
        opts.addWidget(self.end_row_spin)
        layout.addLayout(opts)
        self.preview_table = QTableWidget()
        layout.addWidget(self.preview_table)
        self.preview_info = QLabel()
        layout.addWidget(self.preview_info)
        return page

    def _type_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.crs_check = QCheckBox("CRS XML v3.0")
        self.crs_check.setChecked(True)
        self.fatca_check = QCheckBox("FATCA XML v2.0.1")
        self.fatca_check.setChecked(True)
        self.crs_schema_edit = QLineEdit(str(default_crs_schema()))
        self.fatca_schema_edit = QLineEdit(str(default_fatca_schema()))
        form.addRow("Gerar CRS", self.crs_check)
        form.addRow("Gerar FATCA", self.fatca_check)
        form.addRow("Schema CRS", self.crs_schema_edit)
        form.addRow("Schema FATCA", self.fatca_schema_edit)
        form.addRow(QLabel("O CPF ou CNPJ brasileiro nao deve ser utilizado automaticamente como Tax ID dos Estados Unidos."))
        form.addRow(QLabel("A ausencia do US Tax ID pode exigir omissao do campo, codigo oficial de motivo ou bloqueio da geracao, conforme regra fiscal."))
        form.addRow(QLabel("Nao utilize valores ficticios para preencher este campo."))
        form.addRow(QLabel("Tratamento do US Tax ID ainda nao confirmado pela area fiscal. O arquivo gerado nao deve ser considerado pronto para envio definitivo."))
        self.fatca_fields: dict[str, QLineEdit | QComboBox] = {}
        self.fatca_fields["fatca.us_tin"] = QLineEdit()
        self.fatca_fields["fatca.us_tin_issued_by"] = QLineEdit("US")
        self.fatca_fields["fatca.us_tin_status"] = QLineEdit("NOT_COLLECTED")
        self.fatca_fields["fatca.us_tin_reason"] = QLineEdit("US Tax ID nao coletado na origem.")
        self.fatca_fields["fatca.us_tin_source"] = QLineEdit()
        policy = QComboBox()
        policy.addItems(["TECHNICAL_TEST_ONLY", "BLOCK_PRODUCTION", "OMIT_ELEMENT", "EMPTY_ELEMENT", "OFFICIAL_MISSING_CODE"])
        self.fatca_fields["fatca.missing_us_tin_policy"] = policy
        labels = {
            "fatca.us_tin": "US Tax ID",
            "fatca.us_tin_issued_by": "Pais emissor do Tax ID",
            "fatca.us_tin_status": "Status do US Tax ID",
            "fatca.us_tin_reason": "Motivo da ausencia",
            "fatca.us_tin_source": "Origem da informacao",
            "fatca.missing_us_tin_policy": "Politica para Tax ID ausente",
        }
        for field, label in labels.items():
            form.addRow(label, self.fatca_fields[field])
        return page

    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.general_fields: dict[str, QLineEdit] = {}
        defaults = {
            "message.transmitting_country": "KY",
            "message.receiving_country": "BR",
            "message.reporting_period": "2025-12-31",
            "message.message_type_indic": "CRS701",
            "reporting_fi.name": "BANCO BS2 S.A.",
            "reporting_fi.in": "FI107442",
            "reporting_fi.address_country": "KY",
            "reporting_fi.address_free": "South Church Street, 103, 5TH Floor, POB 1353, KY1-1108, George Town",
            "reporting_fi.filer_category": "FATCA601",
        }
        for field, default in defaults.items():
            edit = QLineEdit(default)
            self.general_fields[field] = edit
            form.addRow(FIELD_CATALOG[field]["label"], edit)
        return page

    def _mapping_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        auto = QPushButton("Detectar mapeamento dos exemplos")
        auto.clicked.connect(self.auto_map)
        buttons.addWidget(auto)
        layout.addLayout(buttons)
        self.mapping_table = QTableWidget()
        self.mapping_table.setColumnCount(6)
        self.mapping_table.setHorizontalHeaderLabels(["Campo", "Descrição", "Obrigatório", "Fonte", "Coluna", "Valor fixo/transformações"])
        self.mapping_table.setRowCount(len(FIELD_CATALOG))
        for row, (field, meta) in enumerate(FIELD_CATALOG.items()):
            self.mapping_table.setItem(row, 0, QTableWidgetItem(field))
            self.mapping_table.setItem(row, 1, QTableWidgetItem(meta["label"]))
            self.mapping_table.setItem(row, 2, QTableWidgetItem(meta["required"]))
            self.mapping_table.setItem(row, 3, QTableWidgetItem("empty"))
            self.mapping_table.setItem(row, 4, QTableWidgetItem(""))
            self.mapping_table.setItem(row, 5, QTableWidgetItem(""))
        self.mapping_table.resizeColumnsToContents()
        layout.addWidget(self.mapping_table)
        return page

    def _grouping_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.group_edits: dict[str, QLineEdit] = {}
        labels = {
            "account_key": "Chave da conta",
            "holder_key": "Chave do titular",
            "organisation_key": "Chave da organização",
            "controlling_person_key": "Chave da controlling person",
            "substantial_owner_key": "Chave do substantial owner",
            "payment_key": "Chave do pagamento",
            "reporting_group_key": "Chave do ReportingGroup",
            "reporting_fi_key": "Chave do ReportingFI",
        }
        for key, label in labels.items():
            edit = QLineEdit("Account number*" if key == "account_key" else "")
            self.group_edits[key] = edit
            form.addRow(label, edit)
        return page

    def _generate_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        out = QFormLayout()
        self.crs_output_edit = QLineEdit()
        self.fatca_output_edit = QLineEdit()
        crs_btn = QPushButton("Escolher XML CRS")
        crs_btn.clicked.connect(lambda: self.pick_output(self.crs_output_edit))
        fatca_btn = QPushButton("Escolher XML FATCA")
        fatca_btn.clicked.connect(lambda: self.pick_output(self.fatca_output_edit))
        crs_row = QHBoxLayout()
        crs_row.addWidget(self.crs_output_edit)
        crs_row.addWidget(crs_btn)
        fatca_row = QHBoxLayout()
        fatca_row.addWidget(self.fatca_output_edit)
        fatca_row.addWidget(fatca_btn)
        out.addRow("Destino CRS", crs_row)
        out.addRow("Destino FATCA", fatca_row)
        self.crs_generate_check = QCheckBox("Criar XML CRS")
        self.crs_generate_check.setChecked(self.crs_check.isChecked())
        self.fatca_generate_check = QCheckBox("Criar XML FATCA")
        self.fatca_generate_check.setChecked(self.fatca_check.isChecked())
        self.crs_check.toggled.connect(self.crs_generate_check.setChecked)
        self.crs_generate_check.toggled.connect(self.crs_check.setChecked)
        self.fatca_check.toggled.connect(self.fatca_generate_check.setChecked)
        self.fatca_generate_check.toggled.connect(self.fatca_check.setChecked)
        out.addRow("Gerar CRS", self.crs_generate_check)
        out.addRow("Gerar FATCA", self.fatca_generate_check)
        self.crs_limit_spin = QSpinBox()
        self.crs_limit_spin.setRange(0, 100_000)
        self.crs_limit_spin.setValue(0)
        self.crs_limit_spin.setSuffix(" MB")
        self.fatca_limit_spin = QSpinBox()
        self.fatca_limit_spin.setRange(0, 100_000)
        self.fatca_limit_spin.setValue(0)
        self.fatca_limit_spin.setSuffix(" MB")
        out.addRow("Limite CRS (0=150; manual usa regras DITC)", self.crs_limit_spin)
        out.addRow("Limite FATCA (manual divide por tamanho)", self.fatca_limit_spin)
        layout.addLayout(out)
        actions = QHBoxLayout()
        preview = QPushButton("Pré-visualizar XML")
        preview.clicked.connect(self.preview_xml)
        generate = QPushButton("Validar e gerar")
        generate.clicked.connect(self.generate_xml)
        open_folder = QPushButton("Abrir pasta de saída")
        open_folder.clicked.connect(self.open_output_folder)
        self.ignore_errors_button = QPushButton("Gerar ignorando registros com erro")
        self.ignore_errors_button.setObjectName("ignore_errors_button")
        self.ignore_errors_button.setVisible(False)
        self.ignore_errors_button.clicked.connect(self.generate_ignoring_errors)
        actions.addWidget(preview)
        actions.addWidget(generate)
        actions.addWidget(self.ignore_errors_button)
        actions.addWidget(open_folder)
        layout.addLayout(actions)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        layout.addWidget(self.result_text)
        layout.addWidget(QLabel("Log em tempo real"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(130)
        layout.addWidget(self.log_text)
        self.error_table = QTableWidget()
        self.error_table.setColumnCount(5)
        self.error_table.setHorizontalHeaderLabels(["Nível", "Código", "Campo", "Linha", "Mensagem"])
        layout.addWidget(self.error_table)
        return page

    def _split_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.split_input_edit = QLineEdit()
        self.split_input_edit.setReadOnly(True)
        input_btn = QPushButton("Selecionar XML")
        input_btn.clicked.connect(self.pick_split_input)
        input_row = QHBoxLayout()
        input_row.addWidget(self.split_input_edit)
        input_row.addWidget(input_btn)
        self.split_output_edit = QLineEdit()
        output_btn = QPushButton("Escolher pasta")
        output_btn.clicked.connect(self.pick_split_output_dir)
        output_row = QHBoxLayout()
        output_row.addWidget(self.split_output_edit)
        output_row.addWidget(output_btn)
        self.split_limit_spin = QSpinBox()
        self.split_limit_spin.setRange(1, 100_000)
        self.split_limit_spin.setValue(10)
        self.split_limit_spin.setSuffix(" MB")
        form.addRow("XML CRS/FATCA", input_row)
        form.addRow("Pasta de saída", output_row)
        form.addRow("Tamanho por arquivo (CRS usa regras DITC)", self.split_limit_spin)
        layout.addLayout(form)
        split_btn = QPushButton("Dividir XML")
        split_btn.clicked.connect(self.split_existing_xml)
        layout.addWidget(split_btn)
        self.split_progress = QProgressBar()
        layout.addWidget(self.split_progress)
        self.split_result_text = QTextEdit()
        self.split_result_text.setReadOnly(True)
        layout.addWidget(self.split_result_text)
        return page

    def select_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar Excel", neutral_start_dir(), "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        self.excel_path = Path(path)
        self.excel_path_edit.setText(path)
        self.result_text.setPlainText("Carregando previa do Excel...")
        QApplication.processEvents()
        preview = self.excel_reader.preview(
            self.excel_path,
            None,
            self.header_row_spin.value(),
            self.start_row_spin.value() or None,
            self.end_row_spin.value() or None,
            limit=25,
        )
        self._apply_preview(preview)

    def _apply_preview(self, preview: Any) -> None:
        self.sheet_combo.clear()
        with QSignalBlocker(self.sheet_combo):
            self.sheet_combo.addItems(preview.sheets)
            self.sheet_combo.setCurrentText(preview.active_sheet)
        self.headers = preview.headers
        self.preview_rows = preview.rows
        self.rows = []
        self.preview_table.setColumnCount(len(preview.headers))
        self.preview_table.setHorizontalHeaderLabels(preview.headers)
        self.preview_table.setRowCount(len(preview.rows))
        for r, row in enumerate(preview.rows):
            for c, header in enumerate(preview.headers):
                self.preview_table.setItem(r, c, QTableWidgetItem(str(row.get(header, "") or "")))
        self.preview_info.setText(
            f"Abas: {len(preview.sheets)} | Colunas: {len(preview.headers)} | Previa: {len(preview.rows)} linhas | Duplicados: {', '.join(preview.duplicate_headers) or 'nenhum'}"
        )
        self.auto_map()
        self.configure_simple_outputs()
        self.update_missing_fields()

    def load_preview(self) -> None:
        if not self.excel_path or not self.sheet_combo.currentText():
            return
        preview = self.excel_reader.preview(
            self.excel_path,
            self.sheet_combo.currentText(),
            self.header_row_spin.value(),
            self.start_row_spin.value() or None,
            self.end_row_spin.value() or None,
            limit=25,
        )
        self._apply_preview(preview)

    def auto_map(self) -> None:
        inferred = infer_default_profile(self.headers)
        self.profile = inferred
        self._profile_to_controls()

    def configure_simple_outputs(self) -> None:
        if not self.excel_path:
            return
        output = simple_output_paths(self.excel_path)
        self.crs_output_edit.setText(output.crs_path)
        self.fatca_output_edit.setText(output.fatca_path)

    def update_missing_fields(self) -> list[str]:
        missing = missing_simple_columns(self.headers)
        if missing:
            self.missing_fields_label.setText("Faltam colunas obrigatorias: " + ", ".join(missing))
        elif self.headers:
            self.missing_fields_label.setText("Layout reconhecido. Nenhuma coluna obrigatoria esta faltando.")
        return missing

    def execute_simple(self) -> None:
        logger.info("TRACE_BUTTON_PIPELINE MainWindow.execute_simple callback=Executar agora")
        if not self.excel_path:
            QMessageBox.warning(self, "Executar", "Selecione primeiro o arquivo Excel com os dados.")
            return
        if not self.headers:
            self.load_preview()
        missing = self.update_missing_fields()
        if missing:
            QMessageBox.warning(
                self,
                "Campos faltando",
                "O Excel nao tem todas as colunas obrigatorias:\n\n" + "\n".join(f"- {item}" for item in missing),
            )
            return
        self.configure_simple_outputs()
        self.tabs.setCurrentIndex(5)
        self.generate_xml()

    def _table_to_profile(self) -> MappingProfile:
        profile = MappingProfile(name="Perfil GUI", sheet_name=self.sheet_combo.currentText(), header_row=self.header_row_spin.value())
        profile.declaration = self._declaration_from_checks()
        profile.xsd_hashes = dict(self.profile.xsd_hashes)
        profile.identifier_config = deepcopy(self.profile.identifier_config)
        if profile.identifier_config.use_uuid or profile.identifier_config.prefix.strip().upper() == "AUTO":
            profile.identifier_config.prefix = DITC_DEFAULT_PREFIX
            profile.identifier_config.country = "BR"
            profile.identifier_config.use_uuid = False
        for field, edit in self.general_fields.items():
            if edit.text().strip():
                profile.field_mappings[field] = MappingRule("fixed", fixed_value=edit.text().strip())
        for field, widget in self.fatca_fields.items():
            value = widget.currentText().strip() if isinstance(widget, QComboBox) else widget.text().strip()
            profile.field_mappings[field] = MappingRule("fixed", fixed_value=value)
        for row in range(self.mapping_table.rowCount()):
            field = self.mapping_table.item(row, 0).text()
            source = self.mapping_table.item(row, 3).text().strip() or "empty"
            column = self.mapping_table.item(row, 4).text().strip()
            extra = self.mapping_table.item(row, 5).text().strip()
            fixed, transforms = extra, []
            if "|" in extra:
                fixed, raw_transforms = extra.split("|", 1)
                transforms = [part.strip() for part in raw_transforms.split(",") if part.strip()]
            profile.field_mappings[field] = MappingRule(source, column, fixed, transforms)
        profile.grouping = GroupingRules(**{key: edit.text().strip() for key, edit in self.group_edits.items()})
        profile.output = OutputConfig(self.crs_output_edit.text().strip(), self.fatca_output_edit.text().strip())
        profile.output.crs_size_limit_mb = self.crs_limit_spin.value()
        profile.output.fatca_size_limit_mb = self.fatca_limit_spin.value()
        return profile

    def _profile_to_table(self) -> None:
        for row in range(self.mapping_table.rowCount()):
            field = self.mapping_table.item(row, 0).text()
            rule = self.profile.field_mappings.get(field)
            if not rule:
                continue
            self.mapping_table.setItem(row, 3, QTableWidgetItem(rule.source))
            self.mapping_table.setItem(row, 4, QTableWidgetItem(rule.column))
            suffix = f"|{','.join(rule.transformations)}" if rule.transformations else ""
            self.mapping_table.setItem(row, 5, QTableWidgetItem(f"{rule.fixed_value}{suffix}"))

    def _profile_to_controls(self) -> None:
        self._apply_declaration_to_checks(getattr(self.profile, "declaration", "both"))
        self._profile_to_table()
        for key, edit in self.group_edits.items():
            edit.setText(getattr(self.profile.grouping, key))
        for field, edit in self.general_fields.items():
            rule = self.profile.field_mappings.get(field)
            if rule and rule.source == "fixed":
                edit.setText(rule.fixed_value)
        for field, widget in self.fatca_fields.items():
            rule = self.profile.field_mappings.get(field)
            if not rule or rule.source != "fixed":
                continue
            if isinstance(widget, QComboBox):
                index = widget.findText(rule.fixed_value)
                widget.setCurrentIndex(max(index, 0))
            else:
                widget.setText(rule.fixed_value)

    def kinds(self) -> list[str]:
        kinds: list[str] = []
        if self.crs_check.isChecked():
            kinds.append("crs")
        if self.fatca_check.isChecked():
            kinds.append("fatca")
        return kinds

    def _declaration_from_checks(self) -> str:
        crs = self.crs_check.isChecked()
        fatca = self.fatca_check.isChecked()
        if crs and fatca:
            return "both"
        if crs:
            return "crs"
        if fatca:
            return "fatca"
        return "none"

    def _apply_declaration_to_checks(self, declaration: str) -> None:
        value = (declaration or "both").strip().lower()
        self.crs_check.setChecked(value in {"both", "crs"})
        self.fatca_check.setChecked(value in {"both", "fatca"})

    def pick_output(self, edit: QLineEdit) -> None:
        initial = edit.text().strip() or neutral_start_dir()
        path, _ = QFileDialog.getSaveFileName(self, "Salvar XML", initial, "XML (*.xml)")
        if path:
            edit.setText(path)

    def preview_xml(self) -> None:
        try:
            profile = self._table_to_profile()
            rows = self.preview_rows or self.rows or [{"_excel_row": 0}]
            mapper = MappingService()
            blocks = []
            for kind in self.kinds():
                report = mapper.build_report(kind, rows[:5], profile, sha256_file(self.excel_path) if self.excel_path else "")
                tree = CrsGenerator().build_tree(report) if kind == "crs" else FatcaGenerator().build_tree(report)
                xml = tree_to_text_masked(tree)
                blocks.append(f"===== {kind.upper()} =====\n{xml}")
            self.result_text.setPlainText("\n\n".join(blocks))
        except Exception as exc:
            QMessageBox.warning(self, "Pré-visualização", f"Não foi possível pré-visualizar:\n{exc}")

    def generate_xml(self, ignore_invalid_records: bool = False) -> None:
        logger.info("TRACE_BUTTON_PIPELINE MainWindow.generate_xml ignore_invalid_records=%s", ignore_invalid_records)
        if not self.kinds():
            QMessageBox.warning(self, "Geração", "Selecione CRS, FATCA ou ambos.")
            return
        if self.crs_check.isChecked() and not self.crs_output_edit.text().strip():
            QMessageBox.warning(self, "Geração", "Escolha o caminho completo do XML CRS.")
            return
        if self.fatca_check.isChecked() and not self.fatca_output_edit.text().strip():
            QMessageBox.warning(self, "Geração", "Escolha o caminho completo do XML FATCA.")
            return
        self.progress.setRange(0, 0)
        self.error_table.setRowCount(0)
        self.ignore_errors_button.setVisible(False)
        self._log_lines = []
        self.log_text.clear()
        if ignore_invalid_records:
            self._append_log("Inicio da execucao ignorando registros com erro.")
        else:
            self._append_log("Inicio da execucao pelo botao da interface.")
        self.result_text.setPlainText("Lendo Excel e processando em segundo plano...")
        self._start_progress_status("Lendo Excel e processando em segundo plano...")
        profile = self._table_to_profile()
        self.thread = QThread()
        self.worker = GenerateWorker(
            self.kinds(),
            self.rows,
            profile,
            self.excel_path or Path(""),
            self.start_row_spin.value() or None,
            self.end_row_spin.value() or None,
            ignore_invalid_records,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self._append_log)
        self.worker.finished.connect(self.on_generated)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def on_progress(self, phase: str, xml_kind: str, processed: int, total: int, current_record: str, eta: str) -> None:
        if self._should_append_progress_log(processed, total):
            target = f" {xml_kind}" if xml_kind else ""
            self._append_log(f"{phase}{target}: {processed}/{total if total else '?'} | atual: {current_record or '-'} | ETA {eta}")
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(min(processed, total))
            remaining = max(total - processed, 0)
            xml_line = f"XML atual: {xml_kind or '-'}\n"
            current_line = f"Registro atual: {current_record or '-'}\n"
            self._set_progress_text(
                f"Etapa atual: {phase}\n"
                f"{xml_line}"
                f"Registros processados: {processed} de {total}\n"
                f"Registros faltantes: {remaining}\n"
                f"{current_line}"
                f"Previsao de finalizacao: {eta}"
            )
        else:
            self.progress.setRange(0, 0)
            self._set_progress_text(f"Etapa atual: {phase}\nXML atual: {xml_kind or '-'}\nRegistro atual: {current_record or '-'}")

    def on_generated(self, results: list[Any]) -> None:
        self._stop_progress_status()
        self._append_log("Geracao finalizada. Montando resumo na tela.")
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        lines: list[str] = []
        issues = []
        for result in results:
            lines.append(f"{result.kind.upper()}: {'válido' if result.valid else 'inválido'} - {result.xml_path}")
            lines.append(json.dumps(result.summary, ensure_ascii=False, indent=2))
            issues.extend(result.issues)
        can_ignore = any(issue.level == "erro" and issue.excel_row for issue in issues)
        if can_ignore and not any(result.valid for result in results):
            lines.append("")
            lines.append("Foram encontrados erros em linhas especificas. Voce pode gerar novamente ignorando esses registros com erro.")
            self.ignore_errors_button.setVisible(True)
            self._append_log("Erros de linha detectados. Botao para ignorar registros com erro liberado.")
        else:
            self.ignore_errors_button.setVisible(False)
        self.result_text.setPlainText("\n".join(lines))
        self.error_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            for col, value in enumerate([issue.level, issue.code, issue.field, issue.excel_row or "", issue.message]):
                self.error_table.setItem(row, col, QTableWidgetItem(str(value)))

    def on_failed(self, message: str) -> None:
        self._stop_progress_status()
        self.ignore_errors_button.setVisible(False)
        self._append_log(f"Erro: {message}")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        QMessageBox.critical(self, "Erro", f"Falha técnica:\n{message}\n\nLog: {logs_dir() / 'app.log'}")

    def generate_ignoring_errors(self) -> None:
        answer = QMessageBox.question(
            self,
            "Ignorar registros com erro",
            "Gerar os XMLs removendo os registros que aparecem com erro na tabela?\n\nEssas linhas ficarao registradas na auditoria como ignoradas.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.generate_xml(ignore_invalid_records=True)

    def _start_progress_status(self, initial_text: str) -> None:
        now = monotonic()
        self._progress_started_at = now
        self._progress_last_at = now
        self._progress_base_text = initial_text
        self.progress_timer.start()

    def _set_progress_text(self, text: str) -> None:
        self._progress_base_text = text
        self._progress_last_at = monotonic()
        self.refresh_progress_status()

    def _append_log(self, message: str) -> None:
        elapsed = ""
        if self._progress_started_at is not None:
            elapsed = f"+{format_duration(int(monotonic() - self._progress_started_at))} "
        self._log_lines.append(f"{elapsed}{message}")
        if len(self._log_lines) > 500:
            self._log_lines = self._log_lines[-500:]
        self.log_text.setPlainText("\n".join(self._log_lines))
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def _should_append_progress_log(self, processed: int, total: int) -> bool:
        if total <= 0:
            return True
        if processed in {0, 1, total}:
            return True
        interval = 1000 if total >= 10_000 else 100
        return processed % interval == 0

    def refresh_progress_status(self) -> None:
        if self._progress_started_at is None:
            return
        now = monotonic()
        elapsed = format_duration(int(now - self._progress_started_at))
        since_update = format_duration(int(now - (self._progress_last_at or self._progress_started_at)))
        self.result_text.setPlainText(
            f"{self._progress_base_text}\n"
            f"Tempo decorrido: {elapsed}\n"
            f"Ultima atualizacao: ha {since_update}"
        )

    def _stop_progress_status(self) -> None:
        self.progress_timer.stop()
        self._progress_started_at = None
        self._progress_last_at = None
        self._progress_base_text = ""

    def open_output_folder(self) -> None:
        path = Path(self.crs_output_edit.text() or self.fatca_output_edit.text()).parent
        if path.exists():
            os.startfile(path)

    def save_profile(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Salvar perfil", str(Path(neutral_start_dir()) / "perfil.json"), "JSON (*.json)")
        if path:
            self.profile_service.save(self._table_to_profile(), Path(path))

    def open_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir perfil", neutral_start_dir(), "JSON (*.json)")
        if not path:
            return
        self.profile = self.profile_service.load(Path(path))
        self._profile_to_controls()
        self.crs_output_edit.setText(self.profile.output.crs_path)
        self.fatca_output_edit.setText(self.profile.output.fatca_path)
        self.crs_limit_spin.setValue(getattr(self.profile.output, "crs_size_limit_mb", 0))
        self.fatca_limit_spin.setValue(getattr(self.profile.output, "fatca_size_limit_mb", 0))

    def pick_split_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar XML CRS/FATCA", neutral_start_dir(), "XML (*.xml)")
        if not path:
            return
        self.split_input_edit.setText(path)
        if not self.split_output_edit.text().strip():
            self.split_output_edit.setText(str(Path(path).with_name(f"{Path(path).stem}_partes")))

    def pick_split_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Escolher pasta de saída", neutral_start_dir())
        if path:
            self.split_output_edit.setText(path)

    def split_existing_xml(self) -> None:
        xml_path = Path(self.split_input_edit.text().strip())
        output_dir = Path(self.split_output_edit.text().strip())
        if not xml_path.exists():
            QMessageBox.warning(self, "Dividir XML", "Selecione um XML CRS ou FATCA existente.")
            return
        if not output_dir:
            QMessageBox.warning(self, "Dividir XML", "Escolha a pasta de saída.")
            return
        self.split_progress.setRange(0, 0)
        self.split_result_text.setPlainText("Dividindo XML...")
        QApplication.processEvents()

        def report_progress(processed: int, total: int, name: str) -> None:
            self.split_progress.setRange(0, total)
            self.split_progress.setValue(processed)
            self.split_result_text.setPlainText(f"Arquivos gerados: {processed} de {total}\nArquivo atual: {name}")
            QApplication.processEvents()

        try:
            paths = XmlSplitterService().split_existing_xml(xml_path, output_dir, self.split_limit_spin.value(), progress_callback=report_progress)
        except Exception as exc:
            self.split_progress.setRange(0, 100)
            self.split_progress.setValue(0)
            QMessageBox.critical(self, "Dividir XML", f"Não foi possível dividir o XML:\n{exc}")
            return
        self.split_progress.setRange(0, max(len(paths), 1))
        self.split_progress.setValue(len(paths))
        lines = [f"XML dividido em {len(paths)} arquivo(s):", ""]
        lines.extend(str(path) for path in paths)
        self.split_result_text.setPlainText("\n".join(lines))

    def clear_history(self) -> None:
        from crs_fatca_generator.infrastructure.database import IdentifierStore

        IdentifierStore().clear()
        QMessageBox.information(self, "Histórico", "Histórico local de identificadores limpo.")


def tree_to_text_masked(tree: Any) -> str:
    text = etree_tostring(tree)
    for marker in ("AccountNumber", "TIN", "IN"):
        text = _mask_tag(text, marker)
    return text


def etree_tostring(tree: Any) -> str:
    from lxml import etree

    return etree.tostring(tree, encoding="unicode", pretty_print=True)


def _mask_tag(text: str, tag: str) -> str:
    import re

    return re.sub(rf"(<[^>]*{tag}[^>]*>)([^<]+)(</[^>]*{tag}>)", lambda m: m.group(1) + mask_value(m.group(2)) + m.group(3), text)


def format_duration(seconds: int) -> str:
    if seconds <= 1:
        return "instantes"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}min {sec:02d}s"
    if minutes:
        return f"{minutes}min {sec:02d}s"
    return f"{sec}s"


def run_gui() -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
