import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QSignalBlocker, QTime, Qt, QTimer
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from hesiva.composition import ApplicationContext
from hesiva.read_models import (
    AccountHistoryRow,
    AnimalSummary,
    ArchivedCustomer,
    CustomerDetail,
    CustomerSummary,
    CustomerSummarySort,
    LegacyImportResult,
    ReminderSummary,
    StartupReminderSummary,
)
from hesiva.services import (
    BackupError,
    BackupPathError,
    BackupValidationError,
    RestoreRecoveryRequiredError,
    RestoreRollbackError,
    ServiceError,
    ValidationError,
)
from hesiva.ui import (
    animal_dialogs,
    auth_dialogs,
    backup_dialogs,
    customer_dialogs,
    reminder_dialogs,
    settings_dialogs,
)
from hesiva.ui.animal_dialogs import (
    AnimalFormDialog,
    AnimalFormValues,
    ArchivedAnimalsDialog,
)
from hesiva.ui.customer_dialogs import (
    ArchivedCustomersDialog,
    CustomerFormDialog,
    CustomerFormValues,
)
from hesiva.ui.financial_dialogs import (
    DebtTransactionDialog,
    PaymentDialog,
    VoidTransactionDialog,
)
from hesiva.ui.legacy_import_dialog import LegacyImportDialog
from hesiva.ui.presentation import (
    ReminderPresentationState,
    classify_reminder,
    count_active_reminders_today,
    format_animal_display,
    format_animal_identity,
    format_balance_kurus,
    format_date,
    format_money_kurus,
    format_reminder_status,
    format_transaction_moment,
)
from hesiva.ui.reminder_dialogs import ReminderFormDialog, ReminderFormValues
from hesiva.ui.report_dialogs import (
    CustomerStatementDialog,
    MonthlySummaryDialog,
    YearlySummaryDialog,
)
from hesiva.ui.theme import APPLICATION_STYLESHEET
from hesiva.version import get_application_version

LOGGER = logging.getLogger(__name__)

INITIAL_WINDOW_WIDTH = 1366
INITIAL_WINDOW_HEIGHT = 768
MINIMUM_WINDOW_WIDTH = 960
MINIMUM_WINDOW_HEIGHT = 600
CUSTOMER_PANE_INITIAL_WIDTH = 340
CUSTOMER_PANE_MINIMUM_WIDTH = 280
CUSTOMER_PANE_MAXIMUM_WIDTH = 460
SEARCH_DEBOUNCE_MILLISECONDS = 200


def _log_failure(message: str, error: BaseException, *safe_arguments: object) -> None:
    """Log the operation and exception type without serializing user data or SQL."""
    LOGGER.error(f"{message}: %s", *safe_arguments, type(error).__name__)


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

    def __init__(
        self,
        application_context: ApplicationContext,
        *,
        date_provider: Callable[[], date] = date.today,
        datetime_provider: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._application_context = application_context
        self._date_provider = date_provider
        self._datetime_provider = datetime_provider or (lambda: datetime.now().astimezone())
        self._startup_actions_run = False
        self._customer_summaries_by_id: dict[int, CustomerSummary] = {}
        self._selected_customer_id: int | None = None
        self._selected_customer_detail: CustomerDetail | None = None
        self._account_history_by_id: dict[int, AccountHistoryRow] = {}
        self._animal_summaries_by_id: dict[int, AnimalSummary] = {}
        self._reminder_summaries_by_id: dict[int, ReminderSummary] = {}
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

        self._reminder_rollover_timer = QTimer(self)
        self._reminder_rollover_timer.setSingleShot(True)
        self._reminder_rollover_timer.timeout.connect(self._refresh_reminders_after_date_rollover)
        self._schedule_reminder_rollover()

        self.refresh_customer_summaries()

    def _create_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("Dosya")
        self.backup_action = QAction("Yedekleme ve Veri Güvenliği", self)
        self.backup_action.triggered.connect(self._open_backup_dialog)
        file_menu.addAction(self.backup_action)
        self.legacy_import_action = QAction("Eski Verileri İçe Aktar...", self)
        self.legacy_import_action.triggered.connect(self._open_legacy_import_dialog)
        file_menu.addAction(self.legacy_import_action)
        file_menu.addSeparator()
        exit_action = QAction("Çıkış", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        operations_menu = self.menuBar().addMenu("İşlemler")
        self.new_customer_action = QAction("Yeni Müşteri", self)
        self.new_customer_action.triggered.connect(self._open_new_customer_dialog)
        operations_menu.addAction(self.new_customer_action)
        self.archived_customers_action = QAction("Arşivlenmiş Müşteriler", self)
        self.archived_customers_action.triggered.connect(self._open_archived_customers_dialog)
        operations_menu.addAction(self.archived_customers_action)
        operations_menu.addSeparator()
        self.new_transaction_action = QAction("Yeni İşlem", self)
        self.new_transaction_action.setEnabled(False)
        self.new_transaction_action.triggered.connect(self._open_debt_transaction_dialog)
        operations_menu.addAction(self.new_transaction_action)
        self.receive_payment_action = QAction("Ödeme Al", self)
        self.receive_payment_action.setEnabled(False)
        self.receive_payment_action.triggered.connect(self._open_payment_dialog)
        operations_menu.addAction(self.receive_payment_action)

        report_menu = self.menuBar().addMenu("Rapor")
        self.customer_statement_action = QAction("Hesap Özeti", self)
        self.customer_statement_action.setEnabled(False)
        self.customer_statement_action.triggered.connect(self._open_customer_statement)
        report_menu.addAction(self.customer_statement_action)
        self.monthly_summary_action = QAction("Aylık Özet", self)
        self.monthly_summary_action.triggered.connect(self._open_monthly_summary)
        report_menu.addAction(self.monthly_summary_action)
        self.yearly_summary_action = QAction("Yıllık Özet", self)
        self.yearly_summary_action.triggered.connect(self._open_yearly_summary)
        report_menu.addAction(self.yearly_summary_action)

        settings_menu = self.menuBar().addMenu("Ayarlar")
        self.settings_action = QAction("Ayarlar...", self)
        self.settings_action.triggered.connect(self._open_settings_dialog)
        settings_menu.addAction(self.settings_action)

        help_menu = self.menuBar().addMenu("Yardım")
        self.about_action = QAction("Hakkında", self)
        self.about_action.triggered.connect(self._open_about_dialog)
        help_menu.addAction(self.about_action)

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
        self.new_customer_button.clicked.connect(self._open_new_customer_dialog)
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
        self.customer_detail_error_state = EmptyState(
            "Müşteri ayrıntıları yüklenemedi. Lütfen yeniden deneyin.",
            object_name="customerDetailErrorState",
            parent=self.customer_detail_stack,
        )
        self.customer_detail_stack.addWidget(self.no_customer_selected_state)
        self.customer_detail_stack.addWidget(self.customer_detail_shell)
        self.customer_detail_stack.addWidget(self.customer_detail_error_state)
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
        self.customer_tabs.addTab(self._create_general_tab(), "Genel")
        self.customer_tabs.addTab(self._create_animals_tab(), "Hayvanlar")
        self.customer_tabs.addTab(self._create_account_history_tab(), "Hesap Hareketleri")
        self.reminders_tab = self._create_reminders_tab()
        self.customer_tabs.addTab(self.reminders_tab, "Hatırlatmalar")
        layout.addWidget(self.customer_tabs, 1)
        return shell

    def _create_general_tab(self) -> QWidget:
        tab = QWidget(self.customer_tabs)
        tab.setObjectName("generalTab")
        tab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        information_panel = QFrame(tab)
        information_panel.setObjectName("generalInformationPanel")
        information_panel.setProperty("detailPanel", True)
        information_layout = QVBoxLayout(information_panel)
        information_layout.setContentsMargins(18, 16, 18, 16)
        information_layout.setSpacing(10)

        contact_heading = QLabel("İletişim Bilgileri", information_panel)
        contact_heading.setProperty("sectionHeading", True)
        information_layout.addWidget(contact_heading)
        contact_grid = QGridLayout()
        contact_grid.setHorizontalSpacing(16)
        contact_grid.setVerticalSpacing(8)
        self.general_phone_value = self._create_detail_value_label(
            information_panel,
            "generalPhoneValue",
        )
        self.general_address_value = self._create_detail_value_label(
            information_panel,
            "generalAddressValue",
            word_wrap=True,
        )
        self._add_detail_row(contact_grid, 0, "Telefon", self.general_phone_value)
        self._add_detail_row(contact_grid, 1, "Adres", self.general_address_value)
        information_layout.addLayout(contact_grid)

        customer_heading = QLabel("Müşteri Bilgileri", information_panel)
        customer_heading.setProperty("sectionHeading", True)
        information_layout.addWidget(customer_heading)
        customer_grid = QGridLayout()
        customer_grid.setHorizontalSpacing(16)
        customer_grid.setVerticalSpacing(8)
        self.general_registered_on_value = self._create_detail_value_label(
            information_panel,
            "generalRegisteredOnValue",
        )
        self.general_last_transaction_value = self._create_detail_value_label(
            information_panel,
            "generalLastTransactionValue",
        )
        self._add_detail_row(
            customer_grid,
            0,
            "Kayıt Tarihi",
            self.general_registered_on_value,
        )
        self._add_detail_row(
            customer_grid,
            1,
            "Son İşlem",
            self.general_last_transaction_value,
        )
        information_layout.addLayout(customer_grid)

        account_heading = QLabel("Hesap Özeti", information_panel)
        account_heading.setProperty("sectionHeading", True)
        information_layout.addWidget(account_heading)
        account_grid = QGridLayout()
        account_grid.setHorizontalSpacing(16)
        account_grid.setVerticalSpacing(8)
        self.general_total_debt_value = self._create_detail_value_label(
            information_panel,
            "generalTotalDebtValue",
        )
        self.general_total_debt_value.setProperty("financialValue", True)
        self.general_total_debt_value.setProperty("balanceState", "debt")
        self.general_total_payment_value = self._create_detail_value_label(
            information_panel,
            "generalTotalPaymentValue",
        )
        self.general_total_payment_value.setProperty("financialValue", True)
        self.general_total_payment_value.setProperty("balanceState", "overpayment")
        self.general_balance_value = self._create_detail_value_label(
            information_panel,
            "generalBalanceValue",
        )
        self.general_balance_value.setProperty("financialValue", True)
        self._add_detail_row(account_grid, 0, "Toplam Borç", self.general_total_debt_value)
        self._add_detail_row(
            account_grid,
            1,
            "Toplam Ödeme",
            self.general_total_payment_value,
        )
        self._add_detail_row(account_grid, 2, "Güncel Bakiye", self.general_balance_value)
        information_layout.addLayout(account_grid)
        information_layout.addStretch()
        content_layout.addWidget(information_panel, 3)

        notes_panel = QFrame(tab)
        notes_panel.setObjectName("generalNotesPanel")
        notes_panel.setProperty("detailPanel", True)
        notes_layout = QVBoxLayout(notes_panel)
        notes_layout.setContentsMargins(18, 16, 18, 16)
        notes_layout.setSpacing(10)
        notes_heading = QLabel("Notlar", notes_panel)
        notes_heading.setProperty("sectionHeading", True)
        notes_layout.addWidget(notes_heading)
        self.general_notes_value = self._create_detail_value_label(
            notes_panel,
            "generalNotesValue",
            word_wrap=True,
        )
        self.general_notes_value.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        notes_layout.addWidget(self.general_notes_value, 1)
        content_layout.addWidget(notes_panel, 2)
        layout.addLayout(content_layout, 1)

        actions_layout = QHBoxLayout()
        self.archive_customer_button = QPushButton("Müşteriyi Arşivle", tab)
        self.archive_customer_button.setObjectName("archiveCustomerButton")
        self.archive_customer_button.setProperty("archiveAction", True)
        self.archive_customer_button.setEnabled(False)
        self.archive_customer_button.clicked.connect(self._archive_selected_customer)
        actions_layout.addWidget(self.archive_customer_button)
        actions_layout.addStretch()
        self.edit_customer_button = QPushButton("Müşteriyi Düzenle", tab)
        self.edit_customer_button.setObjectName("editCustomerButton")
        self.edit_customer_button.setEnabled(False)
        self.edit_customer_button.clicked.connect(self._open_edit_customer_dialog)
        actions_layout.addWidget(self.edit_customer_button)
        layout.addLayout(actions_layout)
        return tab

    def _create_animals_tab(self) -> QWidget:
        tab = QWidget(self.customer_tabs)
        tab.setObjectName("animalsTab")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        actions = QHBoxLayout()
        self.add_animal_button = QPushButton("+ Hayvan Ekle", tab)
        self.add_animal_button.setObjectName("addAnimalButton")
        self.add_animal_button.setProperty("primary", True)
        self.add_animal_button.setEnabled(False)
        self.add_animal_button.clicked.connect(self._open_add_animal_dialog)
        actions.addWidget(self.add_animal_button)
        self.archived_animals_button = QPushButton("Arşivlenmiş Hayvanlar", tab)
        self.archived_animals_button.setObjectName("archivedAnimalsButton")
        self.archived_animals_button.setEnabled(False)
        self.archived_animals_button.clicked.connect(self._open_archived_animals_dialog)
        actions.addWidget(self.archived_animals_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.animal_list_stack = QStackedWidget(tab)
        self.animal_empty_state = EmptyState(
            "Bu müşteriye kayıtlı hayvan bulunmuyor.",
            object_name="animalListEmptyState",
            parent=self.animal_list_stack,
        )
        self.animal_error_state = EmptyState(
            "Hayvanlar yüklenemedi. Lütfen yeniden deneyin.",
            object_name="animalListErrorState",
            parent=self.animal_list_stack,
        )
        self.animal_table = QTableWidget(0, 4, self.animal_list_stack)
        self.animal_table.setObjectName("animalTable")
        self.animal_table.setHorizontalHeaderLabels(("Küpe No", "Ad", "Tür", "Not"))
        self.animal_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.animal_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.animal_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.animal_table.setAlternatingRowColors(True)
        self.animal_table.verticalHeader().hide()
        animal_header = self.animal_table.horizontalHeader()
        animal_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        animal_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.animal_table.itemSelectionChanged.connect(self._animal_selection_changed)
        self.animal_list_stack.addWidget(self.animal_empty_state)
        self.animal_list_stack.addWidget(self.animal_table)
        self.animal_list_stack.addWidget(self.animal_error_state)
        self.animal_list_stack.setCurrentWidget(self.animal_empty_state)
        layout.addWidget(self.animal_list_stack, 1)

        footer = QHBoxLayout()
        self.animal_count_label = QLabel("Toplam Kayıt: 0 hayvan", tab)
        self.animal_count_label.setObjectName("animalCountLabel")
        self.animal_count_label.setProperty("muted", True)
        footer.addWidget(self.animal_count_label)
        footer.addStretch()
        self.edit_animal_button = QPushButton("Düzenle", tab)
        self.edit_animal_button.setObjectName("editAnimalButton")
        self.edit_animal_button.setEnabled(False)
        self.edit_animal_button.clicked.connect(self._open_edit_animal_dialog)
        footer.addWidget(self.edit_animal_button)
        self.archive_animal_button = QPushButton("Arşivle", tab)
        self.archive_animal_button.setObjectName("archiveAnimalButton")
        self.archive_animal_button.setProperty("archiveAction", True)
        self.archive_animal_button.setEnabled(False)
        self.archive_animal_button.clicked.connect(self._archive_selected_animal)
        footer.addWidget(self.archive_animal_button)
        layout.addLayout(footer)
        return tab

    def _create_account_history_tab(self) -> QWidget:
        tab = QWidget(self.customer_tabs)
        tab.setObjectName("accountHistoryTab")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        actions = QHBoxLayout()
        self.new_transaction_button = QPushButton("Yeni İşlem", tab)
        self.new_transaction_button.setObjectName("newTransactionButton")
        self.new_transaction_button.setProperty("primary", True)
        self.new_transaction_button.setEnabled(False)
        self.new_transaction_button.clicked.connect(self._open_debt_transaction_dialog)
        actions.addWidget(self.new_transaction_button)
        self.receive_payment_button = QPushButton("Ödeme Al", tab)
        self.receive_payment_button.setObjectName("receivePaymentButton")
        self.receive_payment_button.setProperty("primary", True)
        self.receive_payment_button.setEnabled(False)
        self.receive_payment_button.clicked.connect(self._open_payment_dialog)
        actions.addWidget(self.receive_payment_button)
        actions.addStretch()
        self.account_history_print_button = QPushButton("Yazdır", tab)
        self.account_history_print_button.setObjectName("accountHistoryPrintButton")
        self.account_history_print_button.setEnabled(False)
        self.account_history_print_button.clicked.connect(self._open_customer_statement)
        actions.addWidget(self.account_history_print_button)
        layout.addLayout(actions)

        self.account_history_stack = QStackedWidget(tab)
        self.account_history_empty_state = EmptyState(
            "Bu müşterinin hesap hareketi bulunmuyor.",
            object_name="accountHistoryEmptyState",
            parent=self.account_history_stack,
        )
        self.account_history_error_state = EmptyState(
            "Hesap hareketleri yüklenemedi. Lütfen yeniden deneyin.",
            object_name="accountHistoryErrorState",
            parent=self.account_history_stack,
        )
        self.account_history_table = QTableWidget(0, 7, self.account_history_stack)
        self.account_history_table.setObjectName("accountHistoryTable")
        self.account_history_table.setHorizontalHeaderLabels(
            ("Tarih", "Saat", "Açıklama", "Hayvan", "Borç", "Ödeme", "Bakiye")
        )
        self.account_history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.account_history_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.account_history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.account_history_table.setAlternatingRowColors(True)
        self.account_history_table.verticalHeader().hide()
        header = self.account_history_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.account_history_table.itemSelectionChanged.connect(
            self._account_history_selection_changed
        )
        self.account_history_stack.addWidget(self.account_history_empty_state)
        self.account_history_stack.addWidget(self.account_history_table)
        self.account_history_stack.addWidget(self.account_history_error_state)
        self.account_history_stack.setCurrentWidget(self.account_history_empty_state)
        layout.addWidget(self.account_history_stack, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        self.void_transaction_button = QPushButton("İşlemi İptal Et", tab)
        self.void_transaction_button.setObjectName("voidTransactionButton")
        self.void_transaction_button.setProperty("destructive", True)
        self.void_transaction_button.setEnabled(False)
        self.void_transaction_button.clicked.connect(self._open_void_transaction_dialog)
        footer.addWidget(self.void_transaction_button)
        layout.addLayout(footer)
        return tab

    def _create_reminders_tab(self) -> QWidget:
        tab = QWidget(self.customer_tabs)
        tab.setObjectName("remindersTab")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        actions = QHBoxLayout()
        self.add_reminder_button = QPushButton("+ Hatırlatma Ekle", tab)
        self.add_reminder_button.setObjectName("addReminderButton")
        self.add_reminder_button.setProperty("primary", True)
        self.add_reminder_button.setEnabled(False)
        self.add_reminder_button.clicked.connect(self._open_add_reminder_dialog)
        actions.addWidget(self.add_reminder_button)
        self.complete_reminder_button = QPushButton("Tamamlandı", tab)
        self.complete_reminder_button.setObjectName("completeReminderButton")
        self.complete_reminder_button.setEnabled(False)
        self.complete_reminder_button.clicked.connect(self._complete_selected_reminder)
        actions.addWidget(self.complete_reminder_button)
        self.edit_reminder_button = QPushButton("Düzenle", tab)
        self.edit_reminder_button.setObjectName("editReminderButton")
        self.edit_reminder_button.setEnabled(False)
        self.edit_reminder_button.clicked.connect(self._open_edit_reminder_dialog)
        actions.addWidget(self.edit_reminder_button)
        self.cancel_reminder_button = QPushButton("İptal Et", tab)
        self.cancel_reminder_button.setObjectName("cancelReminderButton")
        self.cancel_reminder_button.setProperty("destructive", True)
        self.cancel_reminder_button.setEnabled(False)
        self.cancel_reminder_button.clicked.connect(self._cancel_selected_reminder)
        actions.addWidget(self.cancel_reminder_button)
        actions.addStretch()
        self.show_inactive_reminders_checkbox = QCheckBox("Tamamlanmışları Göster", tab)
        self.show_inactive_reminders_checkbox.setObjectName("showInactiveRemindersCheckbox")
        self.show_inactive_reminders_checkbox.setToolTip(
            "Tamamlanan ve iptal edilen hatırlatmaları da gösterir."
        )
        self.show_inactive_reminders_checkbox.setEnabled(False)
        self.show_inactive_reminders_checkbox.toggled.connect(self._reminder_history_toggled)
        actions.addWidget(self.show_inactive_reminders_checkbox)
        layout.addLayout(actions)

        self.reminder_list_stack = QStackedWidget(tab)
        self.reminder_empty_state = EmptyState(
            "Bu müşteriye ait aktif hatırlatma bulunmuyor.",
            object_name="reminderListEmptyState",
            parent=self.reminder_list_stack,
        )
        self.reminder_error_state = EmptyState(
            "Hatırlatmalar yüklenemedi. Lütfen yeniden deneyin.",
            object_name="reminderListErrorState",
            parent=self.reminder_list_stack,
        )
        self.reminder_table = QTableWidget(0, 3, self.reminder_list_stack)
        self.reminder_table.setObjectName("reminderTable")
        self.reminder_table.setHorizontalHeaderLabels(("Tarih", "Hatırlatma Notu", "Durum"))
        self.reminder_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.reminder_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.reminder_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.reminder_table.setAlternatingRowColors(True)
        self.reminder_table.verticalHeader().hide()
        reminder_header = self.reminder_table.horizontalHeader()
        reminder_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        reminder_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.reminder_table.itemSelectionChanged.connect(self._reminder_selection_changed)
        self.reminder_list_stack.addWidget(self.reminder_empty_state)
        self.reminder_list_stack.addWidget(self.reminder_table)
        self.reminder_list_stack.addWidget(self.reminder_error_state)
        self.reminder_list_stack.setCurrentWidget(self.reminder_empty_state)
        layout.addWidget(self.reminder_list_stack, 1)

        footer = QHBoxLayout()
        self.reminder_count_label = QLabel("Toplam Hatırlatma: 0", tab)
        self.reminder_count_label.setObjectName("reminderCountLabel")
        self.reminder_count_label.setProperty("muted", True)
        footer.addWidget(self.reminder_count_label)
        footer.addStretch()
        self.today_reminder_count_label = QLabel("Bugün Yapılacak: 0 Hatırlatma", tab)
        self.today_reminder_count_label.setObjectName("todayReminderCountLabel")
        self.today_reminder_count_label.setProperty("sectionHeading", True)
        footer.addWidget(self.today_reminder_count_label)
        layout.addLayout(footer)
        return tab

    @staticmethod
    def _create_detail_value_label(
        parent: QWidget,
        object_name: str,
        *,
        word_wrap: bool = False,
    ) -> QLabel:
        label = QLabel("-", parent)
        label.setObjectName(object_name)
        label.setProperty("detailValue", True)
        label.setWordWrap(word_wrap)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _add_detail_row(
        layout: QGridLayout,
        row: int,
        caption: str,
        value: QLabel,
    ) -> None:
        caption_label = QLabel(f"{caption}:")
        caption_label.setProperty("detailCaption", True)
        caption_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(caption_label, row, 0)
        layout.addWidget(value, row, 1)
        layout.setColumnStretch(1, 1)

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
        except Exception as error:
            _log_failure("Customer summaries could not be loaded", error)
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
            self._load_selected_customer_detail(
                self._customer_summaries_by_id[selected_customer_id]
            )
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
        self._load_selected_customer_detail(summary)

    def _load_selected_customer_detail(self, summary: CustomerSummary) -> None:
        self._selected_customer_id = summary.customer_id
        self._selected_customer_detail = None
        self._clear_customer_detail_values()
        self._clear_animals()
        self._clear_account_history()
        self._clear_reminders()
        try:
            with self._application_context.services() as services:
                detail = services.customer_detail.get_customer_detail(summary.customer_id)
        except Exception as error:
            _log_failure(
                "Customer detail could not be loaded for customer %s",
                error,
                summary.customer_id,
            )
            self.customer_detail_stack.setCurrentWidget(self.customer_detail_error_state)
            return

        self._selected_customer_detail = detail
        self.customer_name_label.setText(detail.full_name)
        phone = detail.phone or "-"
        self.customer_phone_label.setText(f"Telefon: {phone}")
        self.customer_phone_label.show()
        self.balance_value_label.setText(format_balance_kurus(detail.balance_kurus))
        last_transaction = format_transaction_moment(
            detail.last_transaction_date,
            detail.last_transaction_time,
        )
        self.last_transaction_label.setText(f"Son İşlem: {last_transaction}")
        self.general_phone_value.setText(phone)
        self.general_address_value.setText(detail.address or "-")
        self.general_registered_on_value.setText(format_date(detail.registered_on))
        self.general_last_transaction_value.setText(last_transaction)
        self.general_total_debt_value.setText(format_money_kurus(detail.total_debt_kurus))
        self.general_total_payment_value.setText(format_money_kurus(detail.total_payment_kurus))
        self.general_balance_value.setText(format_balance_kurus(detail.balance_kurus))
        self.general_notes_value.setText(detail.notes or "-")
        self._set_customer_write_actions_enabled(True)
        self._set_financial_actions_enabled(True)
        self._set_animal_customer_actions_enabled(True)
        self._set_reminder_customer_actions_enabled(True)
        self._set_report_actions_enabled(True)
        self.customer_detail_stack.setCurrentWidget(self.customer_detail_shell)
        self.refresh_animals_for_selected_customer(detail.customer_id)
        self.refresh_account_history(detail.customer_id)
        self.refresh_reminders_for_selected_customer(detail.customer_id)

    def _show_no_customer_selected(self) -> None:
        self._selected_customer_id = None
        self._selected_customer_detail = None
        self._clear_customer_detail_values()
        self._clear_animals()
        self._clear_account_history()
        self._clear_reminders()
        self.customer_detail_stack.setCurrentWidget(self.no_customer_selected_state)

    def _clear_customer_detail_values(self) -> None:
        self._set_customer_write_actions_enabled(False)
        self._set_financial_actions_enabled(False)
        self._set_animal_customer_actions_enabled(False)
        self._set_reminder_customer_actions_enabled(False)
        self._set_report_actions_enabled(False)
        self.customer_name_label.clear()
        self.customer_phone_label.setText("Telefon:")
        self.customer_phone_label.hide()
        self.balance_value_label.clear()
        self.last_transaction_label.setText("Son İşlem:")
        self.general_phone_value.setText("-")
        self.general_address_value.setText("-")
        self.general_registered_on_value.setText("-")
        self.general_last_transaction_value.setText("-")
        self.general_total_debt_value.setText("-")
        self.general_total_payment_value.setText("-")
        self.general_balance_value.setText("-")
        self.general_notes_value.setText("-")

    def _set_customer_write_actions_enabled(self, enabled: bool) -> None:
        self.edit_customer_button.setEnabled(enabled)
        self.archive_customer_button.setEnabled(enabled)

    def _set_financial_actions_enabled(self, enabled: bool) -> None:
        self.new_transaction_action.setEnabled(enabled)
        self.receive_payment_action.setEnabled(enabled)
        self.new_transaction_button.setEnabled(enabled)
        self.receive_payment_button.setEnabled(enabled)
        if not enabled:
            self.void_transaction_button.setEnabled(False)

    def _set_report_actions_enabled(self, enabled: bool) -> None:
        self.customer_statement_action.setEnabled(enabled)
        self.account_history_print_button.setEnabled(enabled)

    def _set_animal_customer_actions_enabled(self, enabled: bool) -> None:
        self.add_animal_button.setEnabled(enabled)
        self.archived_animals_button.setEnabled(enabled)
        if not enabled:
            self.edit_animal_button.setEnabled(False)
            self.archive_animal_button.setEnabled(False)

    def refresh_animals_for_selected_customer(
        self,
        customer_id: int | None = None,
        *,
        select_animal_id: int | None = None,
    ) -> None:
        """Reload one active customer's immutable animal records."""
        target_customer_id = self._selected_customer_id if customer_id is None else customer_id
        if target_customer_id is None:
            self._clear_animals()
            return
        preserved_animal_id = (
            self._selected_animal_id() if select_animal_id is None else select_animal_id
        )
        try:
            with self._application_context.services() as services:
                animals = services.animal.list_active_records(target_customer_id)
        except Exception as error:
            _log_failure(
                "Animals could not be loaded for customer %s",
                error,
                target_customer_id,
            )
            self._animal_summaries_by_id = {}
            self.animal_table.setRowCount(0)
            self.animal_count_label.setText("Toplam Kayıt: -")
            self.animal_list_stack.setCurrentWidget(self.animal_error_state)
            self.edit_animal_button.setEnabled(False)
            self.archive_animal_button.setEnabled(False)
            return

        self._populate_animals(animals, preserved_animal_id)

    def _populate_animals(
        self,
        animals: list[AnimalSummary],
        selected_animal_id: int | None,
    ) -> None:
        self._animal_summaries_by_id = {animal.animal_id: animal for animal in animals}
        blocker = QSignalBlocker(self.animal_table)
        self.animal_table.setRowCount(len(animals))
        selected_row: int | None = None
        for row, animal in enumerate(animals):
            values = (
                animal.ear_tag or "-",
                animal.name or "-",
                animal.species or "-",
                animal.notes or "-",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, animal.animal_id)
                self.animal_table.setItem(row, column, item)
            if animal.animal_id == selected_animal_id:
                selected_row = row
        if selected_row is not None:
            self.animal_table.selectRow(selected_row)
        del blocker

        self.animal_count_label.setText(f"Toplam Kayıt: {len(animals)} hayvan")
        self.animal_list_stack.setCurrentWidget(
            self.animal_table if animals else self.animal_empty_state
        )
        self._animal_selection_changed()

    def _clear_animals(self) -> None:
        self._animal_summaries_by_id = {}
        self.animal_table.setRowCount(0)
        self.animal_count_label.setText("Toplam Kayıt: 0 hayvan")
        self.animal_list_stack.setCurrentWidget(self.animal_empty_state)
        self.edit_animal_button.setEnabled(False)
        self.archive_animal_button.setEnabled(False)

    def _selected_animal_id(self) -> int | None:
        selected_rows = self.animal_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        item = self.animal_table.item(selected_rows[0].row(), 0)
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _animal_selection_changed(self) -> None:
        animal = self._animal_summaries_by_id.get(self._selected_animal_id())
        enabled = animal is not None and self._selected_customer_detail is not None
        self.edit_animal_button.setEnabled(enabled)
        self.archive_animal_button.setEnabled(enabled)

    def _set_reminder_customer_actions_enabled(self, enabled: bool) -> None:
        self.add_reminder_button.setEnabled(enabled)
        self.show_inactive_reminders_checkbox.setEnabled(enabled)
        if not enabled:
            self.edit_reminder_button.setEnabled(False)
            self.complete_reminder_button.setEnabled(False)
            self.cancel_reminder_button.setEnabled(False)

    def refresh_reminders_for_selected_customer(
        self,
        customer_id: int | None = None,
        *,
        select_reminder_id: int | None = None,
        reference_date: date | None = None,
    ) -> None:
        """Reload one customer's immutable reminder records."""
        target_customer_id = self._selected_customer_id if customer_id is None else customer_id
        if target_customer_id is None:
            self._clear_reminders()
            return
        preserved_reminder_id = (
            self._selected_reminder_id() if select_reminder_id is None else select_reminder_id
        )
        include_inactive = self.show_inactive_reminders_checkbox.isChecked()
        try:
            with self._application_context.services() as services:
                reminders = services.reminder.list_records_for_customer(
                    target_customer_id,
                    include_inactive=include_inactive,
                )
        except Exception as error:
            _log_failure(
                "Reminders could not be loaded for customer %s",
                error,
                target_customer_id,
            )
            self._reminder_summaries_by_id = {}
            self.reminder_table.setRowCount(0)
            self.reminder_count_label.setText("Toplam Hatırlatma: -")
            self.today_reminder_count_label.setText("Bugün Yapılacak: -")
            self.reminder_list_stack.setCurrentWidget(self.reminder_error_state)
            self._reminder_selection_changed()
            return

        self._populate_reminders(
            reminders,
            preserved_reminder_id,
            reference_date=reference_date or self._date_provider(),
        )

    def _schedule_reminder_rollover(self) -> None:
        now = QDateTime.currentDateTime()
        next_midnight = QDateTime(now.date().addDays(1), QTime(0, 0), now.timeZone())
        milliseconds = max(1_000, now.msecsTo(next_midnight) + 1_000)
        self._reminder_rollover_timer.start(milliseconds)

    def _refresh_reminders_after_date_rollover(self) -> None:
        try:
            if self._selected_customer_id is not None:
                self.refresh_reminders_for_selected_customer(
                    reference_date=self._date_provider(),
                )
        finally:
            self._schedule_reminder_rollover()

    def run_authenticated_startup_actions(self) -> None:
        """Run the non-blocking-failure startup checks once after the window is shown."""
        if self._startup_actions_run:
            return
        self._startup_actions_run = True

        try:
            self._application_context.run_automatic_backup(
                reference_datetime=self._datetime_provider(),
            )
        except Exception as error:
            _log_failure("Automatic daily backup creation failed", error)
            QMessageBox.warning(
                self,
                "Otomatik Yedekleme",
                "Otomatik yedek oluşturulamadı.\nVerilerinizi manuel olarak yedeklemeniz önerilir.",
            )

        try:
            with self._application_context.services() as services:
                summary = services.reminder.get_startup_summary(self._date_provider())
        except Exception as error:
            _log_failure("The startup due-reminder summary could not be loaded", error)
            QMessageBox.warning(
                self,
                "Hatırlatmalar",
                "Hatırlatmalar kontrol edilemedi. Lütfen daha sonra yeniden deneyin.",
            )
            return

        if summary.total_count == 0:
            return
        dialog = reminder_dialogs.StartupReminderSummaryDialog(summary, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        if accepted:
            self._navigate_to_startup_reminders(summary)

    def _navigate_to_startup_reminders(self, summary: StartupReminderSummary) -> None:
        """Focus the earliest due reminder whose owner is in the active customer list."""
        customer_id = summary.focus_customer_id
        if customer_id is None:
            self.statusBar().showMessage(
                "Gecikmiş hatırlatmalar arşivlenmiş müşterilere ait olabilir.",
                8_000,
            )
            return

        if self.customer_search_input.text():
            blocker = QSignalBlocker(self.customer_search_input)
            self.customer_search_input.clear()
            del blocker
            self._search_timer.stop()
            self.refresh_customer_summaries()

        target_item: QListWidgetItem | None = None
        for row in range(self.customer_list.count()):
            item = self.customer_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == customer_id:
                target_item = item
                break
        if target_item is None:
            self.statusBar().showMessage(
                "Hatırlatma sahibi aktif müşteri listesinde bulunamadı.",
                8_000,
            )
            return

        self.customer_list.setCurrentItem(target_item)
        self.customer_tabs.setCurrentWidget(self.reminders_tab)
        reminder_id = summary.focus_reminder_id
        if reminder_id is None:
            return
        for row in range(self.reminder_table.rowCount()):
            item = self.reminder_table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == reminder_id:
                self.reminder_table.selectRow(row)
                self.reminder_table.setFocus()
                break

    def _populate_reminders(
        self,
        reminders: list[ReminderSummary],
        selected_reminder_id: int | None,
        *,
        reference_date: date,
    ) -> None:
        self._reminder_summaries_by_id = {reminder.reminder_id: reminder for reminder in reminders}
        blocker = QSignalBlocker(self.reminder_table)
        self.reminder_table.setRowCount(len(reminders))
        selected_row: int | None = None
        for row, reminder in enumerate(reminders):
            state = classify_reminder(reminder, reference_date)
            values = (
                format_date(reminder.remind_on),
                reminder.note,
                format_reminder_status(reminder, reference_date),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, reminder.reminder_id)
                if state is ReminderPresentationState.OVERDUE:
                    item.setBackground(QColor("#fff4d6"))
                elif state is ReminderPresentationState.TODAY:
                    item.setBackground(QColor("#e5effa"))
                elif state in (
                    ReminderPresentationState.COMPLETED,
                    ReminderPresentationState.CANCELLED,
                ):
                    item.setBackground(QColor("#eef1f4"))
                    item.setForeground(QColor("#6f7a85"))
                self.reminder_table.setItem(row, column, item)
            if reminder.reminder_id == selected_reminder_id:
                selected_row = row
        if selected_row is not None:
            self.reminder_table.selectRow(selected_row)
        del blocker

        self.reminder_count_label.setText(f"Toplam Hatırlatma: {len(reminders)}")
        today_count = count_active_reminders_today(reminders, reference_date)
        self.today_reminder_count_label.setText(f"Bugün Yapılacak: {today_count} Hatırlatma")
        if reminders:
            self.reminder_list_stack.setCurrentWidget(self.reminder_table)
        else:
            message = (
                "Gösterilecek hatırlatma bulunmuyor."
                if self.show_inactive_reminders_checkbox.isChecked()
                else "Bu müşteriye ait aktif hatırlatma bulunmuyor."
            )
            self.reminder_empty_state.set_message(message)
            self.reminder_list_stack.setCurrentWidget(self.reminder_empty_state)
        self._reminder_selection_changed()

    def _clear_reminders(self) -> None:
        self._reminder_summaries_by_id = {}
        self.reminder_table.setRowCount(0)
        self.reminder_count_label.setText("Toplam Hatırlatma: 0")
        self.today_reminder_count_label.setText("Bugün Yapılacak: 0 Hatırlatma")
        self.reminder_empty_state.set_message("Bu müşteriye ait aktif hatırlatma bulunmuyor.")
        self.reminder_list_stack.setCurrentWidget(self.reminder_empty_state)
        self.edit_reminder_button.setEnabled(False)
        self.complete_reminder_button.setEnabled(False)
        self.cancel_reminder_button.setEnabled(False)

    def _selected_reminder_id(self) -> int | None:
        selected_rows = self.reminder_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        item = self.reminder_table.item(selected_rows[0].row(), 0)
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _reminder_selection_changed(self) -> None:
        reminder = self._reminder_summaries_by_id.get(self._selected_reminder_id())
        active = (
            reminder is not None
            and reminder.completed_at is None
            and reminder.cancelled_at is None
            and self._selected_customer_detail is not None
        )
        self.edit_reminder_button.setEnabled(active)
        self.complete_reminder_button.setEnabled(active)
        self.cancel_reminder_button.setEnabled(active)

    def _reminder_history_toggled(self, _checked: bool) -> None:
        if self._selected_customer_detail is not None:
            self.refresh_reminders_for_selected_customer()

    def refresh_account_history(self, customer_id: int | None = None) -> None:
        """Reload the selected customer's plain financial-history rows."""
        target_customer_id = self._selected_customer_id if customer_id is None else customer_id
        if target_customer_id is None:
            self._clear_account_history()
            return

        selected_transaction_id = self._selected_transaction_id()
        try:
            with self._application_context.services() as services:
                rows = services.account_history.list_for_customer(target_customer_id)
        except Exception as error:
            _log_failure(
                "Account history could not be loaded for customer %s",
                error,
                target_customer_id,
            )
            self._account_history_by_id = {}
            self.account_history_table.setRowCount(0)
            self.account_history_stack.setCurrentWidget(self.account_history_error_state)
            self.void_transaction_button.setEnabled(False)
            return

        self._populate_account_history(rows, selected_transaction_id)

    def _populate_account_history(
        self,
        rows: list[AccountHistoryRow],
        selected_transaction_id: int | None,
    ) -> None:
        self._account_history_by_id = {row.transaction_id: row for row in rows}
        blocker = QSignalBlocker(self.account_history_table)
        self.account_history_table.setRowCount(len(rows))
        selected_table_row: int | None = None
        for table_row, history_row in enumerate(rows):
            animal_text = (
                "-"
                if history_row.animal_id is None
                else format_animal_display(
                    history_row.animal_ear_tag,
                    history_row.animal_name,
                    history_row.animal_species,
                )
            )
            description = history_row.description
            if history_row.voided_at is not None:
                description = f"{description} • İptal"
            values = (
                format_date(history_row.transaction_date),
                history_row.transaction_time.strftime("%H:%M")
                if history_row.transaction_time is not None
                else "-",
                description,
                animal_text,
                format_money_kurus(history_row.amount_kurus)
                if history_row.amount_kurus > 0
                else "",
                format_money_kurus(abs(history_row.amount_kurus))
                if history_row.amount_kurus < 0
                else "",
                format_balance_kurus(history_row.running_balance_kurus),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, history_row.transaction_id)
                if column >= 4:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if history_row.voided_at is not None:
                    item.setBackground(QColor("#fff0f1"))
                    item.setToolTip(history_row.void_reason or "İptal edildi")
                self.account_history_table.setItem(table_row, column, item)
            if history_row.transaction_id == selected_transaction_id:
                selected_table_row = table_row
        if selected_table_row is not None:
            self.account_history_table.selectRow(selected_table_row)
        del blocker

        if rows:
            self.account_history_stack.setCurrentWidget(self.account_history_table)
        else:
            self.account_history_stack.setCurrentWidget(self.account_history_empty_state)
        self._account_history_selection_changed()

    def _clear_account_history(self) -> None:
        self._account_history_by_id = {}
        self.account_history_table.setRowCount(0)
        self.account_history_stack.setCurrentWidget(self.account_history_empty_state)
        self.void_transaction_button.setEnabled(False)

    def _selected_transaction_id(self) -> int | None:
        selected_rows = self.account_history_table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        item = self.account_history_table.item(selected_rows[0].row(), 0)
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _account_history_selection_changed(self) -> None:
        transaction_id = self._selected_transaction_id()
        row = self._account_history_by_id.get(transaction_id)
        self.void_transaction_button.setEnabled(
            row is not None and row.voided_at is None and self._selected_customer_detail is not None
        )

    def _open_new_customer_dialog(self) -> None:
        dialog = CustomerFormDialog("Yeni Müşteri", parent=self)
        created_customer_id: int | None = None

        def create_customer() -> None:
            nonlocal created_customer_id
            values = dialog.values()
            try:
                with self._application_context.services() as services:
                    customer = services.customer.create_customer(
                        values.full_name,
                        phone=values.phone,
                        address=values.address,
                        notes=values.notes,
                        registered_on=None,
                    )
                    created_customer_id = customer.id
            except ValidationError:
                dialog.show_error("Lütfen gerekli alanları doğru şekilde doldurun.")
            except ServiceError:
                dialog.show_error("Müşteri kaydedilemedi. Lütfen yeniden deneyin.")
            except Exception as error:
                _log_failure("Customer could not be created", error)
                dialog.show_error("Müşteri kaydedilemedi. Lütfen yeniden deneyin.")
            else:
                dialog.accept()

        dialog.save_requested.connect(create_customer)
        dialog.exec()
        dialog.save_requested.disconnect(create_customer)
        dialog.deleteLater()
        if created_customer_id is not None:
            self._selected_customer_id = created_customer_id
            self.refresh_customer_summaries()

    def _open_edit_customer_dialog(self) -> None:
        detail = self._get_selected_customer_detail_for_edit()
        if detail is None:
            return

        dialog = CustomerFormDialog(
            "Müşteriyi Düzenle",
            initial_values=CustomerFormValues(
                full_name=detail.full_name,
                phone=detail.phone or "",
                address=detail.address or "",
                notes=detail.notes or "",
            ),
            parent=self,
        )
        updated = False

        def update_customer() -> None:
            nonlocal updated
            values = dialog.values()
            try:
                with self._application_context.services() as services:
                    services.customer.update_customer(
                        detail.customer_id,
                        full_name=values.full_name,
                        phone=values.phone,
                        address=values.address,
                        notes=values.notes,
                        registered_on=detail.registered_on,
                    )
            except ValidationError:
                dialog.show_error("Lütfen gerekli alanları doğru şekilde doldurun.")
            except ServiceError:
                dialog.show_error("Müşteri güncellenemedi. Lütfen yeniden deneyin.")
            except Exception as error:
                _log_failure(
                    "Customer %s could not be updated",
                    error,
                    detail.customer_id,
                )
                dialog.show_error("Müşteri güncellenemedi. Lütfen yeniden deneyin.")
            else:
                updated = True
                dialog.accept()

        dialog.save_requested.connect(update_customer)
        dialog.exec()
        dialog.save_requested.disconnect(update_customer)
        dialog.deleteLater()
        if updated:
            self._selected_customer_id = detail.customer_id
            self.refresh_customer_summaries()

    def _get_selected_customer_detail_for_edit(self) -> CustomerDetail | None:
        customer_id = self._selected_customer_id
        if customer_id is None:
            return None
        detail = self._selected_customer_detail
        if detail is not None and detail.customer_id == customer_id:
            return detail

        try:
            with self._application_context.services() as services:
                return services.customer_detail.get_customer_detail(customer_id)
        except ServiceError:
            self._show_customer_operation_error(
                "Müşteri bilgileri yüklenemedi. Lütfen yeniden deneyin."
            )
        except Exception as error:
            _log_failure(
                "Customer %s could not be loaded for editing",
                error,
                customer_id,
            )
            self._show_customer_operation_error(
                "Müşteri bilgileri yüklenemedi. Lütfen yeniden deneyin."
            )
        return None

    def _archive_selected_customer(self) -> None:
        detail = self._selected_customer_detail
        if detail is None or detail.customer_id != self._selected_customer_id:
            return
        if not customer_dialogs.confirm_customer_archive(self, detail.full_name):
            return

        try:
            with self._application_context.services() as services:
                services.customer.archive_customer(detail.customer_id)
        except ServiceError:
            self._show_customer_operation_error("Müşteri arşivlenemedi. Lütfen yeniden deneyin.")
            return
        except Exception as error:
            _log_failure("Customer %s could not be archived", error, detail.customer_id)
            self._show_customer_operation_error("Müşteri arşivlenemedi. Lütfen yeniden deneyin.")
            return

        self.refresh_customer_summaries()

    def _open_add_animal_dialog(self) -> None:
        detail = self._selected_customer_detail
        if detail is None or detail.customer_id != self._selected_customer_id:
            return
        dialog = AnimalFormDialog("Hayvan Ekle", parent=self)
        created_animal_id: int | None = None

        def create_animal() -> None:
            nonlocal created_animal_id
            values = dialog.values()
            try:
                with self._application_context.services() as services:
                    animal = services.animal.create_animal(
                        detail.customer_id,
                        ear_tag=values.ear_tag,
                        name=values.name,
                        species=values.species,
                        notes=values.notes,
                    )
                    created_animal_id = animal.id
            except ServiceError:
                dialog.show_error("Hayvan kaydedilemedi. Lütfen yeniden deneyin.")
            except Exception as error:
                _log_failure("Animal could not be created", error)
                dialog.show_error("Hayvan kaydedilemedi. Lütfen yeniden deneyin.")
            else:
                dialog.accept()

        dialog.save_requested.connect(create_animal)
        dialog.exec()
        dialog.save_requested.disconnect(create_animal)
        dialog.deleteLater()
        if created_animal_id is not None:
            self.refresh_animals_for_selected_customer(
                detail.customer_id,
                select_animal_id=created_animal_id,
            )

    def _open_edit_animal_dialog(self) -> None:
        animal_id = self._selected_animal_id()
        animal = self._animal_summaries_by_id.get(animal_id)
        if animal is None:
            return
        dialog = AnimalFormDialog(
            "Hayvanı Düzenle",
            initial_values=AnimalFormValues(
                ear_tag=animal.ear_tag or "",
                name=animal.name or "",
                species=animal.species or "",
                notes=animal.notes or "",
            ),
            parent=self,
        )
        updated = False

        def update_animal() -> None:
            nonlocal updated
            values = dialog.values()
            try:
                with self._application_context.services() as services:
                    services.animal.update_animal(
                        animal.animal_id,
                        ear_tag=values.ear_tag,
                        name=values.name,
                        species=values.species,
                        notes=values.notes,
                    )
            except ServiceError:
                dialog.show_error("Hayvan güncellenemedi. Lütfen yeniden deneyin.")
            except Exception as error:
                _log_failure("Animal %s could not be updated", error, animal.animal_id)
                dialog.show_error("Hayvan güncellenemedi. Lütfen yeniden deneyin.")
            else:
                updated = True
                dialog.accept()

        dialog.save_requested.connect(update_animal)
        dialog.exec()
        dialog.save_requested.disconnect(update_animal)
        dialog.deleteLater()
        if updated:
            self.refresh_animals_for_selected_customer(
                animal.customer_id,
                select_animal_id=animal.animal_id,
            )
            self.refresh_account_history(animal.customer_id)

    def _archive_selected_animal(self) -> None:
        animal_id = self._selected_animal_id()
        animal = self._animal_summaries_by_id.get(animal_id)
        if animal is None:
            return
        animal_label = format_animal_identity(animal.ear_tag, animal.name, animal.species)
        if not animal_dialogs.confirm_animal_archive(self, animal_label):
            return
        try:
            with self._application_context.services() as services:
                services.animal.archive_animal(animal.animal_id)
        except ServiceError:
            self._show_animal_operation_error("Hayvan arşivlenemedi. Lütfen yeniden deneyin.")
            return
        except Exception as error:
            _log_failure("Animal %s could not be archived", error, animal.animal_id)
            self._show_animal_operation_error("Hayvan arşivlenemedi. Lütfen yeniden deneyin.")
            return

        self.refresh_animals_for_selected_customer(animal.customer_id)
        self.refresh_account_history(animal.customer_id)

    def _open_archived_animals_dialog(self) -> None:
        customer_id = self._selected_customer_id
        if customer_id is None or self._selected_customer_detail is None:
            return
        dialog = ArchivedAnimalsDialog(self)
        try:
            dialog.set_animals(self._load_archived_animals(customer_id))
        except Exception as error:
            _log_failure("Archived animals could not be loaded", error)
            dialog.set_animals([])
            dialog.show_error("Arşivlenmiş hayvanlar yüklenemedi.")

        def unarchive_animal(animal_id: int) -> None:
            try:
                with self._application_context.services() as services:
                    services.animal.unarchive_animal(animal_id)
            except ServiceError:
                dialog.show_error("Hayvan geri açılamadı. Lütfen yeniden deneyin.")
                return
            except Exception as error:
                _log_failure("Animal %s could not be unarchived", error, animal_id)
                dialog.show_error("Hayvan geri açılamadı. Lütfen yeniden deneyin.")
                return

            self.refresh_animals_for_selected_customer(
                customer_id,
                select_animal_id=animal_id,
            )
            try:
                dialog.set_animals(self._load_archived_animals(customer_id))
            except Exception as error:
                _log_failure("Archived animals could not be refreshed", error)
                dialog.show_error("Arşivlenmiş hayvan listesi yenilenemedi.")

        dialog.unarchive_requested.connect(unarchive_animal)
        dialog.exec()
        dialog.unarchive_requested.disconnect(unarchive_animal)
        dialog.deleteLater()

    def _load_archived_animals(self, customer_id: int) -> list[AnimalSummary]:
        with self._application_context.services() as services:
            return services.animal.list_archived_records(customer_id)

    def _show_animal_operation_error(self, message: str) -> None:
        QMessageBox.warning(self, "İşlem Tamamlanamadı", message)

    def _open_add_reminder_dialog(self) -> None:
        detail = self._selected_customer_detail
        if detail is None or detail.customer_id != self._selected_customer_id:
            return
        dialog = ReminderFormDialog("Yeni Hatırlatma", parent=self)
        created_reminder_id: int | None = None

        def create_reminder() -> None:
            nonlocal created_reminder_id
            values = dialog.values()
            try:
                with self._application_context.services() as services:
                    reminder = services.reminder.create_reminder(
                        detail.customer_id,
                        values.remind_on,
                        values.note,
                    )
                    created_reminder_id = reminder.id
            except ServiceError:
                dialog.show_error("Hatırlatma kaydedilemedi. Lütfen alanları kontrol edin.")
            except Exception as error:
                _log_failure("Reminder could not be created", error)
                dialog.show_error("Hatırlatma kaydedilemedi. Lütfen yeniden deneyin.")
            else:
                dialog.accept()

        dialog.save_requested.connect(create_reminder)
        dialog.exec()
        dialog.save_requested.disconnect(create_reminder)
        dialog.deleteLater()
        if created_reminder_id is not None:
            self.refresh_reminders_for_selected_customer(
                detail.customer_id,
                select_reminder_id=created_reminder_id,
            )

    def _open_edit_reminder_dialog(self) -> None:
        reminder_id = self._selected_reminder_id()
        reminder = self._reminder_summaries_by_id.get(reminder_id)
        if (
            reminder is None
            or reminder.completed_at is not None
            or reminder.cancelled_at is not None
        ):
            return
        dialog = ReminderFormDialog(
            "Hatırlatmayı Düzenle",
            initial_values=ReminderFormValues(
                remind_on=reminder.remind_on,
                note=reminder.note,
            ),
            parent=self,
        )
        updated = False

        def update_reminder() -> None:
            nonlocal updated
            values = dialog.values()
            try:
                with self._application_context.services() as services:
                    services.reminder.update_reminder(
                        reminder.reminder_id,
                        remind_on=values.remind_on,
                        note=values.note,
                    )
            except ServiceError:
                dialog.show_error("Hatırlatma güncellenemedi. Lütfen alanları kontrol edin.")
            except Exception as error:
                _log_failure(
                    "Reminder %s could not be updated",
                    error,
                    reminder.reminder_id,
                )
                dialog.show_error("Hatırlatma güncellenemedi. Lütfen yeniden deneyin.")
            else:
                updated = True
                dialog.accept()

        dialog.save_requested.connect(update_reminder)
        dialog.exec()
        dialog.save_requested.disconnect(update_reminder)
        dialog.deleteLater()
        if updated:
            self.refresh_reminders_for_selected_customer(
                reminder.customer_id,
                select_reminder_id=reminder.reminder_id,
            )

    def _complete_selected_reminder(self) -> None:
        reminder = self._reminder_summaries_by_id.get(self._selected_reminder_id())
        if (
            reminder is None
            or reminder.completed_at is not None
            or reminder.cancelled_at is not None
        ):
            return
        if not reminder_dialogs.confirm_reminder_completion(self, reminder):
            return
        try:
            with self._application_context.services() as services:
                services.reminder.complete_reminder(reminder.reminder_id)
        except ServiceError:
            self._show_reminder_operation_error("Hatırlatma tamamlanamadı. Lütfen yeniden deneyin.")
            return
        except Exception as error:
            _log_failure(
                "Reminder %s could not be completed",
                error,
                reminder.reminder_id,
            )
            self._show_reminder_operation_error("Hatırlatma tamamlanamadı. Lütfen yeniden deneyin.")
            return
        self.refresh_reminders_for_selected_customer(
            reminder.customer_id,
            select_reminder_id=reminder.reminder_id,
        )

    def _cancel_selected_reminder(self) -> None:
        reminder = self._reminder_summaries_by_id.get(self._selected_reminder_id())
        if (
            reminder is None
            or reminder.completed_at is not None
            or reminder.cancelled_at is not None
        ):
            return
        if not reminder_dialogs.confirm_reminder_cancellation(self, reminder):
            return
        try:
            with self._application_context.services() as services:
                services.reminder.cancel_reminder(reminder.reminder_id)
        except ServiceError:
            self._show_reminder_operation_error(
                "Hatırlatma iptal edilemedi. Lütfen yeniden deneyin."
            )
            return
        except Exception as error:
            _log_failure(
                "Reminder %s could not be cancelled",
                error,
                reminder.reminder_id,
            )
            self._show_reminder_operation_error(
                "Hatırlatma iptal edilemedi. Lütfen yeniden deneyin."
            )
            return
        self.refresh_reminders_for_selected_customer(
            reminder.customer_id,
            select_reminder_id=reminder.reminder_id,
        )

    def _show_reminder_operation_error(self, message: str) -> None:
        QMessageBox.warning(self, "İşlem Tamamlanamadı", message)

    def _open_debt_transaction_dialog(self) -> None:
        detail = self._selected_customer_detail
        if detail is None or detail.customer_id != self._selected_customer_id:
            return
        try:
            with self._application_context.services() as services:
                animal_options = services.animal.list_active_options(detail.customer_id)
        except ServiceError:
            self._show_financial_operation_error(
                "Hayvan seçenekleri yüklenemedi. Lütfen yeniden deneyin."
            )
            return
        except Exception as error:
            _log_failure("Animal options could not be loaded", error)
            self._show_financial_operation_error(
                "Hayvan seçenekleri yüklenemedi. Lütfen yeniden deneyin."
            )
            return

        dialog = DebtTransactionDialog(detail.full_name, animal_options, self)
        created = False

        def create_debt() -> None:
            nonlocal created
            values = dialog.values()
            try:
                with self._application_context.services() as services:
                    services.transaction.create_debt(
                        detail.customer_id,
                        transaction_date=values.transaction_date,
                        description=values.description,
                        amount_kurus=values.amount_kurus,
                        animal_id=values.animal_id,
                        transaction_time=None,
                        note=values.note,
                    )
            except (ValidationError, ServiceError):
                dialog.show_error("İşlem kaydedilemedi. Lütfen alanları kontrol edin.")
            except Exception as error:
                _log_failure("Debt transaction could not be created", error)
                dialog.show_error("İşlem kaydedilemedi. Lütfen yeniden deneyin.")
            else:
                created = True
                dialog.accept()

        dialog.save_requested.connect(create_debt)
        dialog.exec()
        dialog.save_requested.disconnect(create_debt)
        dialog.deleteLater()
        if created:
            self._refresh_after_financial_write(detail.customer_id)

    def _open_payment_dialog(self) -> None:
        detail = self._selected_customer_detail
        if detail is None or detail.customer_id != self._selected_customer_id:
            return
        dialog = PaymentDialog(detail.full_name, detail.balance_kurus, self)
        created = False

        def create_payment() -> None:
            nonlocal created
            values = dialog.values()
            try:
                with self._application_context.services() as services:
                    services.transaction.create_payment(
                        detail.customer_id,
                        transaction_date=values.transaction_date,
                        description=values.description,
                        amount_kurus=values.amount_kurus,
                        animal_id=None,
                        transaction_time=None,
                        note=None,
                    )
            except (ValidationError, ServiceError):
                dialog.show_error("Ödeme kaydedilemedi. Lütfen alanları kontrol edin.")
            except Exception as error:
                _log_failure("Payment could not be created", error)
                dialog.show_error("Ödeme kaydedilemedi. Lütfen yeniden deneyin.")
            else:
                created = True
                dialog.accept()

        dialog.save_requested.connect(create_payment)
        dialog.exec()
        dialog.save_requested.disconnect(create_payment)
        dialog.deleteLater()
        if created:
            self._refresh_after_financial_write(detail.customer_id)

    def _open_void_transaction_dialog(self) -> None:
        transaction_id = self._selected_transaction_id()
        row = self._account_history_by_id.get(transaction_id)
        if row is None or row.voided_at is not None:
            return
        dialog = VoidTransactionDialog(row, self)
        voided = False

        def void_transaction() -> None:
            nonlocal voided
            try:
                with self._application_context.services() as services:
                    services.transaction.void_transaction(row.transaction_id, dialog.reason())
            except (ValidationError, ServiceError):
                dialog.show_error("İşlem iptal edilemedi. Lütfen yeniden deneyin.")
            except Exception as error:
                _log_failure(
                    "Transaction %s could not be voided",
                    error,
                    row.transaction_id,
                )
                dialog.show_error("İşlem iptal edilemedi. Lütfen yeniden deneyin.")
            else:
                voided = True
                dialog.accept()

        dialog.void_requested.connect(void_transaction)
        dialog.exec()
        dialog.void_requested.disconnect(void_transaction)
        dialog.deleteLater()
        if voided and self._selected_customer_id is not None:
            self._refresh_after_financial_write(self._selected_customer_id)

    def _refresh_after_financial_write(self, customer_id: int) -> None:
        self._selected_customer_id = customer_id
        self.refresh_customer_summaries()

    def _show_financial_operation_error(self, message: str) -> None:
        QMessageBox.warning(self, "İşlem Tamamlanamadı", message)

    def _open_change_password_dialog(self) -> None:
        dialog = auth_dialogs.PasswordChangeDialog(self._application_context.authentication, self)
        changed = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        if changed:
            QMessageBox.information(
                self,
                "Parola Değiştirildi",
                "Hesiva parolası başarıyla değiştirildi.",
            )

    def _open_settings_dialog(self) -> None:
        try:
            current_settings = self._application_context.settings.get_settings()
        except Exception as error:
            _log_failure("Hesiva settings could not be loaded", error)
            QMessageBox.warning(
                self,
                "Ayarlar Açılamadı",
                "Hesiva ayarları yüklenemedi. Lütfen yeniden deneyin.",
            )
            return

        dialog = settings_dialogs.SettingsDialog(current_settings, self)

        def change_backup_location() -> None:
            selected_directory = QFileDialog.getExistingDirectory(
                dialog,
                "Yedekleme Konumunu Seç",
                str(dialog.backup_destination_directory),
            )
            if not selected_directory:
                return
            try:
                self._application_context.settings.update_backup_destination_directory(
                    Path(selected_directory)
                )
                dialog.set_settings(self._application_context.settings.get_settings())
            except (ValidationError, ServiceError):
                dialog_message = "Yedekleme konumu kaydedilemedi. Lütfen başka bir dizin seçin."
                QMessageBox.warning(dialog, "Ayarlar Kaydedilemedi", dialog_message)
            except Exception as error:
                _log_failure("The preferred backup destination could not be updated", error)
                QMessageBox.warning(
                    dialog,
                    "Ayarlar Kaydedilemedi",
                    "Yedekleme konumu kaydedilemedi. Lütfen yeniden deneyin.",
                )

        dialog.password_change_requested.connect(self._open_change_password_dialog)
        dialog.backup_location_change_requested.connect(change_backup_location)
        dialog.exec()
        dialog.password_change_requested.disconnect(self._open_change_password_dialog)
        dialog.backup_location_change_requested.disconnect(change_backup_location)
        dialog.deleteLater()

    def _open_about_dialog(self) -> None:
        try:
            application_version = get_application_version()
        except Exception as error:
            _log_failure("The Hesiva application version could not be loaded", error)
            QMessageBox.warning(
                self,
                "Hakkında Açılamadı",
                "Hesiva sürüm bilgisi yüklenemedi. Lütfen yeniden deneyin.",
            )
            return
        dialog = settings_dialogs.AboutDialog(application_version, self)
        dialog.exec()
        dialog.deleteLater()

    def _open_legacy_import_dialog(self) -> None:
        dialog = LegacyImportDialog(self._application_context, self)
        dialog.import_completed.connect(self._refresh_after_legacy_import)
        dialog.exec()
        dialog.wait_for_active_operation()
        dialog.import_completed.disconnect(self._refresh_after_legacy_import)
        dialog.deleteLater()

    def _refresh_after_legacy_import(self, _result: LegacyImportResult) -> None:
        self._reload_business_state()
        self.statusBar().showMessage("Eski Veresiye 5 verileri başarıyla içe aktarıldı.", 8000)

    def _open_backup_dialog(self) -> None:
        try:
            backup_directory = self._application_context.prepare_manual_backup_directory()
        except Exception as error:
            _log_failure("The preferred backup directory could not be resolved", error)
            QMessageBox.warning(
                self,
                "Yedekleme Açılamadı",
                "Yedekleme konumu yüklenemedi. Ayarlar bölümünden konumu kontrol edin.",
            )
            return
        dialog = backup_dialogs.BackupDialog(backup_directory, self)

        def change_location() -> None:
            selected_directory = QFileDialog.getExistingDirectory(
                dialog,
                "Yedekleme Konumunu Seç",
                str(dialog.destination_directory),
            )
            if selected_directory:
                dialog.set_destination_directory(Path(selected_directory))

        def create_backup() -> None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            suggested_path = dialog.destination_directory / f"hesiva_backup_{timestamp}.zip"
            selected_path, _ = QFileDialog.getSaveFileName(
                dialog,
                "Hesiva Yedeğini Kaydet",
                str(suggested_path),
                "Hesiva Yedeği (*.zip)",
            )
            if not selected_path:
                return
            destination = Path(selected_path)
            if destination.suffix.lower() != ".zip":
                destination = destination.with_suffix(".zip")
            dialog.set_busy(True)
            try:
                metadata = self._application_context.create_backup(destination)
            except BackupPathError:
                LOGGER.warning("The selected manual-backup destination is unavailable")
                dialog.show_operation_error(
                    "Son yedekleme başarısız oldu: Yedekleme konumu kullanılamıyor."
                )
            except BackupError as error:
                _log_failure("Hesiva backup creation failed", error)
                dialog.show_operation_error("Son yedekleme başarısız oldu: Yedek oluşturulamadı.")
            except Exception as error:
                _log_failure("Unexpected Hesiva backup creation failure", error)
                dialog.show_operation_error("Son yedekleme başarısız oldu: Yedek oluşturulamadı.")
            else:
                dialog.set_destination_directory(destination.parent)
                dialog.show_backup_success(metadata)
            finally:
                dialog.set_busy(False)

        def restore_backup() -> None:
            selected_path, _ = QFileDialog.getOpenFileName(
                dialog,
                "Hesiva Yedeğini Seç",
                str(dialog.destination_directory),
                "Hesiva Yedeği (*.zip)",
            )
            if not selected_path:
                return
            backup_path = Path(selected_path)
            try:
                metadata = self._application_context.validate_backup(backup_path)
            except BackupValidationError:
                LOGGER.warning("An invalid Hesiva backup was selected for restore")
                dialog.show_operation_error(
                    "Geçersiz yedek dosyası: Yedek doğrulanamadı veya uyumlu değil."
                )
                return
            except BackupError as error:
                _log_failure("Hesiva backup validation failed", error)
                dialog.show_operation_error("Yedek dosyası doğrulanamadı.")
                return
            except Exception as error:
                _log_failure("Unexpected Hesiva backup validation failure", error)
                dialog.show_operation_error("Yedek dosyası doğrulanamadı.")
                return

            confirmation = backup_dialogs.RestoreConfirmationDialog(metadata, dialog)
            confirmed = confirmation.exec() == QDialog.DialogCode.Accepted
            confirmation.deleteLater()
            if not confirmed:
                return

            dialog.set_busy(True)
            try:
                self._application_context.restore_backup(backup_path)
            except RestoreRecoveryRequiredError as error:
                _log_failure("Restore recovery requires an application restart", error)
                QMessageBox.critical(
                    dialog,
                    "Güvenli Yeniden Başlatma Gerekli",
                    "Geri yükleme tamamlanamadı. Güvenli kurtarma sonraki açılışta "
                    "tamamlanacaktır; yeni değişiklik yapılmaması için Hesiva şimdi kapanacak.",
                )
                dialog.reject()
                QTimer.singleShot(0, self.close)
            except RestoreRollbackError as error:
                _log_failure("Restore rollback failed; safety backup retained", error)
                QMessageBox.critical(
                    dialog,
                    "Geri Yükleme Tamamlanamadı",
                    "Geri yükleme ve otomatik kurtarma tamamlanamadı. "
                    "Güvenlik yedeği korundu; Hesiva'yı kapatıp teknik destek alın.",
                )
                dialog.reject()
                QTimer.singleShot(0, self.close)
            except BackupError as error:
                _log_failure("Hesiva restore failed", error)
                dialog.show_operation_error(
                    "Geri yükleme tamamlanamadı. Mevcut veriler korundu veya geri alındı."
                )
            except Exception as error:
                _log_failure("Unexpected Hesiva restore failure", error)
                dialog.show_operation_error(
                    "Geri yükleme tamamlanamadı. Mevcut veriler korundu veya geri alındı."
                )
            else:
                dialog.accept()
                self._reload_business_state()
                QMessageBox.information(
                    self,
                    "Geri Yükleme Tamamlandı",
                    "Yedek başarıyla geri yüklendi. Hesiva verileri yenilendi.",
                )
            finally:
                dialog.set_busy(False)

        dialog.change_location_requested.connect(change_location)
        dialog.create_requested.connect(create_backup)
        dialog.restore_requested.connect(restore_backup)
        dialog.exec()
        dialog.change_location_requested.disconnect(change_location)
        dialog.create_requested.disconnect(create_backup)
        dialog.restore_requested.disconnect(restore_backup)
        dialog.deleteLater()

    def _reload_business_state(self) -> None:
        """Discard database-derived UI values and reload them from the application context."""
        self._search_timer.stop()
        search_blocker = QSignalBlocker(self.customer_search_input)
        sort_blocker = QSignalBlocker(self.customer_sort_combo)
        self.customer_search_input.clear()
        self.customer_sort_combo.setCurrentIndex(0)
        del search_blocker, sort_blocker
        self._customer_summaries_by_id = {}
        self.customer_list.clear()
        self._show_no_customer_selected()
        self.refresh_customer_summaries()

    def _open_customer_statement(self) -> None:
        customer_id = self._selected_customer_id
        if customer_id is None or self._selected_customer_detail is None:
            return
        dialog = CustomerStatementDialog(self._application_context, customer_id, self)
        dialog.exec()
        dialog.deleteLater()

    def _open_monthly_summary(self) -> None:
        dialog = MonthlySummaryDialog(self._application_context, self)
        dialog.exec()
        dialog.deleteLater()

    def _open_yearly_summary(self) -> None:
        dialog = YearlySummaryDialog(self._application_context, self)
        dialog.exec()
        dialog.deleteLater()

    def _open_archived_customers_dialog(self) -> None:
        dialog = ArchivedCustomersDialog(self)
        try:
            dialog.set_customers(self._load_archived_customers())
        except Exception as error:
            _log_failure("Archived customers could not be loaded", error)
            dialog.set_customers([])
            dialog.show_error("Arşivlenmiş müşteriler yüklenemedi.")

        def unarchive_customer(customer_id: int) -> None:
            try:
                with self._application_context.services() as services:
                    services.customer.unarchive_customer(customer_id)
            except ServiceError:
                dialog.show_error("Müşteri geri açılamadı. Lütfen yeniden deneyin.")
                return
            except Exception as error:
                _log_failure("Customer %s could not be unarchived", error, customer_id)
                dialog.show_error("Müşteri geri açılamadı. Lütfen yeniden deneyin.")
                return

            self.refresh_customer_summaries()
            try:
                dialog.set_customers(self._load_archived_customers())
            except Exception as error:
                _log_failure("Archived customers could not be refreshed", error)
                dialog.show_error("Arşivlenmiş müşteri listesi yenilenemedi.")

        dialog.unarchive_requested.connect(unarchive_customer)
        dialog.exec()
        dialog.unarchive_requested.disconnect(unarchive_customer)
        dialog.deleteLater()

    def _load_archived_customers(self) -> list[ArchivedCustomer]:
        with self._application_context.services() as services:
            return list(services.customer.list_archived_customers())

    def _show_customer_operation_error(self, message: str) -> None:
        QMessageBox.warning(self, "İşlem Tamamlanamadı", message)

    def _show_customer_load_error(self) -> None:
        self._customer_summaries_by_id = {}
        self.customer_list.clear()
        self.customer_count_label.setText("Bulunan: -")
        self.customer_list_stack.setCurrentWidget(self.customer_error_state)
        self._show_no_customer_selected()
