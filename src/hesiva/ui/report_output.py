import html
import os
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QDialog, QWidget
from shiboken6 import delete as delete_qt_object

from hesiva.database.durability import sync_file, sync_parent_directory
from hesiva.read_models import CustomerStatement, MonthlySummary, YearlySummary
from hesiva.ui.presentation import (
    TURKISH_MONTH_NAMES,
    format_balance_kurus,
    format_date,
    format_money_kurus,
    format_signed_money_kurus,
)

ReportData = CustomerStatement | MonthlySummary | YearlySummary


class ReportOutputError(Exception):
    """Raised when a local report cannot be rendered or published safely."""


REPORT_STYLESHEET = """
body {
    color: #1f2933;
    font-family: sans-serif;
    font-size: 9pt;
    line-height: 1.3;
}
h1 {
    color: #234f7d;
    font-size: 18pt;
    margin: 0 0 2pt 0;
}
h2 {
    font-size: 13pt;
    margin: 0 0 10pt 0;
}
.meta {
    margin-bottom: 10pt;
}
.totals {
    border-collapse: collapse;
    margin: 8pt 0 12pt 0;
    width: 100%;
}
.totals td {
    border: 1px solid #aeb8c2;
    padding: 7pt;
    width: 33%;
}
.caption {
    color: #566371;
    font-size: 8pt;
    font-weight: bold;
}
.value {
    font-size: 11pt;
    font-weight: bold;
}
.report-table {
    border-collapse: collapse;
    width: 100%;
}
.report-table th {
    background-color: #e5e9ed;
    border: 1px solid #9aa6b2;
    font-weight: bold;
    padding: 5pt;
    text-align: left;
}
.report-table td {
    border: 1px solid #c5ccd3;
    padding: 4pt 5pt;
    vertical-align: top;
}
.number {
    text-align: right;
    white-space: normal;
    font-size: 8pt;
}
.description {
    white-space: normal;
}
.empty {
    color: #65717d;
    margin: 16pt 0;
    text-align: center;
}
"""


def build_report_document(report: ReportData) -> QTextDocument:
    """Build one searchable Qt document used unchanged by PDF and print outputs."""
    document = QTextDocument()
    font = QFont()
    font.setPointSize(9)
    document.setDefaultFont(font)
    document.setDocumentMargin(0)
    document.setDefaultStyleSheet(REPORT_STYLESHEET)
    document.setHtml(build_report_html(report))
    return document


def build_report_html(report: ReportData) -> str:
    """Build controlled report markup with every user-supplied value escaped."""
    if isinstance(report, CustomerStatement):
        body = _customer_statement_html(report)
    elif isinstance(report, MonthlySummary):
        body = _monthly_summary_html(report)
    elif isinstance(report, YearlySummary):
        body = _yearly_summary_html(report)
    else:
        raise TypeError(f"Unsupported report type: {type(report)!r}")
    return f"<html><head><meta charset='utf-8'></head><body>{body}</body></html>"


def write_report_pdf(report: ReportData, output_path: Path) -> Path:
    """Render to a same-directory temporary PDF, validate it, then publish atomically."""
    target = ensure_pdf_extension(output_path)
    if not target.parent.is_dir():
        raise ReportOutputError("The selected report directory is unavailable.")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}-",
        suffix=".tmp.pdf",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        _render_pdf_to_path(report, temporary_path)
        sync_file(temporary_path)
        if not _is_complete_pdf(temporary_path):
            raise ReportOutputError("The PDF output was not completed.")
        os.replace(temporary_path, target)
        sync_parent_directory(target)
    except ReportOutputError as error:
        _remove_temporary_pdf(temporary_path, primary_error=error)
        raise
    except Exception as error:
        report_error = ReportOutputError("The PDF output could not be written.")
        _remove_temporary_pdf(temporary_path, primary_error=report_error)
        raise report_error from error
    return target


def print_report(report: ReportData, parent: QWidget | None = None) -> bool:
    """Show the native Qt print dialog and print the shared report document if accepted."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dialog: QPrintDialog | None = None
    primary_error: BaseException | None = None
    try:
        _configure_a4_printer(printer)
        printer.setDocName(_report_title(report))
        dialog = QPrintDialog(printer, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        _render_to_printer(report, printer)
        if printer.printerState() in {
            QPrinter.PrinterState.Aborted,
            QPrinter.PrinterState.Error,
        }:
            raise ReportOutputError("The printer did not complete the output.")
        return True
    except ReportOutputError as error:
        primary_error = error
        raise
    except Exception as error:
        output_error = ReportOutputError("The report could not be printed.")
        primary_error = output_error
        raise output_error from error
    finally:
        for qt_object, description in (
            (dialog, "print dialog"),
            (printer, "printer output device"),
        ):
            if qt_object is None:
                continue
            try:
                delete_qt_object(qt_object)
            except Exception as cleanup_error:
                if primary_error is not None:
                    primary_error.add_note(
                        f"The Qt {description} could not be released cleanly: "
                        f"{type(cleanup_error).__name__}."
                    )
                    continue
                raise ReportOutputError(
                    f"The Qt {description} could not be released cleanly."
                ) from cleanup_error


def ensure_pdf_extension(path: Path) -> Path:
    """Keep the chosen path and append the required PDF extension when absent."""
    if path.suffix.lower() == ".pdf":
        return path
    return Path(f"{path}.pdf")


def sanitize_filename_component(value: str) -> str:
    """Create one portable filename component without permitting path traversal."""
    sanitized = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value)
    sanitized = sanitized.replace("&", "_")
    sanitized = re.sub(r"\s+", "_", sanitized).strip(" ._")
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized[:80].rstrip(" ._") or "Musteri"


def suggested_pdf_filename(report: ReportData) -> str:
    """Return a deterministic, portable suggestion derived only from report metadata."""
    if isinstance(report, CustomerStatement):
        customer = sanitize_filename_component(report.full_name)
        return (
            f"Hesiva_Ekstre_{customer}_"
            f"{report.period_start:%Y-%m-%d}_{report.period_end:%Y-%m-%d}.pdf"
        )
    if isinstance(report, MonthlySummary):
        return f"Hesiva_Aylik_Ozet_{report.year:04d}-{report.month:02d}.pdf"
    if isinstance(report, YearlySummary):
        return f"Hesiva_Yillik_Ozet_{report.year:04d}.pdf"
    raise TypeError(f"Unsupported report type: {type(report)!r}")


def _render_to_printer(report: ReportData, printer: QPrinter) -> None:
    document = build_report_document(report)
    document.print_(printer)


def _render_pdf_to_path(report: ReportData, path: Path) -> None:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    primary_error: BaseException | None = None
    try:
        _configure_a4_printer(printer)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(path))
        printer.setDocName(_report_title(report))
        _render_to_printer(report, printer)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            delete_qt_object(printer)
        except Exception as cleanup_error:
            if primary_error is None:
                raise
            primary_error.add_note(
                "The Qt PDF output device could not be released cleanly: "
                f"{type(cleanup_error).__name__}."
            )


def _configure_a4_printer(printer: QPrinter) -> None:
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Unit.Millimeter)
    printer.setFullPage(False)


def _customer_statement_html(report: CustomerStatement) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_escape(format_date(row.transaction_date))}</td>"
        f"<td class='description'>{_escape(row.description)}</td>"
        f"<td class='number'>{_escape(format_money_kurus(row.amount_kurus)) if row.amount_kurus > 0 else ''}</td>"
        f"<td class='number'>{_escape(format_money_kurus(-row.amount_kurus)) if row.amount_kurus < 0 else ''}</td>"
        f"<td class='number'>{_escape(format_balance_kurus(row.running_balance_kurus))}</td>"
        "</tr>"
        for row in report.rows
    )
    table = (
        "<p class='empty'>Seçilen tarih aralığında hesap hareketi bulunmuyor.</p>"
        if not rows
        else (
            "<table class='report-table'>"
            "<thead><tr>"
            "<th width='13%'>Tarih</th><th width='31%'>Açıklama</th>"
            "<th width='17%'>Borç</th><th width='17%'>Ödeme</th><th width='22%'>Bakiye</th>"
            "</tr></thead><tbody>"
            f"{rows}</tbody></table>"
        )
    )
    return (
        "<h1>Hesiva</h1><h2>Müşteri Hesap Özeti - Ekstre</h2>"
        "<div class='meta'>"
        f"<b>Müşteri:</b> {_escape(report.full_name)}<br>"
        f"<b>Telefon:</b> {_escape(report.phone or '-')}<br>"
        f"<b>Tarih Aralığı:</b> {_escape(format_date(report.period_start))} – "
        f"{_escape(format_date(report.period_end))}"
        "</div>"
        + _totals_html(
            ("Toplam Borç", format_money_kurus(report.total_debt_kurus)),
            ("Toplam Ödeme", format_money_kurus(report.total_payment_kurus)),
            ("Güncel Bakiye", format_balance_kurus(report.current_balance_kurus)),
        )
        + table
    )


def _monthly_summary_html(report: MonthlySummary) -> str:
    period = f"{TURKISH_MONTH_NAMES[report.month - 1]} {report.year}"
    return (
        "<h1>Hesiva</h1><h2>Aylık Özet</h2>"
        f"<div class='meta'><b>Dönem:</b> {_escape(period)}</div>"
        + _totals_html(
            ("Oluşan Yeni Borç", format_money_kurus(report.debt_kurus)),
            ("Alınan Toplam Ödeme", format_money_kurus(report.payment_kurus)),
            ("Net Aylık Hareket", format_signed_money_kurus(report.net_kurus)),
        )
    )


def _yearly_summary_html(report: YearlySummary) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_escape(TURKISH_MONTH_NAMES[month.month - 1])}</td>"
        f"<td class='number'>{_escape(format_money_kurus(month.debt_kurus))}</td>"
        f"<td class='number'>{_escape(format_money_kurus(month.payment_kurus))}</td>"
        f"<td class='number'>{_escape(format_signed_money_kurus(month.net_kurus))}</td>"
        "</tr>"
        for month in report.months
    )
    return (
        "<h1>Hesiva</h1><h2>Yıllık Özet</h2>"
        f"<div class='meta'><b>İnceleme Yılı:</b> {report.year}</div>"
        + _totals_html(
            ("Yıllık Oluşan Borç", format_money_kurus(report.debt_kurus)),
            ("Alınan Toplam Ödeme", format_money_kurus(report.payment_kurus)),
            ("Net Fark Hareketi", format_signed_money_kurus(report.net_kurus)),
        )
        + "<table class='report-table'><thead><tr>"
        "<th width='31%'>Ay</th><th width='23%'>Borç</th>"
        "<th width='23%'>Ödeme</th><th width='23%'>Net Fark</th>"
        "</tr></thead><tbody>"
        f"{rows}</tbody></table>"
    )


def _totals_html(*values: tuple[str, str]) -> str:
    cells = "".join(
        "<td>"
        f"<div class='caption'>{_escape(caption)}</div>"
        f"<div class='value'>{_escape(value)}</div>"
        "</td>"
        for caption, value in values
    )
    return f"<table class='totals'><tr>{cells}</tr></table>"


def _report_title(report: ReportData) -> str:
    if isinstance(report, CustomerStatement):
        return "Hesiva - Müşteri Hesap Özeti"
    if isinstance(report, MonthlySummary):
        return "Hesiva - Aylık Özet"
    if isinstance(report, YearlySummary):
        return "Hesiva - Yıllık Özet"
    raise TypeError(f"Unsupported report type: {type(report)!r}")


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _is_complete_pdf(path: Path) -> bool:
    document: QPdfDocument | None = None
    try:
        if path.stat().st_size < 8:
            return False
        document = QPdfDocument()
        return document.load(str(path)) == QPdfDocument.Error.None_ and document.pageCount() > 0
    except (OSError, RuntimeError):
        return False
    finally:
        if document is not None:
            document.close()


def _remove_temporary_pdf(path: Path, *, primary_error: BaseException) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as cleanup_error:
        primary_error.add_note(
            f"The incomplete temporary PDF could not be removed: {type(cleanup_error).__name__}."
        )
