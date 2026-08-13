"""Shared visual foundation for the Hesiva desktop interface."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

APPLICATION_STYLESHEET = """
QMainWindow,
QDialog {
    background: #f4f6f8;
}

QWidget {
    color: #263442;
    font-family: sans-serif;
    font-size: 13px;
}

QMenuBar {
    background: #ffffff;
    border-bottom: 1px solid #d8dee6;
    padding: 2px 6px;
}

QMenuBar::item {
    background: transparent;
    padding: 6px 10px;
}

QMenuBar::item:selected,
QMenuBar::item:pressed {
    background: #e8eef6;
}

QMenu {
    background: #ffffff;
    border: 1px solid #cbd3dd;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px 6px 10px;
}

QMenu::item:selected {
    background: #e5effa;
    color: #173d65;
}

QLineEdit,
QComboBox,
QDateEdit,
QTimeEdit,
QSpinBox,
QPlainTextEdit {
    min-height: 30px;
    background: #ffffff;
    border: 1px solid #b9c2cc;
    border-radius: 3px;
    padding: 0 9px;
    selection-background-color: #2d649b;
    selection-color: #ffffff;
}

QLineEdit:focus,
QComboBox:focus,
QDateEdit:focus,
QTimeEdit:focus,
QSpinBox:focus,
QPlainTextEdit:focus {
    border: 1px solid #2d649b;
}

QLineEdit:disabled,
QComboBox:disabled,
QDateEdit:disabled,
QTimeEdit:disabled,
QSpinBox:disabled,
QPlainTextEdit:disabled {
    color: #56616c;
    background: #e3e8ed;
    border-color: #c5ccd3;
}

QComboBox::drop-down {
    border: 0;
    width: 24px;
}

QPushButton {
    min-height: 30px;
    border: 1px solid #b9c2cc;
    border-radius: 3px;
    background: #ffffff;
    padding: 0 13px;
}

QPushButton:hover {
    background: #f3f5f7;
}

QPushButton:focus {
    border: 1px solid #2d649b;
}

QPushButton[primary="true"] {
    color: #ffffff;
    background: #285b8f;
    border-color: #285b8f;
    font-weight: 600;
}

QPushButton[primary="true"]:hover {
    background: #214d7a;
}

QPushButton[archiveAction="true"] {
    color: #5f3c00;
    background: #fff4d6;
    border-color: #d9a441;
    font-weight: 600;
}

QPushButton[archiveAction="true"]:hover {
    background: #ffe9ad;
}

QPushButton[destructive="true"] {
    color: #ffffff;
    background: #b4232e;
    border-color: #b4232e;
    font-weight: 600;
}

QPushButton[destructive="true"]:hover {
    background: #941d26;
}

QPushButton[primary="true"]:focus {
    border: 2px solid #bcdcff;
}

QPushButton[archiveAction="true"]:focus {
    border: 2px solid #2d649b;
}

QPushButton[destructive="true"]:focus {
    border: 2px solid #ffd166;
}

QPushButton:disabled {
    color: #56616c;
    background: #e3e8ed;
    border-color: #d1d7de;
}

QPushButton[primary="true"]:disabled,
QPushButton[archiveAction="true"]:disabled,
QPushButton[destructive="true"]:disabled {
    color: #56616c;
    background: #e3e8ed;
    border: 1px solid #d1d7de;
}

QCheckBox:disabled,
QRadioButton:disabled,
QLabel:disabled {
    color: #56616c;
}

QSplitter::handle {
    background: #d8dee6;
}

QFrame[panel="true"] {
    background: #ffffff;
    border: 1px solid #d8dee6;
}

QFrame[detailPanel="true"] {
    background: #ffffff;
    border: 1px solid #d8dee6;
    border-radius: 4px;
}

QLabel[sectionHeading="true"] {
    color: #224e79;
    font-size: 13px;
    font-weight: 700;
}

QLabel[muted="true"] {
    color: #6f7a85;
}

QLabel[errorMessage="true"] {
    color: #b4232e;
    background: #fff0f1;
    border: 1px solid #efc5c9;
    border-radius: 3px;
    padding: 7px;
}

QLabel[successMessage="true"] {
    color: #07664f;
    background: #e2f7ee;
    border: 1px solid #9edfc9;
    border-radius: 3px;
    padding: 8px;
    font-weight: 600;
}

QLabel[infoBanner="true"] {
    color: #224e79;
    background: #edf5fc;
    border: 1px solid #bfd6ea;
    border-radius: 3px;
    padding: 8px;
}

QLabel[dialogHeading="true"] {
    color: #172534;
    font-size: 18px;
    font-weight: 700;
}

QLabel[reminderState="overdue"] {
    color: #704000;
    background: #fff4d6;
    border: 1px solid #e3c16f;
    border-radius: 3px;
    padding: 7px;
    font-weight: 700;
}

QLabel[reminderState="today"] {
    color: #173d65;
    background: #e5effa;
    border: 1px solid #b8d0e8;
    border-radius: 3px;
    padding: 7px;
    font-weight: 700;
}

QLabel[detailCaption="true"] {
    color: #6f7a85;
    font-weight: 600;
}

QLabel[detailValue="true"] {
    color: #263442;
}

QLabel[financialValue="true"] {
    font-weight: 700;
}

QLabel[emptyStateTitle="true"] {
    color: #485461;
    font-size: 14px;
    font-weight: 600;
}

QLabel[customerTitle="true"] {
    color: #172534;
    font-size: 23px;
    font-weight: 700;
}

QFrame#balancePanel {
    background: #203f64;
    border: 0;
    border-radius: 5px;
}

QFrame#balancePanel QLabel {
    color: #ffffff;
}

QLabel[balanceCaption="true"] {
    color: #d5e3f2;
    font-size: 12px;
}

QLabel[balanceValue="true"] {
    font-size: 24px;
    font-weight: 700;
}

QListWidget {
    background: #ffffff;
    border: 1px solid transparent;
    outline: 0;
}

QListWidget:focus {
    border-color: #2d649b;
}

QListWidget::item {
    border-bottom: 1px solid #e1e5e9;
    padding: 0;
}

QListWidget::item:selected {
    color: #173d65;
    background: #e3effb;
    border-left: 3px solid #66b7ee;
}

QTableWidget {
    background: #ffffff;
    alternate-background-color: #f7f9fb;
    border: 1px solid #d8dee6;
    gridline-color: #e1e5e9;
    selection-background-color: #e3effb;
    selection-color: #173d65;
}

QHeaderView::section {
    color: #405064;
    background: #eef2f6;
    border: 0;
    border-right: 1px solid #d8dee6;
    border-bottom: 1px solid #cbd3dd;
    padding: 7px 8px;
    font-weight: 700;
}

QLabel[warningMessage="true"] {
    color: #6b4300;
    background: #fff4d6;
    border: 1px solid #e0b75f;
    border-radius: 3px;
    padding: 8px;
}

QWidget[customerRow="true"] {
    background: transparent;
}

QLabel[customerRowName="true"] {
    color: #263442;
    font-weight: 700;
}

QLabel[customerRowBalance="true"] {
    font-weight: 700;
}

QLabel[balanceState="debt"] {
    color: #b4232e;
}

QLabel[balanceState="overpayment"] {
    color: #237a4b;
}

QLabel[balanceState="neutral"] {
    color: #6f7a85;
}

QTabWidget::pane {
    background: #ffffff;
    border: 0;
    border-top: 1px solid #d8dee6;
}

QTabBar::tab {
    background: #eceff3;
    border-right: 1px solid #d8dee6;
    padding: 9px 18px;
}

QTabBar::tab:selected {
    color: #224e79;
    background: #ffffff;
    font-weight: 700;
}

QTabBar::tab:hover:!selected {
    background: #e3e7ec;
}

QStatusBar {
    color: #66717d;
    background: #f7f8fa;
    border-top: 1px solid #d8dee6;
}
"""


def configure_application_theme(application: QApplication) -> None:
    """Install Hesiva's deterministic, accessible light application theme."""
    style = QStyleFactory.create("Fusion")
    if style is None:
        raise RuntimeError("Qt's built-in Fusion style is unavailable.")
    application.setStyle(style)

    palette = style.standardPalette()
    active_colors = {
        QPalette.ColorRole.Window: "#f4f6f8",
        QPalette.ColorRole.WindowText: "#263442",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f7f9fb",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#263442",
        QPalette.ColorRole.Text: "#263442",
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#263442",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Link: "#285b8f",
        QPalette.ColorRole.LinkVisited: "#5e3d80",
        QPalette.ColorRole.Highlight: "#2d649b",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#6f7a85",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#e5e9ed",
        QPalette.ColorRole.Mid: "#cbd3dd",
        QPalette.ColorRole.Dark: "#9aa6b2",
        QPalette.ColorRole.Shadow: "#59636e",
    }
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, color in active_colors.items():
            palette.setColor(group, role, QColor(color))

    disabled_colors = {
        **active_colors,
        QPalette.ColorRole.WindowText: "#56616c",
        QPalette.ColorRole.Base: "#e3e8ed",
        QPalette.ColorRole.AlternateBase: "#e9edf1",
        QPalette.ColorRole.Text: "#56616c",
        QPalette.ColorRole.Button: "#e3e8ed",
        QPalette.ColorRole.ButtonText: "#56616c",
        QPalette.ColorRole.Highlight: "#b9c2cc",
        QPalette.ColorRole.HighlightedText: "#263442",
        QPalette.ColorRole.PlaceholderText: "#56616c",
    }
    for role, color in disabled_colors.items():
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))

    application.setPalette(palette)
    application.setStyleSheet(APPLICATION_STYLESHEET)
