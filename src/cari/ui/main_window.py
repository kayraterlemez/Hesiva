from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Bootstrap shell for the Cari main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cari")
