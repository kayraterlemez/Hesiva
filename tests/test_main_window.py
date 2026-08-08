import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLineEdit,
    QListWidget,
    QSplitter,
    QStackedWidget,
    QTabWidget,
)

from hesiva.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing_application = QApplication.instance()
    if existing_application is not None:
        assert isinstance(existing_application, QApplication)
        return existing_application
    return QApplication([])


@pytest.fixture
def main_window(application: QApplication) -> Iterator[MainWindow]:
    window = MainWindow()
    window.show()
    application.processEvents()
    yield window
    window.close()
    application.processEvents()


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
