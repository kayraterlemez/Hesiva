"""Bounded semantic validation shared by live startup and backup restore."""

import sqlite3
from datetime import date, datetime, time

from hesiva import data_limits
from hesiva.financial_integrity import (
    FinancialIntegrityError,
    calculate_active_financial_totals,
)

MAX_BUSINESS_ROWS_PER_TABLE = 1_000_000


def find_database_semantic_error(connection: sqlite3.Connection) -> str | None:
    """Return the first invalid V1 data category without exposing row values."""
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        return "foreign-key"

    for table_name in ("customers", "animals", "transactions", "reminders"):
        row_count = connection.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()
        if row_count is None or row_count[0] > MAX_BUSINESS_ROWS_PER_TABLE:
            return f"{table_name} row-count"

    scalar_checks = (
        (
            "customer",
            "SELECT 1 FROM customers WHERE "
            "typeof(id) != 'integer' OR "
            "(legacy_id IS NOT NULL AND typeof(legacy_id) != 'integer') OR "
            "typeof(full_name) != 'text' OR trim(full_name) = '' OR "
            "(registered_on IS NOT NULL AND typeof(registered_on) != 'text') OR "
            "(phone IS NOT NULL AND typeof(phone) != 'text') OR "
            "(address IS NOT NULL AND typeof(address) != 'text') OR "
            "(notes IS NOT NULL AND typeof(notes) != 'text') OR "
            f"length(CAST(full_name AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(phone AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(address AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(notes AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(registered_on AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(created_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(updated_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(archived_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            "typeof(created_at) != 'text' OR typeof(updated_at) != 'text' OR "
            "(archived_at IS NOT NULL AND typeof(archived_at) != 'text') LIMIT 1",
        ),
        (
            "animal",
            "SELECT 1 FROM animals WHERE "
            "typeof(id) != 'integer' OR typeof(customer_id) != 'integer' OR "
            "(ear_tag IS NOT NULL AND typeof(ear_tag) != 'text') OR "
            "(name IS NOT NULL AND typeof(name) != 'text') OR "
            "(species IS NOT NULL AND typeof(species) != 'text') OR "
            "(notes IS NOT NULL AND typeof(notes) != 'text') OR "
            f"length(CAST(ear_tag AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(name AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(species AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(notes AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(created_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(updated_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(archived_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            "typeof(created_at) != 'text' OR typeof(updated_at) != 'text' OR "
            "(archived_at IS NOT NULL AND typeof(archived_at) != 'text') LIMIT 1",
        ),
        (
            "transaction",
            "SELECT 1 FROM transactions WHERE "
            "typeof(id) != 'integer' OR typeof(customer_id) != 'integer' OR "
            "(animal_id IS NOT NULL AND typeof(animal_id) != 'integer') OR "
            "(legacy_id IS NOT NULL AND typeof(legacy_id) != 'integer') OR "
            "typeof(transaction_date) != 'text' OR "
            "(transaction_time IS NOT NULL AND typeof(transaction_time) != 'text') OR "
            "typeof(description) != 'text' OR trim(description) = '' OR "
            "typeof(amount_kurus) != 'integer' OR amount_kurus = 0 OR "
            "amount_kurus < -9223372036854775807 OR "
            "(note IS NOT NULL AND typeof(note) != 'text') OR "
            f"length(CAST(description AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(note AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(void_reason AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(transaction_date AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(transaction_time AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(created_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(updated_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(voided_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            "typeof(created_at) != 'text' OR typeof(updated_at) != 'text' OR "
            "(voided_at IS NOT NULL AND typeof(voided_at) != 'text') OR "
            "(void_reason IS NOT NULL AND typeof(void_reason) != 'text') OR "
            "(void_reason IS NOT NULL AND voided_at IS NULL) LIMIT 1",
        ),
        (
            "reminder",
            "SELECT 1 FROM reminders WHERE "
            "typeof(id) != 'integer' OR typeof(customer_id) != 'integer' OR "
            "typeof(remind_on) != 'text' OR "
            "typeof(note) != 'text' OR trim(note) = '' OR "
            f"length(CAST(note AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(remind_on AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(created_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(updated_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(completed_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            f"length(CAST(cancelled_at AS BLOB)) > {data_limits.PERSISTED_USER_TEXT_MAX_BYTES} OR "
            "typeof(created_at) != 'text' OR typeof(updated_at) != 'text' OR "
            "(completed_at IS NOT NULL AND typeof(completed_at) != 'text') OR "
            "(cancelled_at IS NOT NULL AND typeof(cancelled_at) != 'text') OR "
            "(completed_at IS NOT NULL AND cancelled_at IS NOT NULL) LIMIT 1",
        ),
        (
            "transaction ownership",
            "SELECT 1 FROM transactions AS tx "
            "JOIN animals AS animal ON animal.id = tx.animal_id "
            "WHERE tx.customer_id != animal.customer_id LIMIT 1",
        ),
    )
    for category, statement in scalar_checks:
        if connection.execute(statement).fetchone() is not None:
            return category

    try:
        calculate_active_financial_totals(
            row[0]
            for row in connection.execute(
                "SELECT amount_kurus FROM transactions WHERE voided_at IS NULL"
            )
        )
    except FinancialIntegrityError:
        return "transaction aggregate"

    utf8_columns = (
        ("customers", "customer", ("full_name", "phone", "address", "notes")),
        ("animals", "animal", ("ear_tag", "name", "species", "notes")),
        ("transactions", "transaction", ("description", "note", "void_reason")),
        ("reminders", "reminder", ("note",)),
    )
    for table_name, category, columns in utf8_columns:
        projection = ", ".join(f'CAST("{column}" AS BLOB)' for column in columns)
        for row in connection.execute(f'SELECT {projection} FROM "{table_name}"'):
            for value in row:
                if value is not None and not _is_valid_utf8(value):
                    return category

    temporal_columns = (
        ("customers", "registered_on", "date", True),
        ("customers", "created_at", "datetime", False),
        ("customers", "updated_at", "datetime", False),
        ("customers", "archived_at", "datetime", True),
        ("animals", "created_at", "datetime", False),
        ("animals", "updated_at", "datetime", False),
        ("animals", "archived_at", "datetime", True),
        ("transactions", "transaction_date", "date", False),
        ("transactions", "transaction_time", "time", True),
        ("transactions", "created_at", "datetime", False),
        ("transactions", "updated_at", "datetime", False),
        ("transactions", "voided_at", "datetime", True),
        ("reminders", "remind_on", "date", False),
        ("reminders", "created_at", "datetime", False),
        ("reminders", "updated_at", "datetime", False),
        ("reminders", "completed_at", "datetime", True),
        ("reminders", "cancelled_at", "datetime", True),
    )
    for table_name, column_name, temporal_kind, nullable in temporal_columns:
        query = f'SELECT CAST("{column_name}" AS BLOB) FROM "{table_name}"'
        for (value,) in connection.execute(query):
            if value is None and nullable:
                continue
            if not _is_canonical_temporal_bytes(value, temporal_kind):
                return f"{table_name} date/time"
    return None


def _is_valid_utf8(value: object) -> bool:
    if not isinstance(value, bytes):
        return False
    try:
        value.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _is_canonical_temporal_bytes(value: object, temporal_kind: str) -> bool:
    if not isinstance(value, bytes):
        return False
    try:
        decoded_value = value.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return _is_canonical_temporal_text(decoded_value, temporal_kind)


def _is_canonical_temporal_text(value: str, temporal_kind: str) -> bool:
    """Accept only SQLite text forms emitted by Hesiva's SQLAlchemy date types."""
    try:
        if temporal_kind == "date":
            return date.fromisoformat(value).isoformat() == value
        if temporal_kind == "time":
            parsed_time = time.fromisoformat(value)
            return (
                parsed_time.tzinfo is None
                and parsed_time.isoformat(timespec="microseconds") == value
            )
        if temporal_kind == "datetime":
            parsed_datetime = datetime.fromisoformat(value)
            if parsed_datetime.tzinfo is not None:
                return False
            return value in {
                parsed_datetime.isoformat(sep=" ", timespec="seconds"),
                parsed_datetime.isoformat(sep=" ", timespec="microseconds"),
            }
    except ValueError:
        return False
    raise ValueError(f"Unknown temporal kind: {temporal_kind}")
