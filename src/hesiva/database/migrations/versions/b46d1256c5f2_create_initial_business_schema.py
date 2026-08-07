"""create initial business schema

Revision ID: b46d1256c5f2
Revises:
Create Date: 2026-08-07 20:27:35.843936

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b46d1256c5f2"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the database schema."""
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("legacy_id", sa.Integer(), nullable=True),
        sa.Column("registered_on", sa.Date(), nullable=True),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customers_full_name"), "customers", ["full_name"], unique=False)
    op.create_index(op.f("ix_customers_legacy_id"), "customers", ["legacy_id"], unique=False)
    op.create_table(
        "animals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("ear_tag", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("species", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_animals_customer_id"), "animals", ["customer_id"], unique=False)
    op.create_index(op.f("ix_animals_ear_tag"), "animals", ["ear_tag"], unique=False)
    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("remind_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reminders_customer_id"), "reminders", ["customer_id"], unique=False)
    op.create_index(op.f("ix_reminders_remind_on"), "reminders", ["remind_on"], unique=False)
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("animal_id", sa.Integer(), nullable=True),
        sa.Column("legacy_id", sa.Integer(), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("transaction_time", sa.Time(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("amount_kurus != 0", name="ck_transactions_amount_kurus_nonzero"),
        sa.ForeignKeyConstraint(
            ["animal_id"],
            ["animals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transactions_animal_id"), "transactions", ["animal_id"], unique=False)
    op.create_index(
        op.f("ix_transactions_customer_id"), "transactions", ["customer_id"], unique=False
    )
    op.create_index(op.f("ix_transactions_legacy_id"), "transactions", ["legacy_id"], unique=False)
    op.create_index(
        op.f("ix_transactions_transaction_date"), "transactions", ["transaction_date"], unique=False
    )


def downgrade() -> None:
    """Downgrade the database schema."""
    op.drop_index(op.f("ix_transactions_transaction_date"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_legacy_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_customer_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_animal_id"), table_name="transactions")
    op.drop_table("transactions")
    op.drop_index(op.f("ix_reminders_remind_on"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_customer_id"), table_name="reminders")
    op.drop_table("reminders")
    op.drop_index(op.f("ix_animals_ear_tag"), table_name="animals")
    op.drop_index(op.f("ix_animals_customer_id"), table_name="animals")
    op.drop_table("animals")
    op.drop_index(op.f("ix_customers_legacy_id"), table_name="customers")
    op.drop_index(op.f("ix_customers_full_name"), table_name="customers")
    op.drop_table("customers")
