import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLabel  # noqa: E402

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.services import LegacyImportService  # noqa: E402
from hesiva.ui.legacy_import_dialog import LegacyImportDialog, STAGE_NAMES  # noqa: E402
from hesiva.ui.main_window import MainWindow  # noqa: E402
from legacy_import_fixtures import create_default_source  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        assert isinstance(existing, QApplication)
        return existing
    return QApplication([])


@pytest.fixture
def application_context(tmp_path: Path) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "application-data")
    try:
        yield context
    finally:
        context.close()


def wait_for_operation(
    application: QApplication,
    dialog: LegacyImportDialog,
    *,
    timeout: float = 5,
) -> None:
    deadline = time.monotonic() + timeout
    while dialog._busy and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    application.processEvents()
    assert not dialog._busy
    assert dialog._operation_thread is None
    assert dialog._operation_worker is None


def test_wizard_has_frozen_five_stages_and_read_only_source_choices(
    application: QApplication,
    application_context: ApplicationContext,
) -> None:
    dialog = LegacyImportDialog(application_context)
    dialog.show()
    application.processEvents()

    assert STAGE_NAMES == ("Kaynak", "Analiz", "Onay", "Aktarım", "Sonuç")
    assert dialog.pages.count() == 5
    assert dialog.pages.currentIndex() == 0
    assert dialog.stage_title.text() == "Adım 1/5 — Kaynak"
    assert dialog.source_input.isReadOnly()
    assert dialog.source_input.text() == ""
    assert dialog.exa_browse_button.text() == "Dosya Seç..."
    assert dialog.edb_browse_button.text() == "EDB Dosyası Seç..."
    source_texts = [label.text() for label in dialog.source_page.findChildren(QLabel)]
    assert any("Gelişmiş" in text for text in source_texts)
    assert any("Orijinal yedek dosyası değiştirilmez" in text for text in source_texts)

    dialog.close()


def test_missing_source_error_stays_on_source_step_and_is_user_facing(
    application: QApplication,
    application_context: ApplicationContext,
) -> None:
    dialog = LegacyImportDialog(application_context)
    dialog.show()

    dialog._go_next()
    application.processEvents()

    assert dialog.pages.currentIndex() == 0
    assert not dialog.source_error_label.isHidden()
    assert ".exa" in dialog.source_error_label.text()
    assert application_context.active_service_scopes == 0
    dialog.close()


def test_busy_wizard_cannot_be_dismissed_by_escape_reject_done_or_close(
    application: QApplication,
    application_context: ApplicationContext,
) -> None:
    dialog = LegacyImportDialog(application_context)
    dialog.show()
    dialog._set_busy(True)

    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    application.processEvents()
    assert dialog.isVisible()

    dialog.reject()
    dialog.done(QDialog.DialogCode.Rejected.value)
    assert dialog.close() is False
    application.processEvents()
    assert dialog.isVisible()

    dialog._set_busy(False)
    assert dialog.close() is True


def test_worker_start_failure_releases_busy_state_and_override_cursor(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_start(_thread: QThread) -> None:
        raise RuntimeError("PRIVATE THREAD START DETAIL")

    assert QApplication.overrideCursor() is None
    monkeypatch.setattr(QThread, "start", fail_start)
    dialog = LegacyImportDialog(application_context)
    dialog.set_source_path(tmp_path / "source.exa")

    dialog._go_next()
    application.processEvents()

    assert dialog.pages.currentIndex() == 4
    assert dialog.result_heading.text() == "Veriler İçe Aktarılamadı"
    assert "güvenli şekilde işlenemedi" in dialog.result_message.text()
    assert "PRIVATE THREAD START DETAIL" not in dialog.result_message.text()
    assert dialog._busy is False
    assert dialog._operation_kind is None
    assert dialog._operation_thread is None
    assert dialog._operation_worker is None
    assert dialog._override_cursor_active is False
    assert QApplication.overrideCursor() is None
    assert dialog.next_button.isEnabled()
    dialog.close()


def test_unexpected_event_loop_exit_drains_worker_before_dialog_cleanup(
    application: QApplication,
    application_context: ApplicationContext,
) -> None:
    events: list[str] = []

    class RunningThread:
        def isRunning(self) -> bool:
            return True

        def quit(self) -> None:
            events.append("quit-requested")

        def wait(self) -> bool:
            events.append("worker-stopped")
            return True

    dialog = LegacyImportDialog(application_context)
    dialog._set_busy(True)
    dialog._operation_kind = "import"
    dialog._operation_thread = RunningThread()  # type: ignore[assignment]
    dialog._operation_worker = object()  # type: ignore[assignment]

    dialog.wait_for_active_operation()

    assert events == ["quit-requested", "worker-stopped"]
    assert dialog._busy is False
    assert dialog._operation_thread is None
    assert dialog._operation_worker is None
    assert dialog._operation_kind is None


def test_busy_escape_keeps_real_worker_owned_until_it_finishes(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "blocking-source.exa")
    entered = threading.Event()
    release = threading.Event()
    original_preflight = LegacyImportService.preflight

    def blocking_preflight(self: LegacyImportService, source_path: Path):  # noqa: ANN202
        entered.set()
        assert release.wait(timeout=5)
        return original_preflight(self, source_path)

    monkeypatch.setattr(LegacyImportService, "preflight", blocking_preflight)
    dialog = LegacyImportDialog(application_context)
    dialog.set_source_path(source)
    dialog.show()
    dialog._go_next()

    deadline = time.monotonic() + 5
    while not entered.is_set() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    assert entered.is_set()
    assert dialog._busy

    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    application.processEvents()

    assert dialog.isVisible()
    assert dialog._operation_thread is not None
    assert dialog._operation_thread.isRunning()

    release.set()
    wait_for_operation(application, dialog)
    assert dialog.preflight is not None
    dialog.close()


def test_synthetic_wizard_preflight_confirmation_and_atomic_import(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    dialog = LegacyImportDialog(application_context)
    completed = []
    dialog.import_completed.connect(completed.append)
    dialog.set_source_path(source)
    dialog.show()

    dialog._go_next()
    wait_for_operation(application, dialog)

    assert dialog.pages.currentIndex() == 1
    assert dialog.preflight is not None
    assert dialog.analysis_customer_count.text() == "2 — Hazır"
    assert dialog.analysis_transaction_count.text() == "3 — Hazır"
    assert dialog.analysis_skipped_count.text() == "2"
    assert dialog.analysis_date_range.text() == "01.01.2024 – 01.02.2024"
    assert "2 Müşteri" in dialog.confirmation_summary.text()
    assert "3 Hesap Hareketi" in dialog.confirmation_summary.text()
    assert application_context.active_service_scopes == 0

    dialog._go_next()
    assert dialog.pages.currentIndex() == 2
    assert dialog.next_button.text() == "İçe Aktarmayı Başlat"

    dialog._go_next()
    wait_for_operation(application, dialog)

    assert dialog.pages.currentIndex() == 4
    assert dialog.import_result is not None
    assert dialog.result_heading.text() == "Aktarım Başarıyla Tamamlandı"
    assert len(completed) == 1
    assert completed[0] is dialog.import_result
    assert dialog.import_result.imported_customer_count == 2
    assert dialog.import_result.imported_transaction_count == 3
    assert not hasattr(dialog.import_result, "_sa_instance_state")
    assert application_context.active_service_scopes == 0
    dialog.close()


def test_wizard_uses_each_application_service_operation_once(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    calls = {"preflight": 0, "import": 0}
    original_preflight = LegacyImportService.preflight
    original_import = LegacyImportService.import_source

    def count_preflight(self: LegacyImportService, source_path: Path):  # noqa: ANN202
        calls["preflight"] += 1
        return original_preflight(self, source_path)

    def count_import(
        self: LegacyImportService,
        source_path: Path,
        *,
        expected_source_sha256: str,
        progress=None,  # noqa: ANN001
    ):  # noqa: ANN202
        calls["import"] += 1
        return original_import(
            self,
            source_path,
            expected_source_sha256=expected_source_sha256,
            progress=progress,
        )

    monkeypatch.setattr(LegacyImportService, "preflight", count_preflight)
    monkeypatch.setattr(LegacyImportService, "import_source", count_import)
    dialog = LegacyImportDialog(application_context)
    dialog.set_source_path(source)

    dialog._go_next()
    wait_for_operation(application, dialog)
    dialog._go_next()
    dialog._go_next()
    wait_for_operation(application, dialog)

    assert calls == {"preflight": 1, "import": 1}
    assert application_context.active_service_scopes == 0
    dialog.close()


def test_wizard_distinguishes_source_failure_from_empty_data_without_raw_details(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "invalid.exa"
    source.write_bytes(b"invalid")

    def unexpected_failure(_service: LegacyImportService, _source_path: Path) -> object:
        raise RuntimeError("PRIVATE INTERNAL DETAIL")

    monkeypatch.setattr(LegacyImportService, "preflight", unexpected_failure)
    dialog = LegacyImportDialog(application_context)
    dialog.set_source_path(source)

    dialog._go_next()
    wait_for_operation(application, dialog)

    assert dialog.pages.currentIndex() == 4
    assert dialog.import_result is None
    assert dialog.result_heading.text() == "Veriler İçe Aktarılamadı"
    assert "güvenli şekilde işlenemedi" in dialog.result_message.text()
    assert "PRIVATE INTERNAL DETAIL" not in dialog.result_message.text()
    assert application_context.active_service_scopes == 0
    dialog.close()


def test_nonempty_destination_is_rejected_by_wizard_without_partial_import(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    with application_context.services() as services:
        services.customer.create_customer("Mevcut Müşteri")
    dialog = LegacyImportDialog(application_context)
    dialog.set_source_path(source)

    dialog._go_next()
    wait_for_operation(application, dialog)

    assert dialog.pages.currentIndex() == 4
    assert "yalnızca boş" in dialog.result_message.text()
    with application_context.services() as services:
        summaries = services.customer_summary.list_customer_summaries()
    assert [summary.full_name for summary in summaries] == ["Mevcut Müşteri"]
    dialog.close()


def test_main_window_menu_entry_and_post_import_refresh_use_real_imported_data(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    window = MainWindow(application_context)
    window.show()
    application.processEvents()
    assert window.legacy_import_action.text() == "Eski Verileri İçe Aktar..."
    assert window.customer_list.count() == 0

    dialog = LegacyImportDialog(application_context, window)
    dialog.import_completed.connect(window._refresh_after_legacy_import)
    dialog.set_source_path(source)
    dialog._go_next()
    wait_for_operation(application, dialog)
    dialog._go_next()
    dialog._go_next()
    wait_for_operation(application, dialog)
    application.processEvents()

    assert window.customer_list.count() == 2
    assert window.customer_count_label.text() == "Bulunan: 2 müşteri"
    assert window.customer_detail_stack.currentWidget() is window.no_customer_selected_state
    assert "başarıyla içe aktarıldı" in window.statusBar().currentMessage()
    assert application_context.active_service_scopes == 0
    dialog.close()
    window.close()
