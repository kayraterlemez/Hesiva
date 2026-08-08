from datetime import datetime
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

from hesiva.services import BackupMetadata


class BackupDialog(QDialog):
    """Frozen V1 backup destination and action shell."""

    change_location_requested = Signal()
    create_requested = Signal()
    restore_requested = Signal()

    def __init__(self, destination_directory: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Yedekleme ve Veri Güvenliği")
        self.setObjectName("backupDialog")
        self.setModal(True)
        self.setMinimumWidth(680)

        explanation = QLabel(
            "Yedeklerin farklı bir disk veya harici depolama alanında tutulması önerilir. "
            "Düzenli yedekleme, veri kaybını önler.",
            self,
        )
        explanation.setWordWrap(True)

        location_label = QLabel("YEDEKLEME KONUMU", self)
        location_label.setProperty("sectionHeading", True)
        self.location_input = QLineEdit(str(destination_directory), self)
        self.location_input.setObjectName("backupLocationInput")
        self.location_input.setReadOnly(True)

        self.success_label = QLabel("", self)
        self.success_label.setObjectName("backupSuccessLabel")
        self.success_label.setProperty("successMessage", True)
        self.success_label.setWordWrap(True)
        self.success_label.hide()

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("backupErrorLabel")
        self.error_label.setProperty("errorMessage", True)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        self.change_location_button = QPushButton("Konumu Değiştir", self)
        self.change_location_button.setObjectName("changeBackupLocationButton")
        self.change_location_button.clicked.connect(self.change_location_requested)
        self.restore_button = QPushButton("Geri Yükle...", self)
        self.restore_button.setObjectName("restoreBackupButton")
        self.restore_button.clicked.connect(self.restore_requested)
        self.create_button = QPushButton("Yedek Oluştur", self)
        self.create_button.setObjectName("createBackupButton")
        self.create_button.setProperty("primary", True)
        self.create_button.clicked.connect(self.create_requested)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.change_location_button)
        buttons.addWidget(self.restore_button)
        buttons.addWidget(self.create_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        layout.addWidget(explanation)
        layout.addWidget(location_label)
        layout.addWidget(self.location_input)
        layout.addWidget(self.success_label)
        layout.addWidget(self.error_label)
        layout.addSpacing(4)
        layout.addLayout(buttons)

    @property
    def destination_directory(self) -> Path:
        return Path(self.location_input.text())

    def set_destination_directory(self, directory: Path) -> None:
        self.location_input.setText(str(directory))

    def set_busy(self, busy: bool) -> None:
        self.change_location_button.setEnabled(not busy)
        self.restore_button.setEnabled(not busy)
        self.create_button.setEnabled(not busy)

    def show_backup_success(self, metadata: BackupMetadata) -> None:
        moment = _format_backup_moment(metadata.created_at)
        self.error_label.hide()
        self.success_label.setText(f"Son Başarılı Yedek: {moment}")
        self.success_label.show()

    def show_operation_error(self, message: str) -> None:
        self.success_label.hide()
        self.error_label.setText(message)
        self.error_label.show()


class RestoreConfirmationDialog(QDialog):
    """Explicit destructive confirmation for one already-validated backup."""

    def __init__(self, metadata: BackupMetadata, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Yedekten Geri Yükle")
        self.setObjectName("restoreConfirmationDialog")
        self.setModal(True)
        self.setMinimumWidth(620)

        information_panel = QFrame(self)
        information_panel.setProperty("detailPanel", True)
        information_layout = QGridLayout(information_panel)
        information_layout.setContentsMargins(16, 14, 16, 14)
        information_layout.setHorizontalSpacing(28)
        information_layout.addWidget(_caption("Yedek Tarihi:", information_panel), 0, 0)
        information_layout.addWidget(_caption("Uygulama Sürümü:", information_panel), 0, 1)
        information_layout.addWidget(_caption("Veritabanı Sürümü:", information_panel), 0, 2)
        information_layout.addWidget(
            _value(_format_backup_moment(metadata.created_at), information_panel),
            1,
            0,
        )
        information_layout.addWidget(_value(metadata.application_version, information_panel), 1, 1)
        information_layout.addWidget(_value(metadata.database_revision, information_panel), 1, 2)

        warning = QLabel(
            "DİKKAT: Verilerin Üzerine Yazılacak\n\n"
            "Geri yükleme mevcut veritabanının yerine seçilen yedeği kullanacaktır. "
            "İşlemden önce mevcut veriler için otomatik güvenlik yedeği oluşturulacaktır.",
            self,
        )
        warning.setObjectName("restoreWarningLabel")
        warning.setProperty("warningMessage", True)
        warning.setWordWrap(True)

        self.cancel_button = QPushButton("Vazgeç", self)
        self.cancel_button.setObjectName("cancelRestoreButton")
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.restore_button = QPushButton("Geri Yükle", self)
        self.restore_button.setObjectName("confirmRestoreButton")
        self.restore_button.setProperty("destructive", True)
        self.restore_button.setAutoDefault(False)
        self.restore_button.setDefault(False)
        self.restore_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.restore_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)
        layout.addWidget(information_panel)
        layout.addWidget(warning)
        layout.addLayout(buttons)


def _caption(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setProperty("detailCaption", True)
    return label


def _value(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setProperty("financialValue", True)
    return label


def _format_backup_moment(moment: datetime) -> str:
    return moment.astimezone().strftime("%d.%m.%Y %H:%M")
