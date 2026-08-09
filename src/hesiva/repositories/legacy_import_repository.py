from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import case, func, insert, select, text
from sqlalchemy.orm import Session

from hesiva.models.animal import Animal
from hesiva.models.customer import Customer
from hesiva.models.reminder import Reminder
from hesiva.models.transaction import Transaction


IMPORT_BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class BusinessRecordCounts:
    customers: int
    animals: int
    transactions: int
    reminders: int

    @property
    def is_empty(self) -> bool:
        return not any((self.customers, self.animals, self.transactions, self.reminders))


@dataclass(frozen=True, slots=True)
class ImportedCustomerTotals:
    customer_legacy_id: int
    debt_kurus: int
    payment_kurus: int
    signed_net_kurus: int


@dataclass(frozen=True, slots=True)
class DestinationImportSnapshot:
    customer_count: int
    transaction_count: int
    distinct_customer_legacy_ids: int
    distinct_transaction_legacy_ids: int
    null_customer_legacy_ids: int
    null_transaction_legacy_ids: int
    zero_transaction_count: int
    debt_kurus: int
    payment_kurus: int
    signed_net_kurus: int
    per_customer: tuple[ImportedCustomerTotals, ...]
    foreign_key_violation_count: int


class LegacyImportRepository:
    """Perform bounded destination operations for one caller-owned import transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def business_record_counts(self) -> BusinessRecordCounts:
        return BusinessRecordCounts(
            customers=self._count(Customer),
            animals=self._count(Animal),
            transactions=self._count(Transaction),
            reminders=self._count(Reminder),
        )

    def add_customers(self, customers: Sequence[Customer]) -> dict[int, int]:
        self._session.add_all(customers)
        self._session.flush()
        return {
            customer.legacy_id: customer.id
            for customer in customers
            if customer.legacy_id is not None
        }

    def add_transactions(self, rows: Sequence[Mapping[str, object]]) -> None:
        statement = insert(Transaction)
        for start in range(0, len(rows), IMPORT_BATCH_SIZE):
            self._session.execute(statement, rows[start : start + IMPORT_BATCH_SIZE])
        self._session.flush()

    def destination_snapshot(self) -> DestinationImportSnapshot:
        debt = func.coalesce(
            func.sum(case((Transaction.amount_kurus > 0, Transaction.amount_kurus), else_=0)),
            0,
        )
        payment = func.coalesce(
            func.sum(case((Transaction.amount_kurus < 0, -Transaction.amount_kurus), else_=0)),
            0,
        )
        net = func.coalesce(func.sum(Transaction.amount_kurus), 0)
        customer_rows = self._session.execute(
            select(
                Customer.legacy_id,
                debt.label("debt_kurus"),
                payment.label("payment_kurus"),
                net.label("signed_net_kurus"),
            )
            .outerjoin(Transaction, Transaction.customer_id == Customer.id)
            .group_by(Customer.id)
            .order_by(Customer.legacy_id)
        )
        per_customer = tuple(
            ImportedCustomerTotals(
                customer_legacy_id=int(row.legacy_id),
                debt_kurus=int(row.debt_kurus),
                payment_kurus=int(row.payment_kurus),
                signed_net_kurus=int(row.signed_net_kurus),
            )
            for row in customer_rows
            if row.legacy_id is not None
        )
        global_row = self._session.execute(
            select(
                debt.label("debt_kurus"),
                payment.label("payment_kurus"),
                net.label("signed_net_kurus"),
            )
        ).one()
        foreign_key_violations = self._session.execute(text("PRAGMA foreign_key_check")).all()
        return DestinationImportSnapshot(
            customer_count=self._count(Customer),
            transaction_count=self._count(Transaction),
            distinct_customer_legacy_ids=self._distinct_count(Customer.legacy_id),
            distinct_transaction_legacy_ids=self._distinct_count(Transaction.legacy_id),
            null_customer_legacy_ids=self._null_count(Customer.legacy_id),
            null_transaction_legacy_ids=self._null_count(Transaction.legacy_id),
            zero_transaction_count=int(
                self._session.scalar(
                    select(func.count())
                    .select_from(Transaction)
                    .where(Transaction.amount_kurus == 0)
                )
            ),
            debt_kurus=int(global_row.debt_kurus),
            payment_kurus=int(global_row.payment_kurus),
            signed_net_kurus=int(global_row.signed_net_kurus),
            per_customer=per_customer,
            foreign_key_violation_count=len(foreign_key_violations),
        )

    def _count(
        self, model: type[Customer] | type[Animal] | type[Transaction] | type[Reminder]
    ) -> int:
        return int(self._session.scalar(select(func.count()).select_from(model)))

    def _distinct_count(self, column: object) -> int:
        return int(self._session.scalar(select(func.count(func.distinct(column)))))

    def _null_count(self, column: object) -> int:
        return int(self._session.scalar(select(func.count()).where(column.is_(None))))
