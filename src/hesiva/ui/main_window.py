import logging
from collections.abc import Iterable

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from hesiva.composition import ApplicationContext
from hesiva.read_models import CustomerSummary, CustomerSummarySort
from hesiva.ui.presentation import format_balance_kurus, format_transaction_moment
from hesiva.ui.theme import APPLICATION_STYLESHEET

LOGGER = logging.getLogger(__name__)

INITIAL_WINDOW_WIDTH = 1366
INITIAL_WINDOW_HEIGHT = 768
MINIMUM_WINDOW_WIDTH = 960
MINIMUM_WINDOW_HEIGHT = 600
CUSTOMER_PANE_INITIAL_WIDTH = 340
CUSTOMER_PANE_MINIMUM_WIDTH = 280
CUSTOMER_PANE_MAXIMUM_WIDTH = 460
SEARCH_DEBOUNCE_MILLISECONDS = 200


class EmptyState(QFrame):
    """A compact, non-error empty state used by list and detail containers."""

    def __init__(self, message: str, *, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setProperty("panel", True)

        self.message_label = QLabel(message, self)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setProperty("emptyStateTitle", True)
        self.message_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch()
        layout.addWidget(self.message_label)
        layout.addStretch()

    def set_message(self, message: str) -> None:
        self.message_label.setText(message)


class CustomerListRow(QWidget):
    """Lightweight visual row built exclusively from one plain customer summary."""

    def __init__(self, summary: CustomerSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("customerRow", True)
        self.setMinimumHeight(58)

        name_label = QLabel(summary.full_name, self)
        name_label.setObjectName("customerRowName")
        name_label.setProperty("customerRowName", True)

        balance_label = QLabel(format_balance_kurus(summary.balance_kurus), self)
        balance_label.setObjectName("customerRowBalance")
        balance_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        balance_label.setProperty("customerRowBalance", True)
        if summary.balance_kurus > 0:
            balance_label.setProperty("balanceState", "debt")
        elif summary.balance_kurus < 0:
            balance_label.setProperty("balanceState", "overpayment")
        else:
            balance_label.setProperty("balanceState", "neutral")

        last_transaction = format_transaction_moment(
            summary.last_transaction_date,
            summary.last_transaction_time,
        )
        last_transaction_label = QLabel(f"Son: {last_transaction}", self)
        last_transaction_label.setObjectName("customerRowLastTransaction")
        last_transaction_label.setProperty("muted", True)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(name_label, 1)
        top_row.addWidget(balance_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        layout.addLayout(top_row)
        layout.addWidget(last_transaction_label)

        self.setAccessibleName(
            f"{summary.full_name}, {balance_label.text()}, Son İşlem {last_transaction}"
        )


class MainWindow(QMainWindow):
    """Resizable Hesiva shell bound to plain customer-summary read models."""

    def __init__(self, application_context: ApplicationContext) -> None:
        super().__init__()
        self._application_context = application_context
        self._customer_summaries_by_id: dict[int, CustomerSummary] = {}
        self._selected_customer_id: int | None = None
        self.setWindowTitle("Hesiva")
        self.setObjectName("mainWindow")
        self.setMinimumSize(MINIMUM_WINDOW_WIDTH, MINIMUM_WINDOW_HEIGHT)
        self.resize(INITIAL_WINDOW_WIDTH, INITIAL_WINDOW_HEIGHT)
        self.setStyleSheet(APPLICATION_STYLESHEET)

        self._create_menu_bar()
        self.setCentralWidget(self._create_central_widget())
        self.statusBar().showMessage("Hazır")
        self.statusBar().setSizeGripEnabled(True)

        QWidget.setTabOrder(self.customer_search_input, self.customer_sort_combo)
        QWidget.setTabOrder(self.customer_sort_combo, self.customer_list)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MILLISECONDS)
        self._search_timer.timeout.connect(self.refresh_customer_summaries)
        self.customer_search_input.textChanged.connect(self._schedule_customer_search)
        self.customer_sort_combo.currentIndexChanged.connect(self._customer_sort_changed)
        self.customer_list.currentItemChanged.connect(self._customer_selection_changed)

        self.refresh_customer_summaries()

    def _create_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("Dosya")
        self._add_disabled_actions(file_menu, ("Yedekleme ve Veri Güvenliği",))
        file_menu.addSeparator()
        exit_action = QAction("Çıkış", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        operations_menu = self.menuBar().addMenu("İşlemler")
        self._add_disabled_actions(
            operations_menu,
            ("Yeni Müşteri", "Yeni İşlem", "Ödeme Al"),
        )

        report_menu = self.menuBar().addMenu("Rapor")
        self._add_disabled_actions(
            report_menu,
            ("Hesap Özeti", "Aylık Özet", "Yıllık Özet"),
        )

        settings_menu = self.menuBar().addMenu("Ayarlar")
        self._add_disabled_actions(settings_menu, ("Ayarlar",))

        help_menu = self.menuBar().addMenu("Yardım")
        self._add_disabled_actions(help_menu, ("Hakkında",))

    def _add_disabled_actions(self, menu: QMenu, labels: Iterable[str]) -> None:
        for label in labels:
            action = menu.addAction(label)
            action.setEnabled(False)

    def _create_central_widget(self) -> QWidget:
        central_widget = QWidget(self)
        central_widget.setObjectName("mainContent")
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal, central_widget)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(1)

        customer_pane = self._create_customer_navigation_pane()
        detail_pane = self._create_customer_detail_pane()
        self.main_splitter.addWidget(customer_pane)
        self.main_splitter.addWidget(detail_pane)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes(
            [CUSTOMER_PANE_INITIAL_WIDTH, INITIAL_WINDOW_WIDTH - CUSTOMER_PANE_INITIAL_WIDTH]
        )

        layout.addWidget(self.main_splitter)
        return central_widget

    def _create_customer_navigation_pane(self) -> QWidget:
        pane = QFrame(self)
        pane.setObjectName("customerNavigationPane")
        pane.setProperty("panel", True)
        pane.setMinimumWidth(CUSTOMER_PANE_MINIMUM_WIDTH)
        pane.setMaximumWidth(CUSTOMER_PANE_MAXIMUM_WIDTH)
        pane.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(pane)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(9)

        search_label = QLabel("Müşteri", pane)
        search_label.setProperty("sectionHeading", True)
        layout.addWidget(search_label)

        self.customer_search_input = QLineEdit(pane)
        self.customer_search_input.setObjectName("customerSearchInput")
        self.customer_search_input.setAccessibleName("Müşteri ara")
        self.customer_search_input.setPlaceholderText("Müşteri Ara...")
        self.customer_search_input.setClearButtonEnabled(True)
        layout.addWidget(self.customer_search_input)

        sort_row = QHBoxLayout()
        sort_row.setSpacing(8)
        sort_label = QLabel("Sıralama:", pane)
        sort_row.addWidget(sort_label)

        self.customer_sort_combo = QComboBox(pane)
        self.customer_sort_combo.setObjectName("customerSortCombo")
        self.customer_sort_combo.setAccessibleName("Müşteri sıralaması")
        for label, sort in (
            ("En Yüksek Borç", CustomerSummarySort.HIGHEST_DEBT),
            ("Ada Göre", CustomerSummarySort.NAME),
            ("Son İşlem", CustomerSummarySort.LAST_TRANSACTION),
            ("Kayıt Tarihi", CustomerSummarySort.REGISTERED_ON),
        ):
            self.customer_sort_combo.addItem(label, sort.value)
        self.customer_sort_combo.setToolTip("Müşteri listesinin sıralama ölçütünü belirler.")
        sort_label.setBuddy(self.customer_sort_combo)
        sort_row.addWidget(self.customer_sort_combo, 1)
        layout.addLayout(sort_row)

        list_header = QHBoxLayout()
        customer_heading = QLabel("Müşteri", pane)
        customer_heading.setProperty("sectionHeading", True)
        balance_heading = QLabel("Bakiye", pane)
        balance_heading.setProperty("sectionHeading", True)
        balance_heading.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        list_header.addWidget(customer_heading)
        list_header.addStretch()
        list_header.addWidget(balance_heading)
        layout.addLayout(list_header)

        self.customer_list_stack = QStackedWidget(pane)
        self.customer_list_stack.setObjectName("customerListStack")
        self.customer_empty_state = EmptyState(
            "Henüz müşteri kaydı bulunmuyor.",
            object_name="customerListEmptyState",
            parent=self.customer_list_stack,
        )
        self.customer_list = QListWidget(self.customer_list_stack)
        self.customer_list.setObjectName("customerList")
        self.customer_list.setAccessibleName("Müşteri listesi")
        self.customer_list_stack.addWidget(self.customer_empty_state)
        self.customer_list_stack.addWidget(self.customer_list)
        self.customer_error_state = EmptyState(
            "Müşteriler yüklenemedi. Lütfen yeniden deneyin.",
            object_name="customerListErrorState",
            parent=self.customer_list_stack,
        )
        self.customer_list_stack.addWidget(self.customer_error_state)
        self.customer_list_stack.setCurrentWidget(self.customer_empty_state)
        layout.addWidget(self.customer_list_stack, 1)

        footer = QHBoxLayout()
        self.customer_count_label = QLabel("Bulunan: 0 müşteri", pane)
        self.customer_count_label.setObjectName("customerCountLabel")
        self.customer_count_label.setProperty("muted", True)
        footer.addWidget(self.customer_count_label)
        footer.addStretch()

        self.new_customer_button = QPushButton("+ Yeni Müşteri", pane)
        self.new_customer_button.setObjectName("newCustomerButton")
        self.new_customer_button.setProperty("primary", True)
        self.new_customer_button.setEnabled(False)
        self.new_customer_button.setToolTip("Müşteri oluşturma iş akışı henüz bağlı değil.")
        footer.addWidget(self.new_customer_button)
        layout.addLayout(footer)
        return pane

    def _create_customer_detail_pane(self) -> QWidget:
        pane = QFrame(self)
        pane.setObjectName("customerDetailPane")
        pane.setProperty("panel", True)
        pane.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.customer_detail_stack = QStackedWidget(pane)
        self.customer_detail_stack.setObjectName("customerDetailStack")
        self.no_customer_selected_state = EmptyState(
            "Detayları görüntülemek için bir müşteri seçin.",
            object_name="noCustomerSelectedState",
            parent=self.customer_detail_stack,
        )
        self.customer_detail_shell = self._create_selected_customer_shell()
        self.customer_detail_stack.addWidget(self.no_customer_selected_state)
        self.customer_detail_stack.addWidget(self.customer_detail_shell)
        self.customer_detail_stack.setCurrentWidget(self.no_customer_selected_state)
        layout.addWidget(self.customer_detail_stack)
        return pane

    def _create_selected_customer_shell(self) -> QWidget:
        shell = QWidget(self)
        shell.setObjectName("customerDetailShell")
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame(shell)
        header.setObjectName("customerHeader")
        header.setProperty("panel", True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 18)
        header_layout.setSpacing(20)

        identity_layout = QVBoxLayout()
        identity_layout.setSpacing(7)
        self.customer_name_label = QLabel("", header)
        self.customer_name_label.setObjectName("customerNameLabel")
        self.customer_name_label.setProperty("customerTitle", True)
        identity_layout.addWidget(self.customer_name_label)

        metadata_layout = QHBoxLayout()
        metadata_layout.setSpacing(24)
        self.customer_phone_label = QLabel("Telefon:", header)
        self.customer_phone_label.setObjectName("customerPhoneLabel")
        self.customer_phone_label.setProperty("muted", True)
        self.customer_phone_label.hide()
        self.last_transaction_label = QLabel("Son İşlem:", header)
        self.last_transaction_label.setObjectName("lastTransactionLabel")
        self.last_transaction_label.setProperty("muted", True)
        metadata_layout.addWidget(self.customer_phone_label)
        metadata_layout.addWidget(self.last_transaction_label)
        metadata_layout.addStretch()
        identity_layout.addLayout(metadata_layout)
        header_layout.addLayout(identity_layout, 1)

        balance_panel = QFrame(header)
        balance_panel.setObjectName("balancePanel")
        balance_layout = QVBoxLayout(balance_panel)
        balance_layout.setContentsMargins(18, 10, 18, 10)
        balance_layout.setSpacing(2)
        balance_caption = QLabel("Güncel Bakiye", balance_panel)
        balance_caption.setAlignment(Qt.AlignmentFlag.AlignRight)
        balance_caption.setProperty("balanceCaption", True)
        self.balance_value_label = QLabel("", balance_panel)
        self.balance_value_label.setObjectName("balanceValueLabel")
        self.balance_value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.balance_value_label.setProperty("balanceValue", True)
        balance_layout.addWidget(balance_caption)
        balance_layout.addWidget(self.balance_value_label)
        header_layout.addWidget(balance_panel)
        layout.addWidget(header)

        self.customer_tabs = QTabWidget(shell)
        self.customer_tabs.setObjectName("customerTabs")
        self.customer_tabs.setAccessibleName("Müşteri detay sekmeleri")
        for object_name, label in (
            ("generalTab", "Genel"),
            ("animalsTab", "Hayvanlar"),
            ("accountHistoryTab", "Hesap Hareketleri"),
            ("remindersTab", "Hatırlatmalar"),
        ):
            tab = QWidget(self.customer_tabs)
            tab.setObjectName(object_name)
            tab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.customer_tabs.addTab(tab, label)
        layout.addWidget(self.customer_tabs, 1)
        return shell

    def refresh_customer_summaries(self) -> None:
        """Reload active summaries using the current search and sort controls."""
        selected_customer_id = self._selected_customer_id
        sort = CustomerSummarySort(self.customer_sort_combo.currentData())
        query = self.customer_search_input.text()

        try:
            with self._application_context.services() as services:
                summaries = services.customer_summary.list_customer_summaries(
                    query=query,
                    sort=sort,
                )
        except Exception:
            LOGGER.exception("Customer summaries could not be loaded")
            self._show_customer_load_error()
            return

        self._customer_summaries_by_id = {summary.customer_id: summary for summary in summaries}
        blocker = QSignalBlocker(self.customer_list)
        self.customer_list.clear()
        selected_row: int | None = None
        for row_index, summary in enumerate(summaries):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, summary.customer_id)
            row_widget = CustomerListRow(summary, self.customer_list)
            item.setSizeHint(row_widget.sizeHint())
            self.customer_list.addItem(item)
            self.customer_list.setItemWidget(item, row_widget)
            if summary.customer_id == selected_customer_id:
                selected_row = row_index

        if selected_row is not None:
            self.customer_list.setCurrentRow(selected_row)
        del blocker

        self.customer_count_label.setText(f"Bulunan: {len(summaries)} müşteri")
        if summaries:
            self.customer_list_stack.setCurrentWidget(self.customer_list)
        else:
            message = (
                "Arama sonucu bulunamadı." if query.strip() else "Henüz müşteri kaydı bulunmuyor."
            )
            self.customer_empty_state.set_message(message)
            self.customer_list_stack.setCurrentWidget(self.customer_empty_state)

        if selected_row is not None:
            self._show_selected_customer(self._customer_summaries_by_id[selected_customer_id])
        else:
            self._show_no_customer_selected()

    def _schedule_customer_search(self, _text: str) -> None:
        self._search_timer.start()

    def _customer_sort_changed(self, _index: int) -> None:
        self.refresh_customer_summaries()

    def _customer_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self._show_no_customer_selected()
            return

        customer_id = current.data(Qt.ItemDataRole.UserRole)
        summary = self._customer_summaries_by_id.get(customer_id)
        if summary is None:
            self._show_no_customer_selected()
            return
        self._show_selected_customer(summary)

    def _show_selected_customer(self, summary: CustomerSummary) -> None:
        self._selected_customer_id = summary.customer_id
        self.customer_name_label.setText(summary.full_name)
        self.balance_value_label.setText(format_balance_kurus(summary.balance_kurus))
        last_transaction = format_transaction_moment(
            summary.last_transaction_date,
            summary.last_transaction_time,
        )
        self.last_transaction_label.setText(f"Son İşlem: {last_transaction}")
        self.customer_detail_stack.setCurrentWidget(self.customer_detail_shell)

    def _show_no_customer_selected(self) -> None:
        self._selected_customer_id = None
        self.customer_name_label.clear()
        self.balance_value_label.clear()
        self.last_transaction_label.setText("Son İşlem:")
        self.customer_detail_stack.setCurrentWidget(self.no_customer_selected_state)

    def _show_customer_load_error(self) -> None:
        self._customer_summaries_by_id = {}
        self.customer_list.clear()
        self.customer_count_label.setText("Bulunan: -")
        self.customer_list_stack.setCurrentWidget(self.customer_error_state)
        self._show_no_customer_selected()
