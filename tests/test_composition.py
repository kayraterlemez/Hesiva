from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import object_session

from cari.application import ApplicationStartupError, create_application_context
from cari.composition import ApplicationContext
from cari.database.paths import DATABASE_FILENAME
from cari.database.startup import DatabaseState, inspect_database


@pytest.fixture
def application_context(tmp_path: Path) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "application-data")
    try:
        yield context
    finally:
        context.close()


def test_application_context_uses_explicit_data_directory_and_alembic_schema(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "explicit-data"

    context = create_application_context(data_directory)
    try:
        assert context.database_path == data_directory / DATABASE_FILENAME
        assert inspect_database(context.database_path).state is DatabaseState.CURRENT
    finally:
        context.close()


def test_service_sets_use_short_lived_sessions_and_persist_successful_writes(
    application_context: ApplicationContext,
) -> None:
    with application_context.services() as first_services:
        customer = first_services.customer.create_customer("Composed Customer")
        customer_id = customer.id
        first_session = object_session(customer)
        assert first_session is not None

    assert object_session(customer) is None

    with application_context.services() as second_services:
        persisted_customer = second_services.customer.get_customer(customer_id)
        assert object_session(persisted_customer) is not first_session
        assert persisted_customer.full_name == "Composed Customer"


def test_application_context_reports_unusable_data_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("blocking file", encoding="utf-8")

    with pytest.raises(ApplicationStartupError, match="application data directory"):
        create_application_context(file_path)
