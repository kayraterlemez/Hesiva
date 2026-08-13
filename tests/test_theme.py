import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hesiva.ui.theme import APPLICATION_STYLESHEET, configure_application_theme  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        assert isinstance(existing, QApplication)
        return existing
    return QApplication([])


def _relative_luminance(color: QColor) -> float:
    channels = (color.redF(), color.greenF(), color.blueF())
    linear = tuple(
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: QColor, second: QColor) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_application_theme_replaces_external_style_palette_and_stylesheet(
    application: QApplication,
) -> None:
    hostile_palette = QPalette()
    hostile_palette.setColor(QPalette.ColorRole.Window, QColor("#050505"))
    hostile_palette.setColor(QPalette.ColorRole.WindowText, QColor("#080808"))
    application.setPalette(hostile_palette)
    application.setStyleSheet("QWidget { color: magenta; background: black; }")

    configure_application_theme(application)

    palette = application.palette()
    assert application.styleSheet() == APPLICATION_STYLESHEET
    application.setStyleSheet("")
    try:
        assert application.style().objectName().casefold() == "fusion"
    finally:
        application.setStyleSheet(APPLICATION_STYLESHEET)
    assert palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window).name() == (
        "#f4f6f8"
    )
    assert palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText).name() == (
        "#263442"
    )
    assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button).name() == (
        "#e3e8ed"
    )
    assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText).name() == (
        "#56616c"
    )


def test_application_palette_keeps_required_text_states_accessible(
    application: QApplication,
) -> None:
    configure_application_theme(application)
    palette = application.palette()

    assert (
        _contrast(
            palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText),
            palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window),
        )
        >= 4.5
    )
    checkbox = QCheckBox("Devre dışı")
    checkbox.setEnabled(False)
    checkbox.show()
    application.processEvents()
    assert checkbox.palette().color(QPalette.ColorRole.WindowText).name() == "#56616c"
    checkbox.close()
    assert (
        _contrast(
            palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText),
            palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight),
        )
        >= 4.5
    )
    assert (
        _contrast(
            palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText),
            palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button),
        )
        >= 4.5
    )


@pytest.mark.parametrize("property_name", ("primary", "archiveAction", "destructive"))
def test_action_button_variants_keep_a_visible_keyboard_focus_indicator(
    application: QApplication,
    property_name: str,
) -> None:
    configure_application_theme(application)
    host = QWidget()
    layout = QVBoxLayout(host)
    focus_sink = QPushButton("Odak alıcı", host)
    button = QPushButton("İşlem", host)
    button.setProperty(property_name, True)
    button.setFixedSize(180, 40)
    layout.addWidget(focus_sink)
    layout.addWidget(button)
    host.show()
    application.processEvents()

    focus_sink.setFocus()
    application.processEvents()
    unfocused_pixels = bytes(button.grab().toImage().bits())

    button.setFocus()
    application.processEvents()
    focused_pixels = bytes(button.grab().toImage().bits())

    assert button.hasFocus()
    assert focused_pixels != unfocused_pixels

    button.setEnabled(False)
    application.processEvents()
    disabled_image = button.grab().toImage()
    assert disabled_image.pixelColor(5, disabled_image.height() // 2).name() == "#e3e8ed"
    host.close()


def test_customer_list_keeps_selection_and_shows_keyboard_focus(
    application: QApplication,
) -> None:
    configure_application_theme(application)
    host = QWidget()
    layout = QVBoxLayout(host)
    focus_sink = QPushButton("Odak alıcı", host)
    customer_list = QListWidget(host)
    customer_list.setFixedSize(240, 90)
    customer = QListWidgetItem("")
    customer.setSizeHint(QSize(220, 40))
    customer_list.addItem(customer)
    customer_list.setCurrentItem(customer)
    layout.addWidget(focus_sink)
    layout.addWidget(customer_list)
    host.show()
    application.processEvents()

    focus_sink.setFocus()
    application.processEvents()
    unfocused_image = customer_list.grab().toImage()
    selected_point = customer_list.viewport().mapTo(
        customer_list,
        customer_list.visualItemRect(customer).center(),
    )
    unfocused_selection = unfocused_image.pixelColor(selected_point)

    customer_list.setFocus()
    application.processEvents()
    focused_image = customer_list.grab().toImage()
    focused_selection = focused_image.pixelColor(selected_point)

    assert customer_list.hasFocus()
    assert customer.isSelected()
    assert bytes(focused_image.bits()) != bytes(unfocused_image.bits())
    assert focused_selection == unfocused_selection == QColor("#e3effb")
    assert _contrast(QColor("#173d65"), focused_selection) >= 4.5
    host.close()
