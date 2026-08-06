import sys

from PySide6.QtWidgets import QApplication

from cari.ui.main_window import MainWindow


def main() -> int:
    """Start the Cari desktop application."""
    application = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()

    return application.exec()
