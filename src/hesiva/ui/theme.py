"""Shared visual foundation for the Hesiva desktop interface."""

APPLICATION_STYLESHEET = """
QMainWindow {
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
QPlainTextEdit {
    min-height: 30px;
    background: #ffffff;
    border: 1px solid #b9c2cc;
    border-radius: 3px;
    padding: 0 9px;
    selection-background-color: #2d649b;
}

QLineEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus {
    border: 1px solid #2d649b;
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

QPushButton:disabled {
    color: #7c8792;
    background: #e3e8ed;
    border-color: #d1d7de;
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

QLabel[dialogHeading="true"] {
    color: #172534;
    font-size: 18px;
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
    border: 0;
    outline: 0;
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
