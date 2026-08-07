from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC time as a naive value for SQLite storage."""
    return datetime.now(UTC).replace(tzinfo=None)
