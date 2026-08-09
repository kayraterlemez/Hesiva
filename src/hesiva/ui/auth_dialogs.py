from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hesiva.services import (
    AuthenticationError,
    AuthenticationFailedError,
    AuthenticationService,
    InvalidCredentialStateError,
    PasswordMismatchError,
    ValidationError,
)
from hesiva.ui.theme import APPLICATION_STYLESHEET


class SetupChoice(Enum):
    EMPTY = "empty"
    LEGACY_IMPORT = "legacy_import"


class _AuthenticationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(APPLICATION_STYLESHEET)

    def _build_error_label(self) -> QLabel:
        label = QLabel("", self)
        label.setProperty("errorMessage", True)
        label.setWordWrap(True)
        label.hide()
        return label

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()


class InitialPasswordDialog(_AuthenticationDialog):
    """Frozen first-run password creation dialog backed by AuthenticationService."""

    def __init__(
        self,
        authentication: AuthenticationService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._authentication = authentication
        self.setObjectName("initialPasswordDialog")
        self.setWindowTitle("Hesiva - İlk Kurulum")
        self.setModal(True)
        self.setMinimumWidth(440)

        heading = QLabel("Parola Oluştur", self)
        heading.setProperty("dialogHeading", True)
        description = QLabel("Uygulamayı korumak için bir parola oluşturun.", self)
        description.setWordWrap(True)

        self.password_input = QLineEdit(self)
        self.password_input.setObjectName("initialPasswordInput")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setAccessibleName("Parola")
        self.confirmation_input = QLineEdit(self)
        self.confirmation_input.setObjectName("initialPasswordConfirmationInput")
        self.confirmation_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirmation_input.setAccessibleName("Parolayı Tekrar Gir")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow("Parola: *", self.password_input)
        form.addRow("Parolayı Tekrar Gir: *", self.confirmation_input)

        self.error_label = self._build_error_label()
        self.exit_button = QPushButton("Çıkış", self)
        self.exit_button.clicked.connect(self.reject)
        self.continue_button = QPushButton("Devam Et", self)
        self.continue_button.setProperty("primary", True)
        self.continue_button.setDefault(True)
        self.continue_button.clicked.connect(self._create_password)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.exit_button)
        buttons.addWidget(self.continue_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        QWidget.setTabOrder(self.password_input, self.confirmation_input)
        QWidget.setTabOrder(self.confirmation_input, self.continue_button)
        self.password_input.setFocus()

    def _create_password(self) -> None:
        try:
            self._authentication.create_initial_password(
                self.password_input.text(),
                self.confirmation_input.text(),
            )
        except PasswordMismatchError:
            self.show_error("Parolalar eşleşmiyor.")
            self.confirmation_input.clear()
            self.confirmation_input.setFocus()
        except ValidationError:
            self.show_error("Parola boş bırakılamaz.")
            self.password_input.setFocus()
        except AuthenticationError:
            self.show_error("Parola güvenli şekilde kaydedilemedi. Lütfen yeniden deneyin.")
        else:
            self.accept()


class LoginDialog(_AuthenticationDialog):
    """Password-only local login gate."""

    def __init__(
        self,
        authentication: AuthenticationService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._authentication = authentication
        self.setObjectName("loginDialog")
        self.setWindowTitle("Hesiva - Giriş")
        self.setModal(True)
        self.setMinimumWidth(400)

        heading = QLabel("Hesiva", self)
        heading.setProperty("dialogHeading", True)
        description = QLabel("Devam etmek için parolanızı girin.", self)

        self.password_input = QLineEdit(self)
        self.password_input.setObjectName("loginPasswordInput")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setAccessibleName("Parola")
        self.password_input.setPlaceholderText("Parola")
        self.error_label = self._build_error_label()

        self.exit_button = QPushButton("Çıkış", self)
        self.exit_button.clicked.connect(self.reject)
        self.login_button = QPushButton("Giriş Yap", self)
        self.login_button.setProperty("primary", True)
        self.login_button.setDefault(True)
        self.login_button.clicked.connect(self._authenticate)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.exit_button)
        buttons.addWidget(self.login_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addWidget(self.password_input)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)
        self.password_input.setFocus()

    def _authenticate(self) -> None:
        try:
            verified = self._authentication.verify_password(self.password_input.text())
        except InvalidCredentialStateError:
            self.show_error("Kimlik doğrulama bilgileri geçersiz. Hesiva açılamıyor.")
            self.login_button.setEnabled(False)
            return
        if not verified:
            self.show_error("Parola yanlış. Lütfen yeniden deneyin.")
            self.password_input.clear()
            self.password_input.setFocus()
            return
        self.accept()


class PasswordChangeDialog(_AuthenticationDialog):
    """Frozen current/new/confirmation password-change flow."""

    def __init__(
        self,
        authentication: AuthenticationService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._authentication = authentication
        self.setObjectName("passwordChangeDialog")
        self.setWindowTitle("Parola Değiştir")
        self.setModal(True)
        self.setMinimumWidth(440)

        self.current_password_input = self._password_input("currentPasswordInput")
        self.new_password_input = self._password_input("newPasswordInput")
        self.confirmation_input = self._password_input("newPasswordConfirmationInput")

        form = QFormLayout()
        form.addRow("Mevcut Parola: *", self.current_password_input)
        form.addRow("Yeni Parola: *", self.new_password_input)
        form.addRow("Yeni Parola Tekrar: *", self.confirmation_input)

        self.error_label = self._build_error_label()
        self.cancel_button = QPushButton("İptal", self)
        self.cancel_button.clicked.connect(self.reject)
        self.change_button = QPushButton("Parolayı Değiştir", self)
        self.change_button.setProperty("primary", True)
        self.change_button.setDefault(True)
        self.change_button.clicked.connect(self._change_password)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.change_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        heading = QLabel("Parola Değiştir", self)
        heading.setProperty("dialogHeading", True)
        layout.addWidget(heading)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        QWidget.setTabOrder(self.current_password_input, self.new_password_input)
        QWidget.setTabOrder(self.new_password_input, self.confirmation_input)
        QWidget.setTabOrder(self.confirmation_input, self.change_button)
        self.current_password_input.setFocus()

    def _password_input(self, object_name: str) -> QLineEdit:
        field = QLineEdit(self)
        field.setObjectName(object_name)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        return field

    def _change_password(self) -> None:
        try:
            self._authentication.change_password(
                self.current_password_input.text(),
                self.new_password_input.text(),
                self.confirmation_input.text(),
            )
        except AuthenticationFailedError:
            self.show_error("Mevcut parola yanlış.")
            self.current_password_input.clear()
            self.current_password_input.setFocus()
        except PasswordMismatchError:
            self.show_error("Yeni parolalar eşleşmiyor.")
            self.confirmation_input.clear()
            self.confirmation_input.setFocus()
        except ValidationError:
            self.show_error("Yeni parola boş bırakılamaz.")
            self.new_password_input.setFocus()
        except AuthenticationError:
            self.show_error(
                "Parola değiştirilemedi. Hesiva'yı kapatıp yeniden açarak "
                "mevcut parolanızı doğrulayın."
            )
        else:
            self.accept()


class DatabaseChoiceDialog(QDialog):
    """Frozen first-run choice between an empty database and legacy import."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(APPLICATION_STYLESHEET)
        self.choice: SetupChoice | None = None
        self.setObjectName("databaseChoiceDialog")
        self.setWindowTitle("Hesiva - Nasıl Başlamak İstersiniz?")
        self.setModal(True)
        self.setMinimumWidth(520)

        heading = QLabel("Nasıl başlamak istersiniz?", self)
        heading.setProperty("dialogHeading", True)
        description = QLabel(
            "Boş bir Hesiva veritabanıyla başlayabilir veya eski Veresiye 5 "
            "verilerinizi içe aktarabilirsiniz.",
            self,
        )
        description.setWordWrap(True)

        self.empty_button = QPushButton("Boş Veritabanıyla Başla", self)
        self.empty_button.setProperty("primary", True)
        self.empty_button.setMinimumHeight(44)
        self.empty_button.clicked.connect(self._choose_empty)
        self.import_button = QPushButton("Eski Veresiye 5 Verilerini İçe Aktar", self)
        self.import_button.setMinimumHeight(44)
        self.import_button.clicked.connect(self._choose_import)
        self.exit_button = QPushButton("Çıkış", self)
        self.exit_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addSpacing(6)
        layout.addWidget(self.empty_button)
        layout.addWidget(self.import_button)
        layout.addWidget(self.exit_button, alignment=Qt.AlignmentFlag.AlignRight)

    def _choose_empty(self) -> None:
        self.choice = SetupChoice.EMPTY
        self.accept()

    def _choose_import(self) -> None:
        self.choice = SetupChoice.LEGACY_IMPORT
        self.accept()
