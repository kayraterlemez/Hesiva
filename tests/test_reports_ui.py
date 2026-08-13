import logging
import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt  # noqa: E402
from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget, QMessageBox, QPushButton  # noqa: E402

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.services import ReportService  # noqa: E402
from hesiva.ui.main_window import MainWindow  # noqa: E402
from hesiva.ui import report_output  # noqa: E402
from hesiva.ui.report_dialogs import (  # noqa: E402
    CustomerStatementDialog,
    MonthlySummaryDialog,
    YearlySummaryDialog,
)
from hesiva.ui.theme import APPLICATION_STYLESHEET  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing_application = QApplication.instance()
    if existing_application is not None:
        assert isinstance(existing_application, QApplication)
        return existing_application
    return QApplication([])


@pytest.fixture
def application_context(tmp_path: Path) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "reports-ui-data")
    try:
        yield context
    finally:
        context.close()


def seed_report_data(application_context: ApplicationContext) -> tuple[int, int]:
    with application_context.services() as services:
        first = services.customer.create_customer("Statement Customer", phone="0532 000 00 00")
        second = services.customer.create_customer("Other Customer")
        services.transaction.create_debt(
            first.id,
            transaction_date=date(2025, 12, 31),
            description="Opening",
            amount_kurus=100_000,
        )
        services.transaction.create_debt(
            first.id,
            transaction_date=date(2026, 8, 1),
            description="Debt",
            amount_kurus=50_000,
        )
        payment = services.transaction.create_payment(
            first.id,
            transaction_date=date(2026, 8, 2),
            description="Payment",
            amount_kurus=150_000,
        )
        services.transaction.create_payment(
            first.id,
            transaction_date=date(2026, 8, 3),
            description="Payment excess",
            amount_kurus=50_000,
        )
        services.transaction.create_debt(
            first.id,
            transaction_date=date(2026, 8, 4),
            description="Voided",
            amount_kurus=999_000,
        )
        latest = services.transaction.list_for_customer(first.id)[-1]
        services.transaction.void_transaction(latest.id, None)
        services.transaction.create_debt(
            second.id,
            transaction_date=date(2026, 8, 5),
            description="Other debt",
            amount_kurus=25_000,
        )
        assert payment.amount_kurus == -150_000
        return first.id, second.id


def test_report_menu_actions_are_safely_wired_to_correct_dialogs(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id, _ = seed_report_data(application_context)
    window = MainWindow(application_context)
    window.show()
    application.processEvents()
    try:
        assert not window.customer_statement_action.isEnabled()
        assert window.monthly_summary_action.isEnabled()
        assert window.yearly_summary_action.isEnabled()

        customer_list = window.findChild(QListWidget, "customerList")
        assert customer_list is not None
        for row in range(customer_list.count()):
            item = customer_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == customer_id:
                customer_list.setCurrentItem(item)
                break
        application.processEvents()
        assert window.customer_statement_action.isEnabled()
        assert window.account_history_print_button.isEnabled()

        opened: list[str] = []
        monkeypatch.setattr(
            CustomerStatementDialog,
            "exec",
            lambda self: opened.append(self.objectName()),
        )
        monkeypatch.setattr(
            MonthlySummaryDialog,
            "exec",
            lambda self: opened.append(self.objectName()),
        )
        monkeypatch.setattr(
            YearlySummaryDialog,
            "exec",
            lambda self: opened.append(self.objectName()),
        )
        window.customer_statement_action.trigger()
        window.account_history_print_button.click()
        window.monthly_summary_action.trigger()
        window.yearly_summary_action.trigger()

        assert opened == [
            "customerStatementDialog",
            "customerStatementDialog",
            "monthlySummaryDialog",
            "yearlySummaryDialog",
        ]
    finally:
        window.close()


def test_statement_dialog_renders_real_period_data_and_overpayment(
    application: QApplication,
    application_context: ApplicationContext,
) -> None:
    customer_id, _ = seed_report_data(application_context)
    dialog = CustomerStatementDialog(
        application_context,
        customer_id,
        reference_date=date(2026, 8, 9),
    )
    try:
        assert dialog.statement is not None
        assert dialog.customer_name_label.text() == "Statement Customer"
        assert dialog.customer_phone_label.text() == "Telefon: 0532 000 00 00"
        assert dialog.total_debt_label.text() == "500,00 TL"
        assert dialog.total_payment_label.text() == "2.000,00 TL"
        assert dialog.current_balance_label.text() == "500,00 TL Fazla Ödeme"
        assert "Alacak" not in dialog.current_balance_label.text()
        assert dialog.table.rowCount() == 3
        assert [dialog.table.item(row, 1).text() for row in range(3)] == [
            "Payment excess",
            "Payment",
            "Debt",
        ]
        assert dialog.table.item(0, 4).text() == "500,00 TL Fazla Ödeme"
        assert dialog.table.item(1, 4).text() == "0,00 TL"
        assert dialog.table.item(2, 4).text() == "1.500,00 TL Borç"
        assert dialog.findChild(QPushButton, "reportPrintButton").isEnabled()
        assert dialog.findChild(QPushButton, "reportPdfButton").isEnabled()
        assert not hasattr(dialog.statement, "_sa_instance_state")
    finally:
        dialog.close()
        application.processEvents()


def test_statement_empty_period_and_read_error_are_distinct(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id, _ = seed_report_data(application_context)
    dialog = CustomerStatementDialog(
        application_context,
        customer_id,
        reference_date=date(2027, 1, 1),
    )
    try:
        assert dialog.statement is not None
        assert dialog.statement.rows == ()
        assert "bulunmuyor" in dialog.state_label.text()
        assert not dialog.state_label.property("errorMessage")

        def fail_read(
            _service: ReportService,
            _customer_id: int,
            *,
            period_start: date,
            period_end: date,
        ) -> None:
            del period_start, period_end
            raise RuntimeError("database details must stay hidden")

        monkeypatch.setattr(ReportService, "get_customer_statement", fail_read)
        dialog.refresh_statement()
        assert dialog.statement is None
        assert dialog.state_label.property("errorMessage")
        assert "database details" not in dialog.state_label.text()
        assert not dialog.table.isVisible()
        assert not dialog.print_button.isEnabled()
        assert not dialog.pdf_button.isEnabled()
    finally:
        dialog.close()
        application.processEvents()


def test_monthly_summary_is_application_wide_and_empty_period_is_zero(
    application: QApplication,
    application_context: ApplicationContext,
) -> None:
    seed_report_data(application_context)
    dialog = MonthlySummaryDialog(
        application_context,
        reference_date=date(2026, 8, 9),
    )
    try:
        assert dialog.summary is not None
        assert dialog.debt_label.text() == "750,00 TL"
        assert dialog.payment_label.text() == "2.000,00 TL"
        assert dialog.net_label.text() == "-1.250,00 TL"
        assert "Alacak" not in dialog.net_label.text()
        assert dialog.findChild(QPushButton, "reportPrintButton").isEnabled()
        assert dialog.findChild(QPushButton, "reportPdfButton").isEnabled()

        dialog.year_input.setValue(2023)
        application.processEvents()
        assert dialog.summary is not None
        assert dialog.summary.net_kurus == 0
        assert dialog.net_label.text() == "0,00 TL"
        assert "bulunmuyor" in dialog.state_label.text()
    finally:
        dialog.close()
        application.processEvents()


def test_yearly_summary_displays_twelve_months_and_signed_net(
    application: QApplication,
    application_context: ApplicationContext,
) -> None:
    seed_report_data(application_context)
    dialog = YearlySummaryDialog(
        application_context,
        reference_date=date(2026, 8, 9),
    )
    try:
        assert dialog.summary is not None
        assert dialog.debt_label.text() == "750,00 TL"
        assert dialog.payment_label.text() == "2.000,00 TL"
        assert dialog.net_label.text() == "-1.250,00 TL"
        assert dialog.table.rowCount() == 12
        assert dialog.table.item(0, 0).text() == "Ocak"
        assert dialog.table.item(7, 0).text() == "Ağustos"
        assert dialog.table.item(11, 0).text() == "Aralık"
        assert dialog.table.item(7, 3).text() == "-1.250,00 TL"
        assert "Alacak" not in " ".join(
            dialog.table.item(row, column).text()
            for row in range(dialog.table.rowCount())
            for column in range(dialog.table.columnCount())
        )
    finally:
        dialog.close()
        application.processEvents()


def test_each_dialog_uses_one_application_facing_report_call(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id, _ = seed_report_data(application_context)
    calls = {"statement": 0, "monthly": 0, "yearly": 0}
    original_statement = ReportService.get_customer_statement
    original_monthly = ReportService.get_monthly_summary
    original_yearly = ReportService.get_yearly_summary

    def count_statement(self: ReportService, *args: object, **kwargs: object):
        calls["statement"] += 1
        return original_statement(self, *args, **kwargs)

    def count_monthly(self: ReportService, *args: object, **kwargs: object):
        calls["monthly"] += 1
        return original_monthly(self, *args, **kwargs)

    def count_yearly(self: ReportService, *args: object, **kwargs: object):
        calls["yearly"] += 1
        return original_yearly(self, *args, **kwargs)

    monkeypatch.setattr(ReportService, "get_customer_statement", count_statement)
    monkeypatch.setattr(ReportService, "get_monthly_summary", count_monthly)
    monkeypatch.setattr(ReportService, "get_yearly_summary", count_yearly)
    dialogs = [
        CustomerStatementDialog(
            application_context,
            customer_id,
            reference_date=date(2026, 8, 9),
        ),
        MonthlySummaryDialog(application_context, reference_date=date(2026, 8, 9)),
        YearlySummaryDialog(application_context, reference_date=date(2026, 8, 9)),
    ]
    try:
        assert calls == {"statement": 1, "monthly": 1, "yearly": 1}
    finally:
        for dialog in dialogs:
            dialog.close()
        application.processEvents()


def test_cancelled_pdf_save_creates_no_output(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_report_data(application_context)
    dialog = MonthlySummaryDialog(application_context, reference_date=date(2026, 8, 9))
    writes: list[object] = []
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QFileDialog.getSaveFileName",
        lambda *_args: ("", ""),
    )
    monkeypatch.setattr(
        report_output,
        "write_report_pdf",
        lambda *args: writes.append(args),
    )
    try:
        dialog.pdf_button.click()
        assert writes == []
    finally:
        dialog.close()
        application.processEvents()


def test_pdf_suffix_does_not_bypass_existing_file_confirmation(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_report_data(application_context)
    dialog = MonthlySummaryDialog(application_context, reference_date=date(2026, 8, 9))
    selected_path = tmp_path / "existing"
    final_path = tmp_path / "existing.pdf"
    final_path.write_bytes(b"existing report")
    writes: list[object] = []
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QFileDialog.getSaveFileName",
        lambda *_args: (str(selected_path), "PDF Dosyaları (*.pdf)"),
    )
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QMessageBox.question",
        lambda *_args: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(
        report_output,
        "write_report_pdf",
        lambda *args: writes.append(args),
    )
    try:
        dialog.pdf_button.click()
        assert writes == []
        assert final_path.read_bytes() == b"existing report"
    finally:
        dialog.close()
        application.processEvents()


def test_export_uses_current_refreshed_report_model(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_report_data(application_context)
    dialog = MonthlySummaryDialog(application_context, reference_date=date(2026, 8, 9))
    exported: list[object] = []
    target = tmp_path / "current.pdf"
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QFileDialog.getSaveFileName",
        lambda *_args: (str(target), "PDF Dosyaları (*.pdf)"),
    )
    monkeypatch.setattr(
        report_output,
        "write_report_pdf",
        lambda report, _path: exported.append(report),
    )
    try:
        dialog.pdf_button.click()
        dialog.year_input.setValue(2023)
        application.processEvents()
        dialog.pdf_button.click()

        assert len(exported) == 2
        assert isinstance(exported[0], type(dialog.summary))
        assert exported[0].year == 2026
        assert exported[0].month == 8
        assert exported[1] is dialog.summary
        assert exported[1].year == 2023
    finally:
        dialog.close()
        application.processEvents()


def test_statement_calendar_change_refreshes_before_export(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id, _ = seed_report_data(application_context)
    dialog = CustomerStatementDialog(
        application_context,
        customer_id,
        reference_date=date(2026, 8, 9),
    )
    exported: list[object] = []
    target = tmp_path / "statement.pdf"
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QFileDialog.getSaveFileName",
        lambda *_args: (str(target), "PDF Dosyaları (*.pdf)"),
    )
    monkeypatch.setattr(
        report_output,
        "write_report_pdf",
        lambda report, _path: exported.append(report),
    )
    try:
        dialog.period_start_input.setDate(QDate(2026, 8, 2))
        application.processEvents()
        dialog.pdf_button.click()

        assert dialog.statement is not None
        assert dialog.statement.period_start == date(2026, 8, 2)
        assert exported == [dialog.statement]
    finally:
        dialog.close()
        application.processEvents()


def test_report_filter_enter_does_not_implicitly_print_or_close(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_id, _ = seed_report_data(application_context)
    dialog = CustomerStatementDialog(
        application_context,
        customer_id,
        reference_date=date(2026, 8, 9),
    )
    printed: list[object] = []
    monkeypatch.setattr(
        report_output,
        "print_report",
        lambda report, _parent: printed.append(report) or True,
    )
    dialog.show()
    application.processEvents()
    try:
        close_button = dialog.findChild(QPushButton, "reportCloseButton")
        assert close_button is not None
        for button in (dialog.print_button, dialog.pdf_button, close_button):
            assert not button.autoDefault()
            assert not button.isDefault()

        dialog.period_start_input.setFocus()
        QTest.keyClick(dialog.period_start_input, Qt.Key.Key_Return)
        application.processEvents()

        assert printed == []
        assert dialog.isVisible()
        assert dialog.result() == 0
    finally:
        dialog.close()
        application.processEvents()


@pytest.mark.parametrize("report_kind", ("statement", "monthly", "yearly"))
def test_report_error_style_is_applied_and_cleared_after_recovery(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
    report_kind: str,
) -> None:
    customer_id, _ = seed_report_data(application_context)
    if report_kind == "statement":
        dialog = CustomerStatementDialog(
            application_context,
            customer_id,
            reference_date=date(2026, 8, 9),
        )
        service_method_name = "get_customer_statement"
        refresh = dialog.refresh_statement
    elif report_kind == "monthly":
        dialog = MonthlySummaryDialog(application_context, reference_date=date(2026, 8, 9))
        service_method_name = "get_monthly_summary"
        refresh = dialog.refresh_summary
    else:
        dialog = YearlySummaryDialog(application_context, reference_date=date(2026, 8, 9))
        service_method_name = "get_yearly_summary"
        refresh = dialog.refresh_summary
    dialog.setStyleSheet(APPLICATION_STYLESHEET)
    dialog.show()
    application.processEvents()
    original_service_method = getattr(ReportService, service_method_name)

    def fail_read(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic read failure")

    try:
        monkeypatch.setattr(ReportService, service_method_name, fail_read)
        refresh()
        application.processEvents()
        assert dialog.state_label.property("errorMessage")
        assert dialog.state_label.palette().color(QPalette.ColorRole.WindowText).name() == "#b4232e"

        monkeypatch.setattr(
            ReportService,
            service_method_name,
            original_service_method,
        )
        refresh()
        application.processEvents()
        assert not dialog.state_label.property("errorMessage")
        assert dialog.state_label.palette().color(QPalette.ColorRole.WindowText).name() == "#263442"
    finally:
        dialog.close()
        application.processEvents()


def test_pdf_write_error_is_user_facing_and_does_not_report_success(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_report_data(application_context)
    dialog = YearlySummaryDialog(application_context, reference_date=date(2026, 8, 9))
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QFileDialog.getSaveFileName",
        lambda *_args: (str(tmp_path / "failed.pdf"), "PDF Dosyaları (*.pdf)"),
    )
    monkeypatch.setattr(
        report_output,
        "write_report_pdf",
        lambda *_args: (_ for _ in ()).throw(report_output.ReportOutputError("disk details")),
    )
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QMessageBox.warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    try:
        dialog.pdf_button.click()
        assert warnings == [
            (
                "PDF Kaydedilemedi",
                "PDF dosyası kaydedilemedi. Lütfen konumu kontrol edip yeniden deneyin.",
            )
        ]
        assert "disk details" not in warnings[0][1]
    finally:
        dialog.close()
        application.processEvents()


def test_report_failures_do_not_log_private_paths_or_database_parameters(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    customer_id, _ = seed_report_data(application_context)
    dialog = CustomerStatementDialog(
        application_context,
        customer_id,
        reference_date=date(2026, 8, 9),
    )
    private_name = "PRIVATE CUSTOMER NAME"
    private_path = tmp_path / f"{private_name}.pdf"
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QFileDialog.getSaveFileName",
        lambda *_args: (str(private_path), "PDF Dosyaları (*.pdf)"),
    )
    monkeypatch.setattr(
        report_output,
        "write_report_pdf",
        lambda *_args: (_ for _ in ()).throw(
            report_output.ReportOutputError(
                f"[SQL: INSERT] [parameters: ('{private_name}',)] {private_path}"
            )
        ),
    )
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QMessageBox.warning",
        lambda *_args: QMessageBox.Ok,
    )
    try:
        with caplog.at_level(logging.ERROR, logger="hesiva.ui.report_dialogs"):
            dialog.pdf_button.click()
        log_text = caplog.text
        assert "ReportOutputError" in log_text
        assert private_name not in log_text
        assert str(private_path) not in log_text
        assert "parameters" not in log_text
    finally:
        dialog.close()
        application.processEvents()


def test_print_button_passes_current_model_to_native_print_boundary(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_report_data(application_context)
    dialog = YearlySummaryDialog(application_context, reference_date=date(2026, 8, 9))
    printed: list[object] = []
    warnings: list[str] = []
    monkeypatch.setattr(
        report_output,
        "print_report",
        lambda report, _parent: printed.append(report) or False,
    )
    monkeypatch.setattr(
        "hesiva.ui.report_dialogs.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    try:
        dialog.print_button.click()
        assert printed == [dialog.summary]
        assert warnings == []
    finally:
        dialog.close()
        application.processEvents()
