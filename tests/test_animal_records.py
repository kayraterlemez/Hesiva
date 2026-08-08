from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from hesiva.database.base import Base
from hesiva.database.engine import create_sqlite_engine
from hesiva.models import Animal, Customer
from hesiva.read_models import AnimalSummary
from hesiva.repositories import AnimalRepository, CustomerRepository
from hesiva.services import AnimalService, CustomerNotFoundError


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Engine, Session]]:
    engine = create_sqlite_engine(tmp_path / "animal-records.db")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield engine, session
    finally:
        engine.dispose()


def animal_service(session: Session) -> AnimalService:
    return AnimalService(
        session,
        AnimalRepository(session),
        CustomerRepository(session),
    )


def test_active_and_archived_records_are_separate_plain_deterministic_results(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customers = CustomerRepository(session)
    animals = AnimalRepository(session)
    customer = customers.add(Customer(full_name="Animal Owner"))
    other = customers.add(Customer(full_name="Other Owner"))
    first = animals.add(
        Animal(
            customer=customer,
            ear_tag="DUPLICATE",
            name=None,
            species="Sığır",
            notes=None,
        )
    )
    second = animals.add(
        Animal(
            customer=customer,
            ear_tag="DUPLICATE",
            name="Boncuk",
            species=None,
            notes="Not",
        )
    )
    archived = animals.add(
        Animal(
            customer=customer,
            ear_tag=None,
            name=None,
            species=None,
            notes=None,
            archived_at=datetime(2026, 8, 1),
        )
    )
    animals.add(Animal(customer=other, ear_tag="DUPLICATE", name="Unrelated"))
    service = animal_service(session)

    active_records = service.list_active_records(customer.id)
    archived_records = service.list_archived_records(customer.id)

    assert [record.animal_id for record in active_records] == [first.id, second.id]
    assert active_records == [
        AnimalSummary(
            animal_id=first.id,
            customer_id=customer.id,
            ear_tag="DUPLICATE",
            name=None,
            species="Sığır",
            notes=None,
            archived_at=None,
        ),
        AnimalSummary(
            animal_id=second.id,
            customer_id=customer.id,
            ear_tag="DUPLICATE",
            name="Boncuk",
            species=None,
            notes="Not",
            archived_at=None,
        ),
    ]
    assert [record.animal_id for record in archived_records] == [archived.id]
    assert archived_records[0].archived_at == datetime(2026, 8, 1)
    assert archived_records[0].ear_tag is None
    assert all(not hasattr(record, "_sa_instance_state") for record in active_records)


def test_animal_record_reads_reject_missing_customer(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    service = animal_service(session)

    with pytest.raises(CustomerNotFoundError):
        service.list_active_records(999)
    with pytest.raises(CustomerNotFoundError):
        service.list_archived_records(999)


def test_active_animal_read_query_count_is_bounded_independent_of_animal_count(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = CustomerRepository(session).add(Customer(full_name="Bounded Query Owner"))
    repository = AnimalRepository(session)
    for index in range(8):
        repository.add(Animal(customer=customer, name=f"Animal {index}"))
    customer_id = customer.id
    session.commit()
    selects: list[str] = []

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        records = animal_service(session).list_active_records(customer_id)
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert len(records) == 8
    assert len(selects) == 2
