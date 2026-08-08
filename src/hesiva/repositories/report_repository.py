from datetime import date

from sqlalchemy import case, extract, func, select
from sqlalchemy.orm import Session

from hesiva.models.customer import Customer
from hesiva.models.transaction import Transaction
from hesiva.read_models import (
    CustomerStatement,
    MonthlySummary,
    StatementRow,
    YearlyMonthSummary,
    YearlySummary,
)


class ReportRepository:
    """Run bounded, set-based read queries for V1 financial reports."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_customer_statement(
        self,
        customer_id: int,
        *,
        period_start: date,
        period_end: date,
    ) -> CustomerStatement | None:
        current_balance = (
            select(func.coalesce(func.sum(Transaction.amount_kurus), 0))
            .where(
                Transaction.customer_id == Customer.id,
                Transaction.voided_at.is_(None),
            )
            .correlate(Customer)
            .scalar_subquery()
        )
        opening_balance = (
            select(func.coalesce(func.sum(Transaction.amount_kurus), 0))
            .where(
                Transaction.customer_id == Customer.id,
                Transaction.voided_at.is_(None),
                Transaction.transaction_date < period_start,
            )
            .correlate(Customer)
            .scalar_subquery()
        )
        period_debt = (
            select(func.coalesce(func.sum(Transaction.amount_kurus), 0))
            .where(
                Transaction.customer_id == Customer.id,
                Transaction.voided_at.is_(None),
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
                Transaction.amount_kurus > 0,
            )
            .correlate(Customer)
            .scalar_subquery()
        )
        period_payment = (
            select(func.coalesce(-func.sum(Transaction.amount_kurus), 0))
            .where(
                Transaction.customer_id == Customer.id,
                Transaction.voided_at.is_(None),
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
                Transaction.amount_kurus < 0,
            )
            .correlate(Customer)
            .scalar_subquery()
        )
        customer_statement = select(
            Customer.id,
            Customer.full_name,
            Customer.phone,
            opening_balance.label("opening_balance_kurus"),
            period_debt.label("total_debt_kurus"),
            period_payment.label("total_payment_kurus"),
            current_balance.label("current_balance_kurus"),
        ).where(Customer.id == customer_id, Customer.archived_at.is_(None))
        customer_row = self._session.execute(customer_statement).one_or_none()
        if customer_row is None:
            return None

        chronological_balance = int(customer_row.opening_balance_kurus) + func.sum(
            Transaction.amount_kurus
        ).over(
            order_by=(
                Transaction.transaction_date.asc(),
                Transaction.transaction_time.asc().nulls_first(),
                Transaction.id.asc(),
            ),
            rows=(None, 0),
        )
        rows_statement = (
            select(
                Transaction.id,
                Transaction.transaction_date,
                Transaction.transaction_time,
                Transaction.description,
                Transaction.amount_kurus,
                chronological_balance.label("running_balance_kurus"),
            )
            .where(
                Transaction.customer_id == customer_id,
                Transaction.voided_at.is_(None),
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end,
            )
            .order_by(
                Transaction.transaction_date.desc(),
                Transaction.transaction_time.desc().nulls_last(),
                Transaction.id.desc(),
            )
        )
        rows = tuple(
            StatementRow(
                transaction_id=row.id,
                transaction_date=row.transaction_date,
                transaction_time=row.transaction_time,
                description=row.description,
                amount_kurus=int(row.amount_kurus),
                running_balance_kurus=int(row.running_balance_kurus),
            )
            for row in self._session.execute(rows_statement)
        )
        return CustomerStatement(
            customer_id=customer_row.id,
            full_name=customer_row.full_name,
            phone=customer_row.phone,
            period_start=period_start,
            period_end=period_end,
            opening_balance_kurus=int(customer_row.opening_balance_kurus),
            total_debt_kurus=int(customer_row.total_debt_kurus),
            total_payment_kurus=int(customer_row.total_payment_kurus),
            current_balance_kurus=int(customer_row.current_balance_kurus),
            rows=rows,
        )

    def get_monthly_summary(
        self,
        *,
        year: int,
        month: int,
        period_start: date,
        period_end: date,
    ) -> MonthlySummary:
        debt, payment, net = self._session.execute(
            self._period_totals_statement(period_start, period_end)
        ).one()
        return MonthlySummary(
            year=year,
            month=month,
            debt_kurus=int(debt),
            payment_kurus=int(payment),
            net_kurus=int(net),
        )

    def get_yearly_summary(
        self,
        *,
        year: int,
        period_start: date,
        period_end: date,
    ) -> YearlySummary:
        month_number = extract("month", Transaction.transaction_date)
        debt = func.coalesce(
            func.sum(case((Transaction.amount_kurus > 0, Transaction.amount_kurus), else_=0)),
            0,
        )
        payment = func.coalesce(
            func.sum(case((Transaction.amount_kurus < 0, -Transaction.amount_kurus), else_=0)),
            0,
        )
        net = func.coalesce(func.sum(Transaction.amount_kurus), 0)
        statement = (
            select(
                month_number.label("month"),
                debt.label("debt_kurus"),
                payment.label("payment_kurus"),
                net.label("net_kurus"),
            )
            .where(
                Transaction.voided_at.is_(None),
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date < period_end,
            )
            .group_by(month_number)
            .order_by(month_number)
        )
        populated = {
            int(row.month): YearlyMonthSummary(
                month=int(row.month),
                debt_kurus=int(row.debt_kurus),
                payment_kurus=int(row.payment_kurus),
                net_kurus=int(row.net_kurus),
            )
            for row in self._session.execute(statement)
        }
        months = tuple(
            populated.get(
                month,
                YearlyMonthSummary(month=month, debt_kurus=0, payment_kurus=0, net_kurus=0),
            )
            for month in range(1, 13)
        )
        return YearlySummary(
            year=year,
            debt_kurus=sum(row.debt_kurus for row in months),
            payment_kurus=sum(row.payment_kurus for row in months),
            net_kurus=sum(row.net_kurus for row in months),
            months=months,
        )

    @staticmethod
    def _period_totals_statement(period_start: date, period_end: date):
        return select(
            func.coalesce(
                func.sum(case((Transaction.amount_kurus > 0, Transaction.amount_kurus), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((Transaction.amount_kurus < 0, -Transaction.amount_kurus), else_=0)),
                0,
            ),
            func.coalesce(func.sum(Transaction.amount_kurus), 0),
        ).where(
            Transaction.voided_at.is_(None),
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date < period_end,
        )
