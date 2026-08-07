from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hesiva.database.base import Base
from hesiva.models._timestamps import utc_now

if TYPE_CHECKING:
    from hesiva.models.animal import Animal
    from hesiva.models.customer import Customer


class Transaction(Base):
    """One signed financial movement in a customer's account."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "amount_kurus != 0",
            name="ck_transactions_amount_kurus_nonzero",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id"),
        nullable=False,
        index=True,
    )
    animal_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("animals.id"),
        nullable=True,
        index=True,
    )
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    transaction_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="transactions")
    animal: Mapped[Animal | None] = relationship(back_populates="transactions")
