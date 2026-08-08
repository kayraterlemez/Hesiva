import os
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
)

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.services import AccountHistoryService, ValidationError  # noqa: E402
from hesiva.ui.financial_dialogs import (  # noqa: E402
    DebtTransactionDialog,
    PaymentDialog,
    VoidTransactionDialog,
)
from hesiva.ui.main_window import MainWindow  # noqa: E402
from hesiva.ui.presentation import MoneyInputError, parse_money_kurus  # noqa: E402

WindowFactory = Callable[[], MainWindow]


@pytest.fixture(scope="session")
def application() -> QApplication:
    existing_application = QApplication.instance()
    if existing_application is not None:
        assert isinstance(existing_application, QApplication)
        return existing_application
    return QApplication([])


@pytest.fixture
def application_context(tmp_path: Path) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "financial-ui-data")
    try:
        yield context
    finally:
        context.close()


@pytest.fixture
def window_factory(
    application: QApplication,
    application_context: ApplicationContext,
) -> Iterator[WindowFactory]:
    windows: list[MainWindow] = []

    def create_window() -> MainWindow:
        window = MainWindow(application_context)
        window.show()
        application.processEvents()
        windows.append(window)
        return window

    yield create_window

    for window in windows:
        window.close()
    application.processEvents()


def item_for_customer(customer_list: QListWidget, customer_id: int) -> QListWidgetItem:
    for row in range(customer_list.count()):
        item = customer_list.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == customer_id:
            return item
    raise AssertionError(f"Customer {customer_id} is not visible")


@pytest.mark.parametrize(
    ("value", "expected"),
    (("1250", 125_000), ("1250,50", 125_050), ("1.250,50", 125_050)),
)
def test_money_parser_accepts_strict_turkish_positive_magnitudes(
    value: str,
    expected: int,
) -> None:
    assert parse_money_kurus(value) == expected


@pytest.mark.parametrize(
    "value",
    ("", " ", "0", "0,00", "-1", "+1", "1.25", "1,234", "1.2,00", "abc"),
)
def test_money_parser_rejects_blank_zero_negative_and_malformed_values(value: str) -> None:
    with pytest.raises(MoneyInputError):
        parse_money_kurus(value)


def test_dialog_fields_follow_frozen_debt_and_payment_contracts(
    application: QApplication,
    application_context: ApplicationContext,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Dialog Customer")
        active = services.animal.create_animal(
            customer.id,
            ear_tag="TR-1",
            name="Boncuk",
        )
        archived = services.animal.create_animal(customer.id, name="Archived")
        services.animal.archive_animal(archived.id)
        other = services.customer.create_customer("Other Customer")
        services.animal.create_animal(other.id, name="Other Animal")
        options = services.animal.list_active_options(customer.id)
        customer_name = customer.full_name
        active_id = active.id

    debt = DebtTransactionDialog(customer_name, options)
    assert debt.customer_input.isReadOnly()
    assert debt.amount_input.text() == ""
    assert [debt.animal_combo.itemData(index) for index in range(debt.animal_combo.count())] == [
        None,
        active_id,
    ]
    assert debt.findChild(QPlainTextEdit, "debtNotesInput") is debt.notes_input
    debt.close()

    payment = PaymentDialog(customer_name, 50_000)
    assert payment.customer_input.isReadOnly()
    assert payment.amount_input.text() == ""
    assert payment.description_input.text() == "Tahsilat"
    assert not payment.description_input.isReadOnly()
    assert payment.findChild(QComboBox) is None
    assert payment.findChild(QPlainTextEdit) is None
    assert {
        field.objectName()
        for field in payment.findChildren(QLineEdit)
        if field.objectName().startswith("payment")
    } == {
        "paymentCustomerInput",
        "paymentAmountInput",
        "paymentDescriptionInput",
    }
    payment.amount_input.setText("700")
    application.processEvents()
    assert payment.after_balance_value.text() == "200,00 TL Fazla Ödeme"
    payment.close()


def test_debt_payment_and_void_workflow_refreshes_all_financial_views(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Financial Customer")
        animal = services.animal.create_animal(customer.id, name="Boncuk")
        customer_id = customer.id
        animal_id = animal.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))
    assert window.new_transaction_button.isEnabled()
    assert window.receive_payment_button.isEnabled()
    assert window.account_history_stack.currentWidget() is window.account_history_empty_state

    def enter_debt() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, DebtTransactionDialog)
        dialog.date_input.setDate(QDate(2026, 8, 1))
        dialog.description_input.setText("Muayene ve ilaç")
        dialog.amount_input.setText("1.250,50")
        dialog.animal_combo.setCurrentIndex(dialog.animal_combo.findData(animal_id))
        dialog.notes_input.setPlainText("İsteğe bağlı not")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, enter_debt)
    window._open_debt_transaction_dialog()

    assert window.general_total_debt_value.text() == "1.250,50 TL"
    assert window.general_balance_value.text() == "1.250,50 TL Borç"
    customer_item = item_for_customer(window.customer_list, customer_id)
    customer_row = window.customer_list.itemWidget(customer_item)
    assert customer_row.findChild(QLabel, "customerRowBalance").text() == "1.250,50 TL Borç"
    assert window.account_history_table.rowCount() == 1
    assert window.account_history_table.item(0, 2).text() == "Muayene ve ilaç"
    assert window.account_history_table.item(0, 3).text() == "Boncuk"
    assert window.account_history_table.item(0, 4).text() == "1.250,50 TL"
    assert window.account_history_table.item(0, 5).text() == ""

    def enter_payment() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, PaymentDialog)
        dialog.date_input.setDate(QDate(2026, 8, 2))
        dialog.amount_input.setText("2.000")
        assert dialog.description_input.text() == "Tahsilat"
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, enter_payment)
    window._open_payment_dialog()

    assert window.general_total_payment_value.text() == "2.000,00 TL"
    assert window.general_balance_value.text() == "749,50 TL Fazla Ödeme"
    assert "Alacak" not in window.general_balance_value.text()
    customer_item = item_for_customer(window.customer_list, customer_id)
    customer_row = window.customer_list.itemWidget(customer_item)
    assert customer_row.findChild(QLabel, "customerRowBalance").text() == "749,50 TL Fazla Ödeme"
    assert window.account_history_table.rowCount() == 2
    assert window.account_history_table.item(0, 5).text() == "2.000,00 TL"
    assert window.account_history_table.item(0, 6).text() == "749,50 TL Fazla Ödeme"
    payment_id = window.account_history_table.item(0, 0).data(Qt.ItemDataRole.UserRole)

    window.account_history_table.selectRow(0)
    application.processEvents()
    assert window.void_transaction_button.isEnabled()

    def confirm_void_without_reason() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, VoidTransactionDialog)
        assert dialog.reason() == ""
        assert dialog.cancel_button.isDefault()
        QTest.mouseClick(dialog.void_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, confirm_void_without_reason)
    window._open_void_transaction_dialog()

    assert window.account_history_table.rowCount() == 2
    assert window.account_history_table.item(0, 0).data(Qt.ItemDataRole.UserRole) == payment_id
    assert "İptal" in window.account_history_table.item(0, 2).text()
    assert window.account_history_table.item(0, 5).text() == "2.000,00 TL"
    assert window.account_history_table.item(0, 6).text() == "1.250,50 TL Borç"
    window.account_history_table.selectRow(0)
    application.processEvents()
    assert not window.void_transaction_button.isEnabled()
    assert window.general_total_payment_value.text() == "0,00 TL"
    assert window.general_balance_value.text() == "1.250,50 TL Borç"
    assert window.general_last_transaction_value.text() == "01.08.2026"
    customer_item = item_for_customer(window.customer_list, customer_id)
    customer_row = window.customer_list.itemWidget(customer_item)
    assert customer_row.findChild(QLabel, "customerRowBalance").text() == "1.250,50 TL Borç"
    assert customer_row.findChild(QLabel, "customerRowLastTransaction").text() == (
        "Son: 01.08.2026"
    )

    with application_context.services() as services:
        transactions = services.transaction.list_for_customer(customer_id, include_voided=True)
    assert len(transactions) == 2
    debt, payment = transactions
    assert debt.amount_kurus == 125_050
    assert debt.animal_id == animal_id
    assert debt.note == "İsteğe bağlı not"
    assert payment.amount_kurus == -200_000
    assert payment.animal_id is None
    assert payment.note is None
    assert payment.voided_at is not None
    assert payment.void_reason is None


def test_service_validation_failure_keeps_debt_dialog_open_and_usable(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Failure Customer")
        customer_id = customer.id
    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))
    interaction: dict[str, object] = {}

    def reject_write(_service: object, *_args: object, **_kwargs: object) -> object:
        raise ValidationError("Rejected")

    monkeypatch.setattr(
        "hesiva.services.transaction_service.TransactionService.create_debt",
        reject_write,
    )

    def attempt_and_close() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, DebtTransactionDialog)
        dialog.description_input.setText("Valid looking")
        dialog.amount_input.setText("100")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        interaction["visible_after_failure"] = dialog.isVisible()
        interaction["error"] = dialog.error_label.text()
        dialog.reject()

    QTimer.singleShot(0, attempt_and_close)
    window._open_debt_transaction_dialog()

    assert interaction == {
        "visible_after_failure": True,
        "error": "İşlem kaydedilemedi. Lütfen alanları kontrol edin.",
    }
    assert window.account_history_table.rowCount() == 0


def test_history_service_is_called_once_per_selected_customer_load(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Query Count Customer")
        for day in range(1, 5):
            services.transaction.create_debt(
                customer.id,
                transaction_date=date(2026, 8, day),
                description=f"Debt {day}",
                amount_kurus=day * 1_000,
            )
        customer_id = customer.id
    calls: list[int] = []
    original = AccountHistoryService.list_for_customer

    def count_call(service: AccountHistoryService, target_customer_id: int):
        calls.append(target_customer_id)
        return original(service, target_customer_id)

    monkeypatch.setattr(AccountHistoryService, "list_for_customer", count_call)
    window = window_factory()

    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))

    assert window.account_history_table.rowCount() == 4
    assert calls == [customer_id]
    assert not hasattr(window, "_session")
    assert all(
        not hasattr(row, "_sa_instance_state") for row in window._account_history_by_id.values()
    )
    assert "İşlemi Düzenle" not in [action.text() for action in window.findChildren(QAction)]


def test_history_read_failure_has_distinct_error_state_and_keeps_customer_list(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("History Error Customer")
        customer_id = customer.id

    def reject_read(_service: AccountHistoryService, _customer_id: int) -> object:
        raise RuntimeError("technical detail")

    monkeypatch.setattr(AccountHistoryService, "list_for_customer", reject_read)
    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))

    assert window.customer_list.count() == 1
    assert window.customer_detail_stack.currentWidget() is window.customer_detail_shell
    assert window.account_history_stack.currentWidget() is window.account_history_error_state
    assert window.account_history_table.rowCount() == 0
