import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from hesiva.composition import ApplicationContext
from hesiva.read_models import LegacyImportPreflight, LegacyImportResult
from hesiva.services import LegacyImportError
from hesiva.ui.presentation import format_date, format_money_kurus
from hesiva.ui.theme import APPLICATION_STYLESHEET


LOGGER = logging.getLogger(__name__)
STAGE_NAMES = ("Kaynak", "Analiz", "Onay", "Aktarım", "Sonuç")


class _LegacyImportWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    progressed = Signal(str)

    def __init__(
        self,
        application_context: ApplicationContext,
        source_path: Path,
        expected_source_sha256: str | None,
    ) -> None:
        super().__init__()
        self._application_context = application_context
        self._source_path = source_path
        self._expected_source_sha256 = expected_source_sha256

    @Slot()
    def run(self) -> None:
        try:
            with self._application_context.services() as services:
                if self._expected_source_sha256 is None:
                    result = services.legacy_import.preflight(self._source_path)
                else:
                    result = services.legacy_import.import_source(
                        self._source_path,
                        expected_source_sha256=self._expected_source_sha256,
                        progress=self.progressed.emit,
                    )
        except LegacyImportError as error:
            LOGGER.warning("Legacy import operation failed: %s", type(error).__name__)
            self.failed.emit(str(error))
        except Exception as error:
            LOGGER.error("Unexpected legacy import operation failure: %s", type(error).__name__)
            self.failed.emit("Veresiye 5 kaynağı güvenli şekilde işlenemedi.")
        else:
            self.succeeded.emit(result)


class LegacyImportDialog(QDialog):
    """Frozen five-stage Veresiye 5 import workflow over short-lived services."""

    import_completed = Signal(object)

    def __init__(
        self, application_context: ApplicationContext, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._application_context = application_context
        self._source_path: Path | None = None
        self.preflight: LegacyImportPreflight | None = None
        self.import_result: LegacyImportResult | None = None
        self._busy = False
        self._operation_kind: str | None = None
        self._operation_thread: QThread | None = None
        self._operation_worker: _LegacyImportWorker | None = None
        self._override_cursor_active = False
        self.setWindowTitle("Eski Verileri İçe Aktar")
        self.setObjectName("legacyImportDialog")
        self.setModal(True)
        self.setStyleSheet(APPLICATION_STYLESHEET)
        self.resize(820, 520)
        self.setMinimumSize(720, 470)

        self.stage_title = QLabel(self)
        self.stage_title.setObjectName("legacyImportStageTitle")
        self.stage_title.setProperty("sectionHeading", True)
        self.stage_path = QLabel("1. Kaynak > 2. Analiz > 3. Onay > 4. Aktarım > 5. Sonuç", self)
        self.stage_path.setProperty("muted", True)

        self.pages = QStackedWidget(self)
        self.source_page = self._create_source_page()
        self.analysis_page = self._create_analysis_page()
        self.confirmation_page = self._create_confirmation_page()
        self.progress_page = self._create_progress_page()
        self.result_page = self._create_result_page()
        for page in (
            self.source_page,
            self.analysis_page,
            self.confirmation_page,
            self.progress_page,
            self.result_page,
        ):
            self.pages.addWidget(page)

        self.cancel_button = QPushButton("İptal", self)
        self.cancel_button.clicked.connect(self.reject)
        self.back_button = QPushButton("← Geri", self)
        self.back_button.clicked.connect(self._go_back)
        self.next_button = QPushButton("İleri →", self)
        self.next_button.setProperty("primary", True)
        self.next_button.clicked.connect(self._go_next)
        self.next_button.setDefault(True)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.back_button)
        button_row.addWidget(self.next_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(self.stage_title)
        layout.addWidget(self.stage_path)
        layout.addWidget(self.pages, 1)
        layout.addLayout(button_row)
        self._set_stage(0)

    def _create_source_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(14)
        description = QLabel(
            "Veresiye 5 yedek veya veritabanı dosyanızı seçerek müşteri ve hesap "
            "geçmişini Hesiva'ya aktarabilirsiniz.",
            page,
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        exa_label = QLabel("Veresiye 5 Yedeği Seç (.exa)", page)
        exa_label.setProperty("sectionHeading", True)
        layout.addWidget(exa_label)
        exa_row = QHBoxLayout()
        self.source_input = QLineEdit(page)
        self.source_input.setObjectName("legacyImportSourceInput")
        self.source_input.setReadOnly(True)
        self.source_input.setPlaceholderText("Yedek dosyası seçilmedi")
        self.exa_browse_button = QPushButton("Dosya Seç...", page)
        self.exa_browse_button.clicked.connect(self._choose_exa_source)
        exa_row.addWidget(self.source_input, 1)
        exa_row.addWidget(self.exa_browse_button)
        layout.addLayout(exa_row)

        self.source_error_label = QLabel(page)
        self.source_error_label.setObjectName("legacyImportSourceError")
        self.source_error_label.setProperty("errorMessage", True)
        self.source_error_label.setWordWrap(True)
        self.source_error_label.hide()
        layout.addWidget(self.source_error_label)

        advanced_label = QLabel("Veresiye Veritabanı (.edb) — Gelişmiş", page)
        advanced_label.setProperty("sectionHeading", True)
        layout.addWidget(advanced_label)
        self.edb_browse_button = QPushButton("EDB Dosyası Seç...", page)
        self.edb_browse_button.clicked.connect(self._choose_edb_source)
        layout.addWidget(self.edb_browse_button, 0, Qt.AlignmentFlag.AlignLeft)

        privacy = QLabel(
            "Kaynak yalnızca okunur. Orijinal yedek dosyası değiştirilmez veya silinmez.",
            page,
        )
        privacy.setObjectName("legacyImportPrivacyNotice")
        privacy.setProperty("infoBanner", True)
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        layout.addStretch()
        return page

    def _create_analysis_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        heading = QLabel("Seçilen kaynak doğrulandı ve içe aktarmaya hazırlandı.", page)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        grid = QGridLayout()
        self.analysis_customer_count = QLabel("-", page)
        self.analysis_transaction_count = QLabel("-", page)
        self.analysis_date_range = QLabel("-", page)
        self.analysis_skipped_count = QLabel("-", page)
        for row, (caption, value) in enumerate(
            (
                ("Müşteri Kartı", self.analysis_customer_count),
                ("Hesap Hareketi", self.analysis_transaction_count),
                ("Tarih Aralığı", self.analysis_date_range),
                ("Atlanan Yapısal Kayıtlar", self.analysis_skipped_count),
            )
        ):
            grid.addWidget(QLabel(f"{caption}:", page), row, 0)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.analysis_warning_label = QLabel(page)
        self.analysis_warning_label.setWordWrap(True)
        self.analysis_warning_label.setProperty("warningMessage", True)
        layout.addWidget(self.analysis_warning_label)
        layout.addStretch()
        return page

    def _create_confirmation_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        heading = QLabel("Aktarımı başlatmak için son onayınız bekleniyor.", page)
        heading.setProperty("sectionHeading", True)
        layout.addWidget(heading)
        notice = QLabel(
            "Müşteri ve hesap hareketleri boş Hesiva veritabanına tek işlem olarak "
            "aktarılacaktır. Orijinal kaynak değiştirilmeyecektir.",
            page,
        )
        notice.setWordWrap(True)
        notice.setProperty("infoBanner", True)
        layout.addWidget(notice)
        self.confirmation_summary = QLabel("-", page)
        self.confirmation_summary.setWordWrap(True)
        layout.addWidget(self.confirmation_summary)
        warning = QLabel(
            "Aktarım tamamlanana kadar uygulamayı kapatmayın ve güç bağlantısını kesmeyin.",
            page,
        )
        warning.setWordWrap(True)
        warning.setProperty("warningMessage", True)
        layout.addWidget(warning)
        layout.addStretch()
        return page

    def _create_progress_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        heading = QLabel("Eski Veresiye 5 verileri içe aktarılıyor, lütfen bekleyiniz...", page)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.progress_bar = QProgressBar(page)
        self.progress_bar.setRange(0, 3)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.progress_status = QLabel("Kaynak yeniden doğrulanıyor...", page)
        self.progress_status.setWordWrap(True)
        layout.addWidget(self.progress_status)
        layout.addStretch()
        return page

    def _create_result_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        self.result_heading = QLabel(page)
        self.result_heading.setObjectName("legacyImportResultHeading")
        self.result_heading.setProperty("sectionHeading", True)
        layout.addWidget(self.result_heading)
        self.result_message = QLabel(page)
        self.result_message.setObjectName("legacyImportResultMessage")
        self.result_message.setWordWrap(True)
        self.result_message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.result_message)
        layout.addStretch()
        return page

    def set_source_path(self, source_path: Path) -> None:
        """Set a selected source without analyzing it, useful for explicit UI coordination."""
        self._source_path = source_path
        self.source_input.setText(str(source_path))
        self.source_error_label.clear()
        self.source_error_label.hide()

    def _choose_exa_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Veresiye 5 Yedeği Seç",
            "",
            "Veresiye 5 Yedeği (*.exa)",
        )
        if path:
            self.set_source_path(Path(path))

    def _choose_edb_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Veresiye Veritabanı Seç",
            "",
            "Veresiye Veritabanı (*.edb)",
        )
        if path:
            self.set_source_path(Path(path))

    def _go_next(self) -> None:
        stage = self.pages.currentIndex()
        if stage == 0:
            self._analyze_source()
        elif stage == 1:
            self._set_stage(2)
        elif stage == 2:
            self._run_import()
        elif stage == 4:
            self.accept()

    def _go_back(self) -> None:
        stage = self.pages.currentIndex()
        if stage in (1, 2):
            self._set_stage(stage - 1)

    def _analyze_source(self) -> None:
        if self._source_path is None:
            self.source_error_label.setText(
                "Lütfen bir Veresiye 5 .exa veya gelişmiş .edb dosyası seçin."
            )
            self.source_error_label.show()
            return
        self._set_busy(True)
        self._start_operation("analysis", expected_source_sha256=None)

    def _populate_preflight(self, preflight: LegacyImportPreflight) -> None:
        self.analysis_customer_count.setText(f"{preflight.eligible_customer_count} — Hazır")
        self.analysis_transaction_count.setText(f"{preflight.eligible_transaction_count} — Hazır")
        self.analysis_date_range.setText(
            f"{format_date(preflight.earliest_transaction_date)} – "
            f"{format_date(preflight.latest_transaction_date)}"
        )
        skipped_total = (
            preflight.skipped_placeholder_customers + preflight.skipped_zero_movement_transactions
        )
        self.analysis_skipped_count.setText(str(skipped_total))
        warning_count = len(preflight.warnings)
        self.analysis_warning_label.setText(
            f"{warning_count} doğrulama uyarısı. Atlanan kayıtlar sonuç özetinde gösterilecektir."
        )
        self.confirmation_summary.setText(
            f"Aktarılacak Veri Özeti:\n"
            f"{preflight.eligible_customer_count} Müşteri\n"
            f"{preflight.eligible_transaction_count} Hesap Hareketi\n"
            f"Toplam Borç: {format_money_kurus(preflight.total_debt_kurus)}\n"
            f"Toplam Ödeme: {format_money_kurus(preflight.total_payment_kurus)}"
        )

    def _run_import(self) -> None:
        if self._source_path is None or self.preflight is None:
            self._show_failure("Kaynak analizi bulunamadı. Lütfen işlemi yeniden başlatın.")
            return
        self._set_stage(3)
        self._set_busy(True)
        self.progress_bar.setValue(0)
        self.progress_status.setText("Kaynak yeniden doğrulanıyor...")
        self._start_operation(
            "import",
            expected_source_sha256=self.preflight.source_sha256,
        )

    def _start_operation(self, kind: str, *, expected_source_sha256: str | None) -> None:
        assert self._source_path is not None
        self._operation_kind = kind
        thread = QThread(self)
        worker = _LegacyImportWorker(
            self._application_context,
            self._source_path,
            expected_source_sha256,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._operation_succeeded)
        worker.failed.connect(self._operation_failed)
        worker.progressed.connect(self._operation_progressed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._operation_finished)
        thread.finished.connect(thread.deleteLater)
        self._operation_thread = thread
        self._operation_worker = worker
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self._override_cursor_active = True
            thread.start()
        except Exception as error:
            LOGGER.error(
                "Legacy import worker could not be started: %s",
                type(error).__name__,
            )
            self._operation_kind = None
            self._operation_worker = None
            self._operation_thread = None
            self._release_operation_ui()
            self._show_failure("Veresiye 5 kaynağı güvenli şekilde işlenemedi.")

    @Slot(str)
    def _operation_progressed(self, phase: str) -> None:
        progress_states = {
            "customers": (1, "Müşteriler aktarılıyor..."),
            "transactions": (2, "Hesap hareketleri aktarılıyor..."),
            "verification": (3, "Aktarılan veriler doğrulanıyor..."),
        }
        state = progress_states.get(phase)
        if state is not None:
            self.progress_bar.setValue(state[0])
            self.progress_status.setText(state[1])

    @Slot(object)
    def _operation_succeeded(self, result: object) -> None:
        if self._operation_kind == "analysis" and isinstance(result, LegacyImportPreflight):
            self.preflight = result
            self._populate_preflight(result)
            self._set_stage(1)
            return
        if self._operation_kind != "import" or not isinstance(result, LegacyImportResult):
            self._show_failure("Veri aktarımı sonucu güvenli şekilde doğrulanamadı.")
            return
        self.progress_bar.setValue(3)
        self.progress_status.setText("Doğrulama tamamlandı.")
        self.import_result = result
        self.result_heading.setText("Aktarım Başarıyla Tamamlandı")
        self.result_message.setText(
            f"{result.imported_customer_count} müşteri ve "
            f"{result.imported_transaction_count} hesap hareketi doğrulanarak aktarıldı.\n"
            f"{result.skipped_placeholder_customers} boş müşteri kaydı ve "
            f"{result.skipped_zero_movement_transactions} sıfır hareket kaydı atlandı.\n"
            f"Uyarı: {len(result.warnings)}"
        )
        self._set_stage(4)
        self.import_completed.emit(result)

    @Slot(str)
    def _operation_failed(self, message: str) -> None:
        self._show_failure(message)

    @Slot()
    def _operation_finished(self) -> None:
        self._release_operation_ui()
        self._operation_kind = None
        self._operation_worker = None
        self._operation_thread = None

    def _release_operation_ui(self) -> None:
        if self._override_cursor_active:
            QApplication.restoreOverrideCursor()
            self._override_cursor_active = False
        self._set_busy(False)

    def _show_failure(self, message: str) -> None:
        self.import_result = None
        self.result_heading.setText("Veriler İçe Aktarılamadı")
        self.result_message.setText(
            f"Veri aktarımı tamamlanamadı.\n\n{message}\n\n"
            "Orijinal kaynak değiştirilmedi. Hedefte kısmi aktarım bırakılmadı."
        )
        self._set_stage(4)

    def _set_stage(self, stage: int) -> None:
        self.pages.setCurrentIndex(stage)
        self.stage_title.setText(f"Adım {stage + 1}/5 — {STAGE_NAMES[stage]}")
        self.back_button.setVisible(stage in (1, 2))
        self.cancel_button.setText("Kapat" if stage == 4 else "İptal")
        if stage in (0, 1):
            self.next_button.setText("İleri →")
            self.next_button.setEnabled(True)
        elif stage == 2:
            self.next_button.setText("İçe Aktarmayı Başlat")
            self.next_button.setEnabled(True)
        elif stage == 3:
            self.next_button.setText("Bekleyiniz...")
            self.next_button.setEnabled(False)
        else:
            self.next_button.setText("Tamam" if self.import_result is not None else "Kapat")
            self.next_button.setEnabled(True)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.cancel_button.setEnabled(not busy)
        self.back_button.setEnabled(not busy)
        self.next_button.setEnabled(not busy)
        self.exa_browse_button.setEnabled(not busy)
        self.edb_browse_button.setEnabled(not busy)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:
        if self._busy:
            return
        super().reject()

    def done(self, result: int) -> None:
        if self._busy:
            return
        super().done(result)

    def wait_for_active_operation(self) -> None:
        """Drain an operation if the application event loop is exiting unexpectedly."""
        thread = self._operation_thread
        if thread is None:
            return
        if thread.isRunning():
            thread.quit()
            thread.wait()
        self._release_operation_ui()
        self._operation_kind = None
        self._operation_worker = None
        self._operation_thread = None
