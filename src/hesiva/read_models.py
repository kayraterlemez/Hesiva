"""Typed, persistence-independent read models used by application-facing queries."""

from dataclasses import dataclass
from datetime import date, datetime, time
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


@dataclass(frozen=True, slots=True)
class ArchivedCustomer:
    """Immutable identifying data for the archived-customer workflow."""

    customer_id: int
    full_name: str
    phone: str | None
    registered_on: date | None


@dataclass(frozen=True, slots=True)
class AnimalOption:
    """Immutable active-animal data used by transaction selection controls."""

    animal_id: int
    ear_tag: str | None
    name: str | None
    species: str | None


@dataclass(frozen=True, slots=True)
class AnimalSummary:
    """Immutable animal data used by active and archived customer workflows."""

    animal_id: int
    customer_id: int
    ear_tag: str | None
    name: str | None
    species: str | None
    notes: str | None
    archived_at: datetime | None


@dataclass(frozen=True, slots=True)
class AccountHistoryRow:
    """One immutable financial-history row with its chronological running balance."""

    transaction_id: int
    transaction_date: date
    transaction_time: time | None
    description: str
    animal_id: int | None
    animal_ear_tag: str | None
    animal_name: str | None
    animal_species: str | None
    amount_kurus: int
    running_balance_kurus: int
    voided_at: datetime | None
    void_reason: str | None
