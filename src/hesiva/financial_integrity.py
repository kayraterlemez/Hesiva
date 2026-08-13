from collections.abc import Iterable
from dataclasses import dataclass


SQLITE_SIGNED_INTEGER_MAX = (1 << 63) - 1


class FinancialIntegrityError(ValueError):
    """Raised when signed-kuruş data cannot be aggregated exactly by SQLite."""


@dataclass(frozen=True, slots=True)
class ActiveFinancialTotals:
    debt_kurus: int
    payment_kurus: int

    def including(self, amount_kurus: int) -> "ActiveFinancialTotals":
        amount = validate_transaction_amount(amount_kurus)
        if amount > 0:
            return ActiveFinancialTotals(
                debt_kurus=_checked_magnitude_sum(self.debt_kurus, amount),
                payment_kurus=self.payment_kurus,
            )
        return ActiveFinancialTotals(
            debt_kurus=self.debt_kurus,
            payment_kurus=_checked_magnitude_sum(self.payment_kurus, -amount),
        )


def validate_positive_magnitude(amount_kurus: object) -> int:
    if type(amount_kurus) is not int or not 0 < amount_kurus <= SQLITE_SIGNED_INTEGER_MAX:
        raise FinancialIntegrityError(
            "The amount must be a positive SQLite signed-integer magnitude."
        )
    return amount_kurus


def validate_transaction_amount(amount_kurus: object) -> int:
    if (
        type(amount_kurus) is not int
        or amount_kurus == 0
        or not -SQLITE_SIGNED_INTEGER_MAX <= amount_kurus <= SQLITE_SIGNED_INTEGER_MAX
    ):
        raise FinancialIntegrityError(
            "The transaction amount is outside the exact signed-kuruş range."
        )
    return amount_kurus


def calculate_active_financial_totals(
    amounts_kurus: Iterable[object],
) -> ActiveFinancialTotals:
    """Validate active movements without asking SQLite to perform an unsafe SUM."""
    totals = ActiveFinancialTotals(debt_kurus=0, payment_kurus=0)
    for amount_kurus in amounts_kurus:
        totals = totals.including(validate_transaction_amount(amount_kurus))
    return totals


def _checked_magnitude_sum(current_kurus: int, amount_kurus: int) -> int:
    if amount_kurus > SQLITE_SIGNED_INTEGER_MAX - current_kurus:
        raise FinancialIntegrityError(
            "The active financial total exceeds SQLite's exact signed-integer range."
        )
    return current_kurus + amount_kurus
