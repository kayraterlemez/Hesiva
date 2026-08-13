import os
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtPdf import QPdfDocument  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from hesiva.read_models import (  # noqa: E402
    CustomerStatement,
    MonthlySummary,
    StatementRow,
    YearlyMonthSummary,
    YearlySummary,
)
from hesiva.ui import report_output  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing_application = QApplication.instance()
    if existing_application is not None:
        assert isinstance(existing_application, QApplication)
        return existing_application
    return QApplication([])


def statement_report(*, row_count: int = 2) -> CustomerStatement:
    rows = tuple(
        StatementRow(
            transaction_id=index,
            transaction_date=date(2026, 8, (index - 1) % 28 + 1),
            transaction_time=None,
            description=(
                f'Satır {index:03d}: Çç Ğğ İı Öö Şş Üü <İlaç> & "Kontrol" — A > B '
                + "uzun açıklama " * 4
            ),
            amount_kurus=125_050 if index % 2 else -25_000,
            running_balance_kurus=125_050 - (index - 1) * 25_000,
        )
        for index in range(1, row_count + 1)
    )
    return CustomerStatement(
        customer_id=1,
        full_name='Ali & Veli <Çiftliği> "Özel"',
        phone="0532 111 22 33",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 8, 31),
        opening_balance_kurus=100_000,
        total_debt_kurus=250_100,
        total_payment_kurus=25_000,
        current_balance_kurus=-100_000,
        rows=rows,
    )


def monthly_report() -> MonthlySummary:
    return MonthlySummary(
        year=2026,
        month=8,
        debt_kurus=425_000,
        payment_kurus=510_000,
        net_kurus=-85_000,
    )


def yearly_report() -> YearlySummary:
    months = tuple(
        YearlyMonthSummary(
            month=month,
            debt_kurus=month * 10_000,
            payment_kurus=month * 8_000,
            net_kurus=month * 2_000,
        )
        for month in range(1, 13)
    )
    return YearlySummary(
        year=2026,
        debt_kurus=sum(row.debt_kurus for row in months),
        payment_kurus=sum(row.payment_kurus for row in months),
        net_kurus=sum(row.net_kurus for row in months),
        months=months,
    )


def pdf_text(path: Path) -> tuple[int, str]:
    document = QPdfDocument()
    try:
        assert document.load(str(path)) == QPdfDocument.Error.None_
        return document.pageCount(), "\n".join(
            document.getAllText(page).text() for page in range(document.pageCount())
        )
    finally:
        document.close()


def test_statement_document_contains_authoritative_content_and_escaped_user_text(
    application: QApplication,
) -> None:
    report = statement_report()
    html = report_output.build_report_html(report)
    plain_text = report_output.build_report_document(report).toPlainText()

    assert "Müşteri Hesap Özeti - Ekstre" in plain_text
    assert 'Ali & Veli <Çiftliği> "Özel"' in plain_text
    assert 'Çç Ğğ İı Öö Şş Üü <İlaç> & "Kontrol" — A > B' in plain_text
    assert "01.01.2026" in plain_text and "31.08.2026" in plain_text
    assert "2.501,00 TL" in plain_text
    assert "250,00 TL" in plain_text
    assert "1.000,00 TL Fazla Ödeme" in plain_text
    assert "1.250,50 TL Borç" in plain_text
    assert "Alacak" not in plain_text
    assert "Ali &amp; Veli &lt;Çiftliği&gt; &quot;Özel&quot;" in html
    assert "Çç Ğğ İı Öö Şş Üü &lt;İlaç&gt; &amp; &quot;Kontrol&quot; — A &gt; B" in html


def test_monthly_and_yearly_documents_match_existing_report_values(
    application: QApplication,
) -> None:
    monthly_text = report_output.build_report_document(monthly_report()).toPlainText()
    yearly_text = report_output.build_report_document(yearly_report()).toPlainText()

    assert "Ağustos 2026" in monthly_text
    assert "4.250,00 TL" in monthly_text
    assert "5.100,00 TL" in monthly_text
    assert "-850,00 TL" in monthly_text
    assert "Yıllık Özet" in yearly_text
    assert "İnceleme Yılı: 2026" in yearly_text
    assert all(month in yearly_text for month in ("Ocak", "Şubat", "Aralık"))
    assert yearly_text.count("Net Fark") >= 1


@pytest.mark.parametrize(
    ("report", "filename"),
    (
        (monthly_report(), "Hesiva_Aylik_Ozet_2026-08.pdf"),
        (yearly_report(), "Hesiva_Yillik_Ozet_2026.pdf"),
    ),
)
def test_report_filenames_are_deterministic(
    report: MonthlySummary | YearlySummary,
    filename: str,
) -> None:
    assert report_output.suggested_pdf_filename(report) == filename


def test_statement_filename_is_portable_and_cannot_create_a_path() -> None:
    report = statement_report()
    filename = report_output.suggested_pdf_filename(report)

    assert filename.startswith("Hesiva_Ekstre_Ali_Veli_Çiftliği_Özel_")
    assert filename.endswith("_2026-01-01_2026-08-31.pdf")
    assert not any(character in filename for character in '<>:"/\\|?*')
    assert report_output.ensure_pdf_extension(Path("rapor")) == Path("rapor.pdf")
    assert report_output.ensure_pdf_extension(Path("rapor.PDF")) == Path("rapor.PDF")


@pytest.mark.parametrize(
    "report",
    (statement_report(), monthly_report(), yearly_report()),
)
def test_all_report_types_generate_valid_searchable_pdfs(
    application: QApplication,
    tmp_path: Path,
    report: CustomerStatement | MonthlySummary | YearlySummary,
) -> None:
    output = report_output.write_report_pdf(report, tmp_path / "report.pdf")

    assert output.exists()
    assert output.stat().st_size > 1_000
    assert output.read_bytes().startswith(b"%PDF-")
    page_count, text = pdf_text(output)
    assert page_count >= 1
    assert "Hesiva" in text


def test_generated_pdf_uses_portrait_a4_page_size(
    application: QApplication,
    tmp_path: Path,
) -> None:
    output = report_output.write_report_pdf(monthly_report(), tmp_path / "a4.pdf")
    document = QPdfDocument()
    try:
        assert document.load(str(output)) == QPdfDocument.Error.None_
        page_size = document.pagePointSize(0)
    finally:
        document.close()

    assert 590 <= page_size.width() <= 600
    assert 840 <= page_size.height() <= 845
    assert page_size.height() > page_size.width()


def test_empty_statement_generates_a_valid_pdf(application: QApplication, tmp_path: Path) -> None:
    empty = CustomerStatement(
        customer_id=1,
        full_name="Boş Müşteri",
        phone=None,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance_kurus=0,
        total_debt_kurus=0,
        total_payment_kurus=0,
        current_balance_kurus=0,
        rows=(),
    )

    output = report_output.write_report_pdf(empty, tmp_path / "empty.pdf")
    page_count, text = pdf_text(output)

    assert page_count == 1
    assert "hesap hareketi bulunmuyor" in text
    assert "0,00 TL" in text


def test_long_statement_paginates_without_losing_or_duplicating_rows(
    application: QApplication,
    tmp_path: Path,
) -> None:
    report = statement_report(row_count=140)
    # Keep each row shorter than a page boundary here so PDF text extraction can
    # unambiguously prove row cardinality. Long-cell wrapping is exercised by
    # the Unicode/special-character statement and visual render checks.
    report = replace(
        report,
        rows=tuple(
            replace(row, description=f"Satır {row.transaction_id:03d}") for row in report.rows
        ),
    )
    output = report_output.write_report_pdf(report, tmp_path / "long.pdf")
    page_count, text = pdf_text(output)
    source_text = report_output.build_report_document(report).toPlainText()

    assert page_count > 1
    for index in range(1, 141):
        row_label = f"Satır {index:03d}"
        assert source_text.count(row_label) == 1
        assert text.count(row_label) == 1
    assert text.count("Tarih") >= page_count


def test_maximum_supported_money_remains_readable_in_statement_pdf(
    application: QApplication,
    tmp_path: Path,
) -> None:
    maximum_kurus = (1 << 63) - 1
    report = replace(
        statement_report(row_count=1),
        total_debt_kurus=maximum_kurus,
        total_payment_kurus=0,
        current_balance_kurus=maximum_kurus,
        rows=(
            replace(
                statement_report(row_count=1).rows[0],
                amount_kurus=maximum_kurus,
                running_balance_kurus=maximum_kurus,
            ),
        ),
    )

    output = report_output.write_report_pdf(report, tmp_path / "maximum-money.pdf")
    _page_count, text = pdf_text(output)
    compact_text = re.sub(r"\s+", "", text)

    formatted = "92.233.720.368.547.758,07TL"
    assert compact_text.count(formatted) >= 3
    assert f"{formatted}Borç" in compact_text
    assert "Ödeme" in text


def test_pdf_preserves_turkish_and_special_characters(
    application: QApplication,
    tmp_path: Path,
) -> None:
    output = report_output.write_report_pdf(statement_report(), tmp_path / "unicode.pdf")
    _page_count, text = pdf_text(output)
    normalized_text = re.sub(r"\s+", " ", text)

    assert 'Ali & Veli <Çiftliği> "Özel"' in normalized_text
    assert 'Çç Ğğ İı Öö Şş Üü <İlaç> & "Kontrol" — A > B' in normalized_text
    assert all(character in normalized_text for character in "ÇçĞğİıÖöŞşÜü")


def test_pdf_failure_does_not_publish_target_or_leave_temporary_file(
    application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_render(_report: object, _printer: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(report_output, "_render_to_printer", fail_render)
    target = tmp_path / "failed.pdf"

    with pytest.raises(report_output.ReportOutputError):
        report_output.write_report_pdf(monthly_report(), target)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_pdf_printer_is_released_before_validation_and_publication(
    application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    real_printer = report_output.QPrinter
    real_replace = os.replace

    class FakePrinter:
        PrinterMode = real_printer.PrinterMode
        OutputFormat = real_printer.OutputFormat

        def __init__(self, _mode: object) -> None:
            self.output_path: Path | None = None

        def setOutputFormat(self, _output_format: object) -> None:
            pass

        def setOutputFileName(self, output_name: str) -> None:
            self.output_path = Path(output_name)

        def setDocName(self, _document_name: str) -> None:
            pass

    def render(_report: object, printer: FakePrinter) -> None:
        events.append("render")
        assert printer.output_path is not None
        printer.output_path.write_bytes(b"rendered")

    def release(_printer: FakePrinter) -> None:
        events.append("release")

    def validate(_path: Path) -> bool:
        events.append("validate")
        return True

    def publish(source: str | Path, target: str | Path) -> None:
        events.append("publish")
        real_replace(source, target)

    monkeypatch.setattr(report_output, "QPrinter", FakePrinter)
    monkeypatch.setattr(report_output, "_configure_a4_printer", lambda _printer: None)
    monkeypatch.setattr(report_output, "_render_to_printer", render)
    monkeypatch.setattr(report_output, "delete_qt_object", release)
    monkeypatch.setattr(report_output, "_is_complete_pdf", validate)
    monkeypatch.setattr(report_output.os, "replace", publish)

    output = report_output.write_report_pdf(monthly_report(), tmp_path / "released.pdf")

    assert output.read_bytes() == b"rendered"
    assert events == ["render", "release", "validate", "publish"]


def test_pdf_is_synced_before_publication_and_directory_afterwards(
    application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    real_replace = os.replace
    monkeypatch.setattr(
        report_output,
        "_render_pdf_to_path",
        lambda _report, path: path.write_bytes(b"synthetic valid output"),
    )
    monkeypatch.setattr(report_output, "_is_complete_pdf", lambda _path: True)
    monkeypatch.setattr(report_output, "sync_file", lambda _path: events.append("file-sync"))
    monkeypatch.setattr(
        report_output,
        "sync_parent_directory",
        lambda _path: events.append("directory-sync"),
    )

    def publish(source: str | Path, target: str | Path) -> None:
        events.append("publish")
        real_replace(source, target)

    monkeypatch.setattr(report_output.os, "replace", publish)

    output = report_output.write_report_pdf(monthly_report(), tmp_path / "durable.pdf")

    assert output.read_bytes() == b"synthetic valid output"
    assert events == ["file-sync", "publish", "directory-sync"]


def test_pdf_validation_rejects_truncated_header_only_output(
    application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def write_truncated(_report: object, path: Path) -> None:
        path.write_bytes(b"%PDF-1.4\ntruncated")

    monkeypatch.setattr(report_output, "_render_pdf_to_path", write_truncated)
    target = tmp_path / "truncated.pdf"

    with pytest.raises(report_output.ReportOutputError, match="not completed"):
        report_output.write_report_pdf(monthly_report(), target)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_pdf_cleanup_failure_does_not_mask_primary_render_error(
    application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_render(_report: object, path: Path) -> None:
        path.write_bytes(b"private partial report")
        raise OSError("primary disk failure")

    def fail_cleanup(_path: Path, *, missing_ok: bool = False) -> None:
        raise PermissionError("sharing violation")

    monkeypatch.setattr(report_output, "_render_pdf_to_path", fail_render)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)

    with pytest.raises(report_output.ReportOutputError) as caught:
        report_output.write_report_pdf(monthly_report(), tmp_path / "cleanup-failed.pdf")

    assert str(caught.value) == "The PDF output could not be written."
    assert isinstance(caught.value.__cause__, OSError)
    assert str(caught.value.__cause__) == "primary disk failure"
    assert any("temporary PDF could not be removed" in note for note in caught.value.__notes__)


def test_print_cancellation_does_not_render(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered = False

    class CancelledPrintDialog:
        def __init__(self, _printer: object, _parent: object) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Rejected

    def mark_rendered(_report: object, _printer: object) -> None:
        nonlocal rendered
        rendered = True

    monkeypatch.setattr(report_output, "QPrintDialog", CancelledPrintDialog)
    monkeypatch.setattr(report_output, "_render_to_printer", mark_rendered)
    monkeypatch.setattr(
        report_output,
        "delete_qt_object",
        lambda _value: None,
    )

    assert report_output.print_report(monthly_report()) is False
    assert rendered is False


def test_print_releases_dialog_before_printer_on_cancel(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    real_printer = report_output.QPrinter

    class FakePrinter:
        PrinterMode = real_printer.PrinterMode

        def __init__(self, _mode: object) -> None:
            pass

        def setDocName(self, _name: str) -> None:
            pass

    class FakeDialog:
        def __init__(self, _printer: FakePrinter, _parent: object) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(report_output, "QPrinter", FakePrinter)
    monkeypatch.setattr(report_output, "QPrintDialog", FakeDialog)
    monkeypatch.setattr(report_output, "_configure_a4_printer", lambda _printer: None)
    monkeypatch.setattr(
        report_output,
        "delete_qt_object",
        lambda value: events.append("dialog" if isinstance(value, FakeDialog) else "printer"),
    )

    assert report_output.print_report(monthly_report()) is False
    assert events == ["dialog", "printer"]


def test_cancelled_native_print_dialog_is_not_retained_by_parent(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = QWidget()
    monkeypatch.setattr(
        report_output.QPrintDialog,
        "exec",
        lambda _dialog: QDialog.DialogCode.Rejected,
    )

    assert report_output.print_report(monthly_report(), parent) is False
    application.processEvents()

    assert parent.findChildren(report_output.QPrintDialog) == []
    parent.close()


def test_accepted_print_uses_the_shared_current_report_document(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = yearly_report()
    rendered: list[object] = []

    class AcceptedPrintDialog:
        def __init__(self, _printer: object, _parent: object) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(report_output, "QPrintDialog", AcceptedPrintDialog)
    monkeypatch.setattr(
        report_output,
        "delete_qt_object",
        lambda _value: None,
    )
    monkeypatch.setattr(
        report_output,
        "_render_to_printer",
        lambda current_report, _printer: rendered.append(current_report),
    )

    assert report_output.print_report(report) is True
    assert rendered == [report]


def test_accepted_print_that_is_aborted_is_reported_as_failure(
    application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_printer = report_output.QPrinter

    class AbortedPrinter:
        PrinterMode = real_printer.PrinterMode
        PrinterState = real_printer.PrinterState

        def __init__(self, _mode: object) -> None:
            pass

        def setDocName(self, _name: str) -> None:
            pass

        def printerState(self) -> object:
            return real_printer.PrinterState.Aborted

    class AcceptedPrintDialog:
        def __init__(self, _printer: object, _parent: object) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(report_output, "QPrinter", AbortedPrinter)
    monkeypatch.setattr(report_output, "QPrintDialog", AcceptedPrintDialog)
    monkeypatch.setattr(report_output, "_configure_a4_printer", lambda _printer: None)
    monkeypatch.setattr(report_output, "_render_to_printer", lambda *_args: None)
    monkeypatch.setattr(report_output, "delete_qt_object", lambda _value: None)

    with pytest.raises(report_output.ReportOutputError, match="did not complete"):
        report_output.print_report(monthly_report())
