from dataclasses import dataclass
from pathlib import Path

from hesiva.configuration import ConfigurationError, ConfigurationStore
from hesiva.services.exceptions import SettingsPersistenceError, ValidationError
from hesiva.version import get_application_version


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    """Non-secret application metadata safe for retention by the Settings UI."""

    backup_destination_directory: Path
    uses_default_backup_destination: bool
    application_version: str


class SettingsService:
    """Read and update the narrow persistent V1 Settings contract."""

    def __init__(
        self,
        configuration_store: ConfigurationStore,
        default_backup_directory: Path,
    ) -> None:
        if not default_backup_directory.is_absolute():
            raise ValueError("The default backup directory must be absolute.")
        self._configuration_store = configuration_store
        self._default_backup_directory = default_backup_directory

    def get_settings(self) -> ApplicationSettings:
        destination, uses_default = self.resolve_backup_destination_directory()
        return ApplicationSettings(
            backup_destination_directory=destination,
            uses_default_backup_destination=uses_default,
            application_version=get_application_version(),
        )

    def resolve_backup_destination_directory(self) -> tuple[Path, bool]:
        configuration = self._load_configuration()
        configured_destination = configuration.backup_destination_directory
        if configured_destination is None:
            return self._default_backup_directory, True
        return Path(configured_destination), False

    def update_backup_destination_directory(self, destination_directory: Path) -> None:
        destination = destination_directory.expanduser()
        if not destination.is_absolute():
            raise ValidationError("Yedekleme konumu mutlak bir dizin yolu olmalıdır.")
        if not destination.is_dir():
            raise ValidationError("Seçilen yedekleme dizini mevcut değil.")
        configuration = self._load_configuration()
        updated = configuration.with_backup_destination_directory(destination)
        try:
            self._configuration_store.save(updated)
        except ConfigurationError as error:
            raise SettingsPersistenceError(
                "Yedekleme konumu güvenli şekilde kaydedilemedi."
            ) from error

    def _load_configuration(self):
        try:
            return self._configuration_store.load()
        except ConfigurationError as error:
            raise SettingsPersistenceError("Hesiva ayarları okunamadı.") from error
