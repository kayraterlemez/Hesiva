from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hesiva.services import ApplicationSettings
from hesiva.ui.theme import APPLICATION_STYLESHEET


class SettingsDialog(QDialog):
    """Frozen, deliberately small V1 Settings surface."""

    password_change_requested = Signal()
    backup_location_change_requested = Signal()

    def __init__(
        self,
        settings: ApplicationSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle("Ayarlar")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setStyleSheet(APPLICATION_STYLESHEET)

        heading = QLabel("Ayarlar", self)
        heading.setProperty("dialogHeading", True)

        security_heading = QLabel("Güvenlik", self)
        security_heading.setProperty("sectionHeading", True)
        security_panel = self._panel("Güvenlik")
        security_layout = QGridLayout(security_panel)
        security_layout.setContentsMargins(16, 14, 16, 14)
        security_layout.addWidget(QLabel("Giriş Şifresi", security_panel), 0, 0)
        self.change_password_button = QPushButton("Parola Değiştir", security_panel)
        self.change_password_button.setObjectName("settingsChangePasswordButton")
        self.change_password_button.clicked.connect(self.password_change_requested)
        security_layout.addWidget(self.change_password_button, 0, 1)
        security_layout.setColumnStretch(0, 1)

        backup_heading = QLabel("Yedekleme", self)
        backup_heading.setProperty("sectionHeading", True)
        backup_panel = self._panel("Yedekleme")
        backup_layout = QGridLayout(backup_panel)
        backup_layout.setContentsMargins(16, 14, 16, 14)
        backup_layout.setHorizontalSpacing(10)
        backup_layout.addWidget(QLabel("Yedekleme Konumu:", backup_panel), 0, 0)
        self.change_backup_location_button = QPushButton("Konumu Değiştir", backup_panel)
        self.change_backup_location_button.setObjectName("settingsChangeBackupLocationButton")
        self.change_backup_location_button.clicked.connect(self.backup_location_change_requested)
        backup_layout.addWidget(self.change_backup_location_button, 0, 1)
        self.backup_location_input = QLineEdit(backup_panel)
        self.backup_location_input.setObjectName("settingsBackupLocationInput")
        self.backup_location_input.setReadOnly(True)
        self.backup_location_input.setAccessibleName("Yedekleme konumu")
        backup_layout.addWidget(self.backup_location_input, 1, 0, 1, 2)

        information_panel = self._panel("Uygulama Bilgisi")
        information_layout = QHBoxLayout(information_panel)
        information_layout.setContentsMargins(16, 14, 16, 14)
        information_layout.addWidget(QLabel("Uygulama Bilgisi", information_panel))
        information_layout.addStretch()
        self.version_label = QLabel(information_panel)
        self.version_label.setObjectName("settingsVersionLabel")
        self.version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        information_layout.addWidget(self.version_label)

        self.close_button = QPushButton("Kapat", self)
        self.close_button.setObjectName("closeSettingsButton")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        layout.addWidget(heading)
        layout.addWidget(security_heading)
        layout.addWidget(security_panel)
        layout.addWidget(backup_heading)
        layout.addWidget(backup_panel)
        layout.addWidget(information_panel)
        layout.addLayout(buttons)

        self.set_settings(settings)
        QWidget.setTabOrder(self.change_password_button, self.change_backup_location_button)
        QWidget.setTabOrder(self.change_backup_location_button, self.close_button)
        self.change_password_button.setFocus()

    def set_settings(self, settings: ApplicationSettings) -> None:
        self.backup_location_input.setText(str(settings.backup_destination_directory))
        self.version_label.setText(f"Sürüm: {settings.application_version}")

    @property
    def backup_destination_directory(self) -> Path:
        return Path(self.backup_location_input.text())

    def _panel(self, title: str) -> QFrame:
        panel = QFrame(self)
        panel.setProperty("detailPanel", True)
        panel.setAccessibleName(title)
        return panel


class AboutDialog(QDialog):
    """Read-only product identity dialog with no network or persistence behavior."""

    def __init__(self, application_version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aboutDialog")
        self.setWindowTitle("Hakkında")
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setStyleSheet(APPLICATION_STYLESHEET)

        self.product_name_label = QLabel("Hesiva", self)
        self.product_name_label.setObjectName("aboutProductNameLabel")
        self.product_name_label.setProperty("dialogHeading", True)
        self.product_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.version_label = QLabel(f"Sürüm {application_version}", self)
        self.version_label.setObjectName("aboutVersionLabel")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.description_label = QLabel(
            "Veteriner müşteri hesap ve bakiye takip uygulaması.",
            self,
        )
        self.description_label.setObjectName("aboutDescriptionLabel")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        self.description_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.license_label = QLabel("MIT Lisansı", self)
        self.license_label.setObjectName("aboutLicenseLabel")
        self.license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.license_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.close_button = QPushButton("Kapat", self)
        self.close_button.setObjectName("closeAboutButton")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(12)
        layout.addWidget(self.product_name_label)
        layout.addWidget(self.version_label)
        layout.addSpacing(4)
        layout.addWidget(self.description_label)
        layout.addWidget(self.license_label)
        layout.addSpacing(8)
        layout.addLayout(buttons)

        self.close_button.setFocus()
