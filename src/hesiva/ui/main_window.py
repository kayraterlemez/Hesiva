from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
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

from hesiva.ui.theme import APPLICATION_STYLESHEET

INITIAL_WINDOW_WIDTH = 1366
INITIAL_WINDOW_HEIGHT = 768
MINIMUM_WINDOW_WIDTH = 960
MINIMUM_WINDOW_HEIGHT = 600
CUSTOMER_PANE_INITIAL_WIDTH = 340
CUSTOMER_PANE_MINIMUM_WIDTH = 280
CUSTOMER_PANE_MAXIMUM_WIDTH = 460


class EmptyState(QFrame):
    """A compact, non-error empty state used by list and detail containers."""

    def __init__(self, message: str, *, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setProperty("panel", True)

        message_label = QLabel(message, self)
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setProperty("emptyStateTitle", True)
        message_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch()
        layout.addWidget(message_label)
        layout.addStretch()


class MainWindow(QMainWindow):
    """Resizable, data-independent shell for the Hesiva main window."""

    def __init__(self) -> None:
        super().__init__()
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
        self.customer_sort_combo.addItems(
            ("En Yüksek Borç", "Ada Göre", "Son İşlem", "Kayıt Tarihi")
        )
        self.customer_sort_combo.setToolTip(
            "Müşteri listesi bağlandığında sıralama ölçütünü belirler."
        )
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
        self.customer_list_stack.setCurrentWidget(self.customer_empty_state)
        layout.addWidget(self.customer_list_stack, 1)

        footer = QHBoxLayout()
        self.customer_count_label = QLabel("Bulunan: 0 kayıt", pane)
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
