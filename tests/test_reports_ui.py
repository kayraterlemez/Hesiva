import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget, QPushButton  # noqa: E402

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.services import ReportService  # noqa: E402
from hesiva.ui.main_window import MainWindow  # noqa: E402
from hesiva.ui.report_dialogs import (  # noqa: E402
    CustomerStatementDialog,
    MonthlySummaryDialog,
    YearlySummaryDialog,
)


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
        window.monthly_summary_action.trigger()
        window.yearly_summary_action.trigger()

        assert opened == [
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
        assert dialog.findChild(QPushButton, "reportPrintButton").isEnabled() is False
        assert dialog.findChild(QPushButton, "reportPdfButton").isEnabled() is False
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
        assert not dialog.findChild(QPushButton, "reportPrintButton").isEnabled()

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
