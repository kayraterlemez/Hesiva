from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from argon2 import PasswordHasher
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from hesiva.database.engine import create_sqlite_engine
from hesiva.database.paths import get_config_path
from hesiva.database.session import create_session_factory
from hesiva.configuration import ConfigurationStore
from hesiva.repositories import (
    AnimalRepository,
    CustomerRepository,
    LegacyImportRepository,
    ReminderRepository,
    ReportRepository,
    TransactionRepository,
)
from hesiva.services import (
    AccountHistoryService,
    AnimalService,
    AuthenticationService,
    BackupMetadata,
    BackupService,
    CustomerDetailService,
    CustomerService,
    CustomerSummaryService,
    LegacyImportService,
    ReminderService,
    ReportService,
    RestoreResult,
    SettingsService,
    TransactionService,
)


@dataclass(frozen=True)
class ServiceSet:
    """Services sharing one explicitly scoped SQLAlchemy session."""

    account_history: AccountHistoryService
    customer: CustomerService
    customer_detail: CustomerDetailService
    customer_summary: CustomerSummaryService
    animal: AnimalService
    transaction: TransactionService
    reminder: ReminderService
    report: ReportService
    legacy_import: LegacyImportService


@dataclass
class ApplicationContext:
    """Long-lived engine and factory used to create short-lived service sets."""

    database_path: Path
    engine: Engine
    session_factory: sessionmaker[Session]
    configuration_store: ConfigurationStore
    authentication: AuthenticationService
    _active_service_scopes: int = field(default=0, init=False, repr=False)
    _database_available: bool = field(default=True, init=False, repr=False)
    _backup_service: BackupService = field(init=False, repr=False)
    settings: SettingsService = field(init=False)

    def __post_init__(self) -> None:
        self._backup_service = BackupService(self.database_path, self.configuration_store)
        self.settings = SettingsService(
            self.configuration_store,
            self._backup_service.default_backup_directory,
        )

    @contextmanager
    def services(self) -> Iterator[ServiceSet]:
        """Create services and repositories bound to one short-lived session."""
        if not self._database_available:
            raise RuntimeError("The Hesiva database is temporarily unavailable.")
        self._active_service_scopes += 1
        try:
            with self.session_factory() as session:
                customer_repository = CustomerRepository(session)
                animal_repository = AnimalRepository(session)
                transaction_repository = TransactionRepository(session)
                reminder_repository = ReminderRepository(session)
                report_repository = ReportRepository(session)
                legacy_import_repository = LegacyImportRepository(session)

                yield ServiceSet(
                    account_history=AccountHistoryService(transaction_repository),
                    customer=CustomerService(session, customer_repository),
                    customer_detail=CustomerDetailService(customer_repository),
                    customer_summary=CustomerSummaryService(customer_repository),
                    animal=AnimalService(session, animal_repository, customer_repository),
                    transaction=TransactionService(
                        session,
                        transaction_repository,
                        customer_repository,
                        animal_repository,
                    ),
                    reminder=ReminderService(session, reminder_repository, customer_repository),
                    report=ReportService(report_repository),
                    legacy_import=LegacyImportService(session, legacy_import_repository),
                )
        finally:
            self._active_service_scopes -= 1

    @property
    def active_service_scopes(self) -> int:
        """Return the number of currently open caller-owned service scopes."""
        return self._active_service_scopes

    def create_backup(self, destination_path: Path) -> BackupMetadata:
        """Create a verified backup while keeping the application database open."""
        return self._backup_service.create_backup(destination_path)

    def prepare_default_backup_directory(self) -> Path:
        """Return the ready documented local fallback backup directory."""
        return self._backup_service.prepare_default_backup_directory()

    def prepare_manual_backup_directory(self) -> Path:
        """Resolve the configured manual-backup directory without silent fallback."""
        destination, uses_default = self.settings.resolve_backup_destination_directory()
        if uses_default:
            return self._backup_service.prepare_default_backup_directory()
        return destination

    def validate_backup(self, backup_path: Path) -> BackupMetadata:
        """Validate a backup without changing the application database."""
        return self._backup_service.validate_backup(backup_path)

    def restore_backup(self, backup_path: Path) -> RestoreResult:
        """Restore a verified backup through the context-owned engine lifecycle."""
        if self._active_service_scopes:
            raise RuntimeError("Restore cannot run while a service scope is active.")
        return self._backup_service.restore_backup(
            backup_path,
            close_live_database=self._close_database_for_restore,
            reopen_live_database=self._reopen_database_after_restore,
        )

    def _close_database_for_restore(self) -> None:
        self.engine.dispose()
        self._database_available = False

    def _reopen_database_after_restore(self) -> None:
        engine = create_sqlite_engine(self.database_path)
        try:
            with engine.connect() as connection:
                connection.scalar(text("SELECT 1"))
        except Exception:
            engine.dispose()
            raise
        self.engine = engine
        self.session_factory = create_session_factory(engine)
        self._database_available = True

    def close(self) -> None:
        """Release pooled database connections owned by the application."""
        self.engine.dispose()
        self._database_available = False


def build_application_context(
    database_path: Path,
    *,
    password_hasher: PasswordHasher | None = None,
) -> ApplicationContext:
    """Open the initialized database and build application-level dependencies."""
    engine = create_sqlite_engine(database_path)
    try:
        with engine.connect() as connection:
            connection.scalar(text("SELECT 1"))
    except Exception:
        engine.dispose()
        raise

    configuration_store = ConfigurationStore(get_config_path(database_path.parent))
    return ApplicationContext(
        database_path=database_path,
        engine=engine,
        session_factory=create_session_factory(engine),
        configuration_store=configuration_store,
        authentication=AuthenticationService(configuration_store, password_hasher),
    )
