import os
import logging
from collections.abc import Callable, Iterator
from datetime import date, time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStackedWidget,
    QTabWidget,
)
from sqlalchemy.exc import StatementError  # noqa: E402

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.read_models import CustomerDetail, CustomerSummary, CustomerSummarySort  # noqa: E402
from hesiva.services import CustomerDetailService, CustomerSummaryService  # noqa: E402
from hesiva.ui.main_window import MainWindow  # noqa: E402
from hesiva.ui.presentation import format_balance_kurus, format_money_kurus  # noqa: E402

WindowFactory = Callable[[], MainWindow]


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing_application = QApplication.instance()
    if existing_application is not None:
        assert isinstance(existing_application, QApplication)
        return existing_application
    return QApplication([])


@pytest.fixture
def application_context(tmp_path: Path) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "ui-application-data")
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


@pytest.fixture
def main_window(window_factory: WindowFactory) -> MainWindow:
    return window_factory()


def customer_ids(customer_list: QListWidget) -> list[int]:
    return [
        customer_list.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(customer_list.count())
    ]


def item_for_customer(customer_list: QListWidget, customer_id: int) -> QListWidgetItem:
    for row in range(customer_list.count()):
        item = customer_list.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == customer_id:
            return item
    raise AssertionError(f"Customer {customer_id} is not visible")


def test_main_window_has_frozen_shell_structure(main_window: MainWindow) -> None:
    assert main_window.windowTitle() == "Hesiva"
    assert main_window.centralWidget() is not None
    assert main_window.minimumSize() != main_window.maximumSize()

    menu_labels = [action.text() for action in main_window.menuBar().actions()]
    assert menu_labels == ["Dosya", "İşlemler", "Rapor", "Ayarlar", "Yardım"]
    assert main_window.statusBar().currentMessage() == "Hazır"

    splitter = main_window.findChild(QSplitter, "mainSplitter")
    assert splitter is not None
    assert splitter.orientation() is Qt.Orientation.Horizontal
    assert splitter.count() == 2
    assert not splitter.childrenCollapsible()


def test_main_window_starts_without_customer_data(main_window: MainWindow) -> None:
    customer_list = main_window.findChild(QListWidget, "customerList")
    customer_list_stack = main_window.findChild(QStackedWidget, "customerListStack")
    detail_stack = main_window.findChild(QStackedWidget, "customerDetailStack")

    assert customer_list is not None
    assert customer_list.count() == 0
    assert customer_list_stack is not None
    assert customer_list_stack.currentWidget().objectName() == "customerListEmptyState"
    assert detail_stack is not None
    assert detail_stack.currentWidget().objectName() == "noCustomerSelectedState"
    assert main_window.customer_count_label.text() == "Bulunan: 0 müşteri"


def test_search_sort_and_customer_tabs_are_accessible_shell_controls(
    main_window: MainWindow,
) -> None:
    search_input = main_window.findChild(QLineEdit, "customerSearchInput")
    sort_combo = main_window.findChild(QComboBox, "customerSortCombo")
    customer_tabs = main_window.findChild(QTabWidget, "customerTabs")

    assert search_input is not None
    assert search_input.isEnabled()
    assert search_input.focusPolicy() is not Qt.FocusPolicy.NoFocus
    assert search_input.placeholderText() == "Müşteri Ara..."

    assert sort_combo is not None
    assert sort_combo.isEnabled()
    assert sort_combo.focusPolicy() is not Qt.FocusPolicy.NoFocus
    assert sort_combo.count() == 4
    assert [sort_combo.itemData(index) for index in range(sort_combo.count())] == [
        CustomerSummarySort.HIGHEST_DEBT.value,
        CustomerSummarySort.NAME.value,
        CustomerSummarySort.LAST_TRANSACTION.value,
        CustomerSummarySort.REGISTERED_ON.value,
    ]

    assert customer_tabs is not None
    assert [customer_tabs.tabText(index) for index in range(customer_tabs.count())] == [
        "Genel",
        "Hayvanlar",
        "Hesap Hareketleri",
        "Hatırlatmalar",
    ]


def test_splitter_keeps_both_panes_usable_when_window_grows(
    main_window: MainWindow,
    application: QApplication,
) -> None:
    splitter = main_window.findChild(QSplitter, "mainSplitter")
    assert splitter is not None

    main_window.resize(1366, 768)
    application.processEvents()
    reference_sizes = splitter.sizes()

    assert all(size > 0 for size in reference_sizes)
    assert reference_sizes[0] >= splitter.widget(0).minimumWidth()
    assert reference_sizes[1] > reference_sizes[0]

    main_window.resize(1920, 1080)
    application.processEvents()
    expanded_sizes = splitter.sizes()

    left_growth = expanded_sizes[0] - reference_sizes[0]
    right_growth = expanded_sizes[1] - reference_sizes[1]
    assert all(size > 0 for size in expanded_sizes)
    assert expanded_sizes[0] <= splitter.widget(0).maximumWidth()
    assert right_growth > left_growth


def test_balance_presentation_uses_signed_integer_semantics() -> None:
    assert format_money_kurus(700_000) == "7.000,00 TL"
    assert format_balance_kurus(200_000) == "2.000,00 TL Borç"
    assert format_balance_kurus(0) == "0,00 TL"
    overpayment = format_balance_kurus(-100_000)
    assert overpayment == "1.000,00 TL Fazla Ödeme"
    assert "Alacak" not in overpayment
    assert not overpayment.startswith("-")


def test_selected_customer_general_tab_displays_real_read_only_detail(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer(
            "Detailed Customer",
            phone="0532 123 45 67",
            address="Merkez Mah. Çiftlik Yolu No:12",
            notes="Genellikle aylık ödeme yapar.",
            registered_on=date(2022, 1, 14),
        )
        services.transaction.create_debt(
            customer.id,
            transaction_date=date(2026, 8, 6),
            description="First debt",
            amount_kurus=500_000,
        )
        services.transaction.create_debt(
            customer.id,
            transaction_date=date(2026, 8, 7),
            description="Second debt",
            amount_kurus=200_000,
        )
        services.transaction.create_payment(
            customer.id,
            transaction_date=date(2026, 8, 8),
            transaction_time=time(10, 30),
            description="Payment",
            amount_kurus=300_000,
        )
        customer_id = customer.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))

    assert window.customer_detail_stack.currentWidget() is window.customer_detail_shell
    assert window.customer_name_label.text() == "Detailed Customer"
    assert window.customer_phone_label.text() == "Telefon: 0532 123 45 67"
    assert window.general_phone_value.text() == "0532 123 45 67"
    assert window.general_address_value.text() == "Merkez Mah. Çiftlik Yolu No:12"
    assert window.general_registered_on_value.text() == "14.01.2022"
    assert window.general_last_transaction_value.text() == "08.08.2026 10:30"
    assert window.general_total_debt_value.text() == "7.000,00 TL"
    assert window.general_total_payment_value.text() == "3.000,00 TL"
    assert window.general_balance_value.text() == "4.000,00 TL Borç"
    assert window.general_notes_value.text() == "Genellikle aylık ödeme yapar."
    assert window.balance_value_label.text() == "4.000,00 TL Borç"
    assert window.last_transaction_label.text() == "Son İşlem: 08.08.2026 10:30"
    assert isinstance(window._selected_customer_detail, CustomerDetail)
    assert not hasattr(window._selected_customer_detail, "_sa_instance_state")


def test_general_tab_uses_neutral_values_for_missing_fields_and_no_activity(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Minimal Customer")
        customer_id = customer.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))

    assert window.general_phone_value.text() == "-"
    assert window.general_address_value.text() == "-"
    assert window.general_registered_on_value.text() == "-"
    assert window.general_last_transaction_value.text() == "-"
    assert window.general_total_debt_value.text() == "0,00 TL"
    assert window.general_total_payment_value.text() == "0,00 TL"
    assert window.general_balance_value.text() == "0,00 TL"
    assert window.general_notes_value.text() == "-"
    assert window.last_transaction_label.text() == "Son İşlem: -"


def test_general_tab_presents_overpayment_without_alacak(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Overpaid Customer")
        services.transaction.create_payment(
            customer.id,
            transaction_date=date(2026, 8, 8),
            description="Overpayment",
            amount_kurus=100_000,
        )
        customer_id = customer.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))

    assert window.general_total_payment_value.text() == "1.000,00 TL"
    assert window.general_balance_value.text() == "1.000,00 TL Fazla Ödeme"
    assert "Alacak" not in window.general_balance_value.text()


def test_real_active_summaries_populate_structured_customer_rows(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        debt_customer = services.customer.create_customer("Debt Customer")
        zero_customer = services.customer.create_customer("Zero Customer")
        overpaid_customer = services.customer.create_customer("Overpaid Customer")
        archived_customer = services.customer.create_customer("Archived Customer")
        services.transaction.create_debt(
            debt_customer.id,
            transaction_date=date(2026, 8, 7),
            transaction_time=time(9, 30),
            description="Debt",
            amount_kurus=200_000,
        )
        services.transaction.create_payment(
            overpaid_customer.id,
            transaction_date=date(2026, 8, 8),
            description="Overpayment",
            amount_kurus=100_000,
        )
        services.customer.archive_customer(archived_customer.id)
        debt_customer_id = debt_customer.id
        zero_customer_id = zero_customer.id
        overpaid_customer_id = overpaid_customer.id
        archived_customer_id = archived_customer.id

    window = window_factory()
    customer_list = window.customer_list

    assert customer_ids(customer_list) == [
        debt_customer_id,
        zero_customer_id,
        overpaid_customer_id,
    ]
    assert archived_customer_id not in customer_ids(customer_list)
    assert window.customer_count_label.text() == "Bulunan: 3 müşteri"
    assert all(
        isinstance(summary, CustomerSummary)
        for summary in window._customer_summaries_by_id.values()
    )
    assert not hasattr(window, "_session")

    expected_rows = {
        debt_customer_id: ("Debt Customer", "2.000,00 TL Borç", "Son: 07.08.2026 09:30"),
        zero_customer_id: ("Zero Customer", "0,00 TL", "Son: -"),
        overpaid_customer_id: (
            "Overpaid Customer",
            "1.000,00 TL Fazla Ödeme",
            "Son: 08.08.2026",
        ),
    }
    for customer_id, expected_texts in expected_rows.items():
        item = item_for_customer(customer_list, customer_id)
        row_widget = customer_list.itemWidget(item)
        assert row_widget is not None
        assert row_widget.findChild(QLabel, "customerRowName").text() == expected_texts[0]
        assert row_widget.findChild(QLabel, "customerRowBalance").text() == expected_texts[1]
        assert (
            row_widget.findChild(QLabel, "customerRowLastTransaction").text() == expected_texts[2]
        )

    customer_list.setCurrentItem(item_for_customer(customer_list, overpaid_customer_id))
    assert window.customer_detail_stack.currentWidget() is window.customer_detail_shell
    assert window.customer_name_label.text() == "Overpaid Customer"
    assert window.balance_value_label.text() == "1.000,00 TL Fazla Ödeme"
    assert window.last_transaction_label.text() == "Son İşlem: 08.08.2026"
    assert window.general_total_payment_value.text() == "1.000,00 TL"
    assert window.general_balance_value.text() == "1.000,00 TL Fazla Ödeme"


def test_search_and_sort_refresh_preserve_selection_by_customer_id(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        first_duplicate = services.customer.create_customer("Alpha Match")
        second_duplicate = services.customer.create_customer("Alpha Match")
        other_customer = services.customer.create_customer("Other Customer")
        first_duplicate_id = first_duplicate.id
        second_duplicate_id = second_duplicate.id
        other_customer_id = other_customer.id

    window = window_factory()
    customer_list = window.customer_list
    customer_list.setCurrentItem(item_for_customer(customer_list, second_duplicate_id))
    assert customer_list.currentItem().data(Qt.ItemDataRole.UserRole) == second_duplicate_id

    window.customer_sort_combo.setCurrentIndex(1)
    application.processEvents()
    assert customer_list.currentItem().data(Qt.ItemDataRole.UserRole) == second_duplicate_id

    window.customer_search_input.setText("  Match  ")
    QTest.qWait(250)
    assert customer_ids(customer_list) == [first_duplicate_id, second_duplicate_id]
    assert customer_list.currentItem().data(Qt.ItemDataRole.UserRole) == second_duplicate_id

    window.customer_search_input.setText("Other")
    QTest.qWait(250)
    assert customer_ids(customer_list) == [other_customer_id]
    assert customer_list.currentItem() is None
    assert window.customer_detail_stack.currentWidget() is window.no_customer_selected_state
    assert window._selected_customer_detail is None
    assert window.general_phone_value.text() == "-"
    assert window.customer_count_label.text() == "Bulunan: 1 müşteri"

    window.customer_search_input.clear()
    QTest.qWait(250)
    assert customer_ids(customer_list) == [
        first_duplicate_id,
        second_duplicate_id,
        other_customer_id,
    ]
    assert window.customer_count_label.text() == "Bulunan: 3 müşteri"


def test_selection_and_preserved_refresh_load_detail_once_each(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        first = services.customer.create_customer("First Detail")
        second = services.customer.create_customer("Second Detail")
        first_id = first.id
        second_id = second.id

    call_count = 0
    original_get = CustomerDetailService.get_customer_detail

    def counted_get(service: CustomerDetailService, customer_id: int) -> CustomerDetail:
        nonlocal call_count
        call_count += 1
        return original_get(service, customer_id)

    monkeypatch.setattr(CustomerDetailService, "get_customer_detail", counted_get)
    window = window_factory()
    assert call_count == 0

    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, first_id))
    assert call_count == 1
    assert window.customer_name_label.text() == "First Detail"

    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, second_id))
    assert call_count == 2
    assert window.customer_name_label.text() == "Second Detail"

    with application_context.services() as services:
        services.customer.update_customer(
            second_id,
            full_name="Second Detail",
            phone="Updated Phone",
        )
    window.refresh_customer_summaries()
    assert call_count == 3
    assert window._selected_customer_id == second_id
    assert window.customer_name_label.text() == "Second Detail"
    assert window.general_phone_value.text() == "Updated Phone"


def test_detail_load_failure_keeps_list_and_clears_stale_detail(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        first = services.customer.create_customer("First Customer", phone="111")
        second = services.customer.create_customer("Second Customer", phone="222")
        first_id = first.id
        second_id = second.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, first_id))
    assert window.general_phone_value.text() == "111"

    def fail_to_load(_service: CustomerDetailService, _customer_id: int) -> CustomerDetail:
        raise RuntimeError("Synthetic detail failure")

    monkeypatch.setattr(CustomerDetailService, "get_customer_detail", fail_to_load)
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, second_id))

    assert window.customer_list.count() == 2
    assert window.customer_detail_stack.currentWidget() is window.customer_detail_error_state
    assert window._selected_customer_detail is None
    assert window.customer_name_label.text() == ""
    assert window.general_phone_value.text() == "-"


def test_each_ui_refresh_calls_summary_service_once_not_once_per_row(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        for customer_number in range(10):
            services.customer.create_customer(f"Customer {customer_number:02d}")

    call_count = 0
    original_list = CustomerSummaryService.list_customer_summaries

    def counted_list(
        service: CustomerSummaryService,
        *,
        query: str = "",
        sort: CustomerSummarySort = CustomerSummarySort.HIGHEST_DEBT,
    ) -> list[CustomerSummary]:
        nonlocal call_count
        call_count += 1
        return original_list(service, query=query, sort=sort)

    monkeypatch.setattr(CustomerSummaryService, "list_customer_summaries", counted_list)
    window = window_factory()

    assert window.customer_list.count() == 10
    assert call_count == 1

    window.customer_sort_combo.setCurrentIndex(1)
    assert call_count == 2


def test_customer_load_failure_has_distinct_error_state(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_load(
        _service: CustomerSummaryService,
        *,
        query: str = "",
        sort: CustomerSummarySort = CustomerSummarySort.HIGHEST_DEBT,
    ) -> list[CustomerSummary]:
        del query, sort
        raise RuntimeError("Synthetic summary failure")

    monkeypatch.setattr(CustomerSummaryService, "list_customer_summaries", fail_to_load)
    window = window_factory()

    assert window.customer_list_stack.currentWidget() is window.customer_error_state
    assert window.customer_count_label.text() == "Bulunan: -"
    assert window.customer_detail_stack.currentWidget() is window.no_customer_selected_state


def test_database_failure_logging_does_not_serialize_private_bound_parameters(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_name = "PRIVATE CUSTOMER SENTINEL"
    private_phone = "PRIVATE PHONE SENTINEL"

    def fail_to_load(
        _service: CustomerSummaryService,
        *,
        query: str = "",
        sort: CustomerSummarySort = CustomerSummarySort.HIGHEST_DEBT,
    ) -> list[CustomerSummary]:
        del query, sort
        raise StatementError(
            "synthetic database failure",
            "INSERT INTO customers (full_name, phone) VALUES (?, ?)",
            (private_name, private_phone),
            RuntimeError("driver failure"),
        )

    monkeypatch.setattr(CustomerSummaryService, "list_customer_summaries", fail_to_load)
    with caplog.at_level(logging.ERROR, logger="hesiva.ui.main_window"):
        window = window_factory()

    assert window.customer_list_stack.currentWidget() is window.customer_error_state
    assert "StatementError" in caplog.text
    assert private_name not in caplog.text
    assert private_phone not in caplog.text
    assert "INSERT INTO" not in caplog.text
    assert "parameters" not in caplog.text
