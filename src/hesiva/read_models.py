"""Typed, persistence-independent read models used by application-facing queries."""

from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum


class CustomerSummarySort(StrEnum):
    """Supported deterministic orderings for the active customer summary list."""

    HIGHEST_DEBT = "highest_debt"
    NAME = "name"
    LAST_TRANSACTION = "last_transaction"
    REGISTERED_ON = "registered_on"


@dataclass(frozen=True, slots=True)
class CustomerSummary:
    """Immutable raw data needed to render one customer-list row."""

    customer_id: int
    full_name: str
    balance_kurus: int
    registered_on: date | None
    last_transaction_date: date | None
    last_transaction_time: time | None


@dataclass(frozen=True, slots=True)
class CustomerDetail:
    """Immutable raw data needed to render the active customer's General tab."""

    customer_id: int
    full_name: str
    phone: str | None
    address: str | None
    notes: str | None
    registered_on: date | None
    total_debt_kurus: int
    total_payment_kurus: int
    balance_kurus: int
    last_transaction_date: date | None
    last_transaction_time: time | None
