import logging
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hesiva.composition import ApplicationContext
from hesiva.read_models import CustomerStatement, MonthlySummary, YearlySummary
from hesiva.services import ServiceError, ValidationError
from hesiva.ui import report_output
from hesiva.ui.presentation import (
    TURKISH_MONTH_NAMES,
    format_balance_kurus,
    format_date,
    format_money_kurus,
    format_signed_money_kurus,
)

LOGGER = logging.getLogger(__name__)


def _to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def _money_item(value: str) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _configure_report_table(table: QTableWidget) -> None:
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.horizontalHeader().setStretchLastSection(False)


def _create_value_card(caption: str, object_name: str) -> tuple[QFrame, QLabel]:
    card = QFrame()
    card.setProperty("detailPanel", True)
    caption_label = QLabel(caption, card)
    caption_label.setProperty("detailCaption", True)
    value_label = QLabel("0,00 TL", card)
    value_label.setObjectName(object_name)
    value_label.setProperty("financialValue", True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 9, 12, 9)
    layout.setSpacing(3)
    layout.addWidget(caption_label)
    layout.addWidget(value_label)
    return card, value_label


def _create_close_footer(
    dialog: QDialog,
) -> tuple[QHBoxLayout, QPushButton, QPushButton]:
    footer = QHBoxLayout()
    footer.addStretch()
    print_button = QPushButton("Yazdır", dialog)
    print_button.setObjectName("reportPrintButton")
    print_button.setEnabled(False)
    footer.addWidget(print_button)
    pdf_button = QPushButton("PDF Olarak Kaydet", dialog)
    pdf_button.setObjectName("reportPdfButton")
    pdf_button.setEnabled(False)
    footer.addWidget(pdf_button)
    close_button = QPushButton("Kapat", dialog)
    close_button.setObjectName("reportCloseButton")
    close_button.setProperty("primary", True)
    close_button.clicked.connect(dialog.accept)
    footer.addWidget(close_button)
    return footer, print_button, pdf_button


def _save_report(parent: QDialog, report: report_output.ReportData) -> None:
    selected_path, _selected_filter = QFileDialog.getSaveFileName(
        parent,
        "PDF Olarak Kaydet",
        report_output.suggested_pdf_filename(report),
        "PDF Dosyaları (*.pdf)",
    )
    if not selected_path:
        return
    try:
        report_output.write_report_pdf(report, Path(selected_path))
    except report_output.ReportOutputError:
        LOGGER.exception("Report PDF output failed")
        QMessageBox.warning(
            parent,
            "PDF Kaydedilemedi",
            "PDF dosyası kaydedilemedi. Lütfen konumu kontrol edip yeniden deneyin.",
        )


def _print_report(parent: QDialog, report: report_output.ReportData) -> None:
    try:
        report_output.print_report(report, parent)
    except report_output.ReportOutputError:
        LOGGER.exception("Report print output failed")
        QMessageBox.warning(
            parent,
            "Yazdırma Başarısız",
            "Rapor yazdırılamadı. Lütfen yazıcı ayarlarını kontrol edin.",
        )


class CustomerStatementDialog(QDialog):
    """Read-only, date-ranged statement for the selected active customer."""

    def __init__(
        self,
        application_context: ApplicationContext,
        customer_id: int,
        parent: QWidget | None = None,
        *,
        reference_date: date | None = None,
    ) -> None:
        super().__init__(parent)
        self._application_context = application_context
        self._customer_id = customer_id
        self.statement: CustomerStatement | None = None
        today = reference_date or date.today()
        self.setObjectName("customerStatementDialog")
        self.setWindowTitle("Müşteri Hesap Özeti - Ekstre")
        self.resize(980, 620)
        self.setMinimumSize(760, 480)

        self.customer_name_label = QLabel("-", self)
        self.customer_name_label.setObjectName("statementCustomerName")
        self.customer_name_label.setProperty("dialogHeading", True)
        self.customer_phone_label = QLabel("Telefon: -", self)
        self.customer_phone_label.setObjectName("statementCustomerPhone")

        customer_panel = QFrame(self)
        customer_panel.setProperty("detailPanel", True)
        customer_layout = QVBoxLayout(customer_panel)
        customer_layout.addWidget(QLabel("MÜŞTERİ DETAYLARI", customer_panel))
        customer_layout.addWidget(self.customer_name_label)
        customer_layout.addWidget(self.customer_phone_label)

        self.period_start_input = QDateEdit(_to_qdate(date(today.year, 1, 1)), self)
        self.period_start_input.setObjectName("statementPeriodStart")
        self.period_start_input.setCalendarPopup(True)
        self.period_start_input.setDisplayFormat("dd.MM.yyyy")
        self.period_end_input = QDateEdit(_to_qdate(today), self)
        self.period_end_input.setObjectName("statementPeriodEnd")
        self.period_end_input.setCalendarPopup(True)
        self.period_end_input.setDisplayFormat("dd.MM.yyyy")
        period_panel = QFrame(self)
        period_panel.setProperty("detailPanel", True)
        period_layout = QGridLayout(period_panel)
        period_layout.addWidget(QLabel("TARİH ARALIĞI FİLTRESİ", period_panel), 0, 0, 1, 4)
        period_layout.addWidget(QLabel("Başlangıç:", period_panel), 1, 0)
        period_layout.addWidget(self.period_start_input, 1, 1)
        period_layout.addWidget(QLabel("Bitiş:", period_panel), 1, 2)
        period_layout.addWidget(self.period_end_input, 1, 3)

        heading = QHBoxLayout()
        heading.addWidget(customer_panel, 1)
        heading.addWidget(period_panel, 1)

        debt_card, self.total_debt_label = _create_value_card("TOPLAM BORÇ", "statementTotalDebt")
        payment_card, self.total_payment_label = _create_value_card(
            "TOPLAM ÖDEME", "statementTotalPayment"
        )
        balance_card, self.current_balance_label = _create_value_card(
            "Güncel Bakiye", "statementCurrentBalance"
        )
        totals = QHBoxLayout()
        totals.addWidget(debt_card)
        totals.addWidget(payment_card)
        totals.addWidget(balance_card)

        self.table = QTableWidget(0, 5, self)
        self.table.setObjectName("statementTable")
        self.table.setHorizontalHeaderLabels(("Tarih", "Açıklama", "Borç", "Ödeme", "Bakiye"))
        _configure_report_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )

        self.state_label = QLabel("", self)
        self.state_label.setObjectName("statementStateLabel")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setWordWrap(True)
        self.state_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.addLayout(heading)
        layout.addLayout(totals)
        layout.addWidget(self.state_label)
        layout.addWidget(self.table, 1)
        footer, self.print_button, self.pdf_button = _create_close_footer(self)
        layout.addLayout(footer)

        self.period_start_input.editingFinished.connect(self.refresh_statement)
        self.period_end_input.editingFinished.connect(self.refresh_statement)
        self.print_button.clicked.connect(self._print_current_report)
        self.pdf_button.clicked.connect(self._save_current_report)
        self.refresh_statement()

    def refresh_statement(self) -> None:
        self.statement = None
        self._set_output_enabled(False)
        period_start = self.period_start_input.date().toPython()
        period_end = self.period_end_input.date().toPython()
        if period_start > period_end:
            self._show_error("Başlangıç tarihi bitiş tarihinden sonra olamaz.")
            return
        try:
            with self._application_context.services() as services:
                statement = services.report.get_customer_statement(
                    self._customer_id,
                    period_start=period_start,
                    period_end=period_end,
                )
        except (ServiceError, ValidationError):
            self._show_error("Hesap özeti yüklenemedi. Lütfen yeniden deneyin.")
            return
        except Exception:
            LOGGER.exception("Customer statement could not be loaded")
            self._show_error("Hesap özeti yüklenemedi. Lütfen yeniden deneyin.")
            return
        self.statement = statement
        self._populate(statement)

    def _populate(self, statement: CustomerStatement) -> None:
        self.customer_name_label.setText(statement.full_name)
        self.customer_phone_label.setText(f"Telefon: {statement.phone or '-'}")
        self.total_debt_label.setText(format_money_kurus(statement.total_debt_kurus))
        self.total_payment_label.setText(format_money_kurus(statement.total_payment_kurus))
        self.current_balance_label.setText(format_balance_kurus(statement.current_balance_kurus))
        self.table.setRowCount(len(statement.rows))
        for row_index, row in enumerate(statement.rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(format_date(row.transaction_date)))
            self.table.setItem(row_index, 1, QTableWidgetItem(row.description))
            self.table.setItem(
                row_index,
                2,
                _money_item(format_money_kurus(row.amount_kurus) if row.amount_kurus > 0 else ""),
            )
            self.table.setItem(
                row_index,
                3,
                _money_item(format_money_kurus(-row.amount_kurus) if row.amount_kurus < 0 else ""),
            )
            self.table.setItem(
                row_index,
                4,
                _money_item(format_balance_kurus(row.running_balance_kurus)),
            )
        if statement.rows:
            self.state_label.hide()
            self.table.show()
        else:
            self.state_label.setProperty("errorMessage", False)
            self.state_label.setText("Seçilen tarih aralığında hesap hareketi bulunmuyor.")
            self.state_label.show()
            self.table.hide()
        self._set_output_enabled(True)

    def _show_error(self, message: str) -> None:
        self.statement = None
        self.table.hide()
        self.state_label.setProperty("errorMessage", True)
        self.state_label.setText(message)
        self.state_label.show()
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)

    def _save_current_report(self) -> None:
        if self.statement is not None:
            _save_report(self, self.statement)

    def _print_current_report(self) -> None:
        if self.statement is not None:
            _print_report(self, self.statement)

    def _set_output_enabled(self, enabled: bool) -> None:
        self.print_button.setEnabled(enabled)
        self.pdf_button.setEnabled(enabled)


class MonthlySummaryDialog(QDialog):
    """Read-only application-wide totals for one calendar month."""

    def __init__(
        self,
        application_context: ApplicationContext,
        parent: QWidget | None = None,
        *,
        reference_date: date | None = None,
    ) -> None:
        super().__init__(parent)
        self._application_context = application_context
        self.summary: MonthlySummary | None = None
        today = reference_date or date.today()
        self.setObjectName("monthlySummaryDialog")
        self.setWindowTitle("Aylık Özet")
        self.resize(720, 360)

        self.year_input = QSpinBox(self)
        self.year_input.setObjectName("monthlyYear")
        self.year_input.setRange(1, 9998)
        self.year_input.setValue(today.year)
        self.month_input = QComboBox(self)
        self.month_input.setObjectName("monthlyMonth")
        for month, name in enumerate(TURKISH_MONTH_NAMES, start=1):
            self.month_input.addItem(name, month)
        self.month_input.setCurrentIndex(today.month - 1)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Yıl Seçimi:", self))
        filters.addWidget(self.year_input)
        filters.addSpacing(16)
        filters.addWidget(QLabel("Ay Seçimi:", self))
        filters.addWidget(self.month_input)
        filters.addStretch()

        debt_card, self.debt_label = _create_value_card("OLUŞAN YENİ BORÇ", "monthlyDebt")
        payment_card, self.payment_label = _create_value_card(
            "ALINAN TOPLAM ÖDEME", "monthlyPayment"
        )
        net_card, self.net_label = _create_value_card("NET AYLIK HAREKET", "monthlyNet")
        totals = QHBoxLayout()
        totals.addWidget(debt_card)
        totals.addWidget(payment_card)
        totals.addWidget(net_card)

        self.state_label = QLabel("", self)
        self.state_label.setObjectName("monthlySummaryState")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.addLayout(filters)
        layout.addLayout(totals)
        layout.addWidget(self.state_label)
        layout.addStretch()
        footer, self.print_button, self.pdf_button = _create_close_footer(self)
        layout.addLayout(footer)

        self.year_input.valueChanged.connect(self.refresh_summary)
        self.month_input.currentIndexChanged.connect(self.refresh_summary)
        self.print_button.clicked.connect(self._print_current_report)
        self.pdf_button.clicked.connect(self._save_current_report)
        self.refresh_summary()

    def refresh_summary(self) -> None:
        self.summary = None
        self._set_output_enabled(False)
        try:
            with self._application_context.services() as services:
                summary = services.report.get_monthly_summary(
                    year=self.year_input.value(),
                    month=int(self.month_input.currentData()),
                )
        except Exception:
            LOGGER.exception("Monthly summary could not be loaded")
            self.summary = None
            self.state_label.setProperty("errorMessage", True)
            self.state_label.setText("Aylık özet yüklenemedi. Lütfen yeniden deneyin.")
            return
        self.summary = summary
        self.debt_label.setText(format_money_kurus(summary.debt_kurus))
        self.payment_label.setText(format_money_kurus(summary.payment_kurus))
        self.net_label.setText(format_signed_money_kurus(summary.net_kurus))
        self.state_label.setProperty("errorMessage", False)
        self.state_label.setText(
            "Seçilen ayda finansal hareket bulunmuyor."
            if summary.debt_kurus == summary.payment_kurus == 0
            else ""
        )
        self._set_output_enabled(True)

    def _save_current_report(self) -> None:
        if self.summary is not None:
            _save_report(self, self.summary)

    def _print_current_report(self) -> None:
        if self.summary is not None:
            _print_report(self, self.summary)

    def _set_output_enabled(self, enabled: bool) -> None:
        self.print_button.setEnabled(enabled)
        self.pdf_button.setEnabled(enabled)


class YearlySummaryDialog(QDialog):
    """Read-only application-wide yearly totals and monthly breakdown."""

    def __init__(
        self,
        application_context: ApplicationContext,
        parent: QWidget | None = None,
        *,
        reference_date: date | None = None,
    ) -> None:
        super().__init__(parent)
        self._application_context = application_context
        self.summary: YearlySummary | None = None
        today = reference_date or date.today()
        self.setObjectName("yearlySummaryDialog")
        self.setWindowTitle("Yıllık Özet")
        self.resize(850, 620)

        self.year_input = QSpinBox(self)
        self.year_input.setObjectName("yearlyYear")
        self.year_input.setRange(1, 9998)
        self.year_input.setValue(today.year)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("İnceleme Yılı:", self))
        filters.addWidget(self.year_input)
        filters.addStretch()

        debt_card, self.debt_label = _create_value_card("YILLIK OLUŞAN BORÇ", "yearlyDebt")
        payment_card, self.payment_label = _create_value_card(
            "ALINAN TOPLAM ÖDEME", "yearlyPayment"
        )
        net_card, self.net_label = _create_value_card("NET FARK HAREKETİ", "yearlyNet")
        totals = QHBoxLayout()
        totals.addWidget(debt_card)
        totals.addWidget(payment_card)
        totals.addWidget(net_card)

        self.table = QTableWidget(12, 4, self)
        self.table.setObjectName("yearlySummaryTable")
        self.table.setHorizontalHeaderLabels(("Ay", "Borç", "Ödeme", "Net Fark"))
        _configure_report_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )

        self.state_label = QLabel("", self)
        self.state_label.setObjectName("yearlySummaryState")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.addLayout(filters)
        layout.addLayout(totals)
        layout.addWidget(self.state_label)
        layout.addWidget(self.table, 1)
        footer, self.print_button, self.pdf_button = _create_close_footer(self)
        layout.addLayout(footer)

        self.year_input.valueChanged.connect(self.refresh_summary)
        self.print_button.clicked.connect(self._print_current_report)
        self.pdf_button.clicked.connect(self._save_current_report)
        self.refresh_summary()

    def refresh_summary(self) -> None:
        self.summary = None
        self._set_output_enabled(False)
        try:
            with self._application_context.services() as services:
                summary = services.report.get_yearly_summary(year=self.year_input.value())
        except Exception:
            LOGGER.exception("Yearly summary could not be loaded")
            self.summary = None
            self.table.hide()
            self.state_label.setProperty("errorMessage", True)
            self.state_label.setText("Yıllık özet yüklenemedi. Lütfen yeniden deneyin.")
            return
        self.summary = summary
        self.debt_label.setText(format_money_kurus(summary.debt_kurus))
        self.payment_label.setText(format_money_kurus(summary.payment_kurus))
        self.net_label.setText(format_signed_money_kurus(summary.net_kurus))
        self.table.setRowCount(12)
        for row_index, month in enumerate(summary.months):
            self.table.setItem(
                row_index,
                0,
                QTableWidgetItem(TURKISH_MONTH_NAMES[month.month - 1]),
            )
            self.table.setItem(row_index, 1, _money_item(format_money_kurus(month.debt_kurus)))
            self.table.setItem(row_index, 2, _money_item(format_money_kurus(month.payment_kurus)))
            self.table.setItem(
                row_index, 3, _money_item(format_signed_money_kurus(month.net_kurus))
            )
        self.table.show()
        self.state_label.setProperty("errorMessage", False)
        self.state_label.setText(
            "Seçilen yılda finansal hareket bulunmuyor."
            if summary.debt_kurus == summary.payment_kurus == 0
            else ""
        )
        self._set_output_enabled(True)

    def _save_current_report(self) -> None:
        if self.summary is not None:
            _save_report(self, self.summary)

    def _print_current_report(self) -> None:
        if self.summary is not None:
            _print_report(self, self.summary)

    def _set_output_enabled(self, enabled: bool) -> None:
        self.print_button.setEnabled(enabled)
        self.pdf_button.setEnabled(enabled)
