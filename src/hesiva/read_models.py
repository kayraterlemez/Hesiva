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
class ReminderSummary:
    """Immutable reminder data used by active and inactive customer workflows."""

    reminder_id: int
    customer_id: int
    remind_on: date
    note: str
    completed_at: datetime | None
    cancelled_at: datetime | None


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


@dataclass(frozen=True, slots=True)
class StatementRow:
    """One active customer-statement movement with its lifetime running balance."""

    transaction_id: int
    transaction_date: date
    transaction_time: time | None
    description: str
    amount_kurus: int
    running_balance_kurus: int


@dataclass(frozen=True, slots=True)
class CustomerStatement:
    """Immutable date-ranged statement for one active customer."""

    customer_id: int
    full_name: str
    phone: str | None
    period_start: date
    period_end: date
    opening_balance_kurus: int
    total_debt_kurus: int
    total_payment_kurus: int
    current_balance_kurus: int
    rows: tuple[StatementRow, ...]


@dataclass(frozen=True, slots=True)
class MonthlySummary:
    """Application-wide active financial totals for one calendar month."""

    year: int
    month: int
    debt_kurus: int
    payment_kurus: int
    net_kurus: int


@dataclass(frozen=True, slots=True)
class YearlyMonthSummary:
    """One calendar month's active totals in a yearly report."""

    month: int
    debt_kurus: int
    payment_kurus: int
    net_kurus: int


@dataclass(frozen=True, slots=True)
class YearlySummary:
    """Application-wide yearly totals and deterministic January-December rows."""

    year: int
    debt_kurus: int
    payment_kurus: int
    net_kurus: int
    months: tuple[YearlyMonthSummary, ...]
