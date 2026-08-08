from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from hesiva.database.engine import create_sqlite_engine
from hesiva.database.session import create_session_factory
from hesiva.repositories import (
    AnimalRepository,
    CustomerRepository,
    ReminderRepository,
    TransactionRepository,
)
from hesiva.services import (
    AccountHistoryService,
    AnimalService,
    CustomerDetailService,
    CustomerService,
    CustomerSummaryService,
    ReminderService,
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


@dataclass
class ApplicationContext:
    """Long-lived engine and factory used to create short-lived service sets."""

    database_path: Path
    engine: Engine
    session_factory: sessionmaker[Session]

    @contextmanager
    def services(self) -> Iterator[ServiceSet]:
        """Create services and repositories bound to one short-lived session."""
        with self.session_factory() as session:
            customer_repository = CustomerRepository(session)
            animal_repository = AnimalRepository(session)
            transaction_repository = TransactionRepository(session)
            reminder_repository = ReminderRepository(session)

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
            )

    def close(self) -> None:
        """Release pooled database connections owned by the application."""
        self.engine.dispose()


def build_application_context(database_path: Path) -> ApplicationContext:
    """Open the initialized database and build application-level dependencies."""
    engine = create_sqlite_engine(database_path)
    try:
        with engine.connect() as connection:
            connection.scalar(text("SELECT 1"))
    except Exception:
        engine.dispose()
        raise

    return ApplicationContext(
        database_path=database_path,
        engine=engine,
        session_factory=create_session_factory(engine),
    )
