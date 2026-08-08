"""Small deterministic formatters for Hesiva UI values."""

from datetime import date, time


def format_money_kurus(amount_kurus: int) -> str:
    """Format a non-negative kuruş magnitude as Turkish-friendly TL text."""
    if amount_kurus < 0:
        raise ValueError("amount_kurus must be a non-negative magnitude")

    lira, kurus = divmod(amount_kurus, 100)
    formatted_lira = f"{lira:,}".replace(",", ".")
    return f"{formatted_lira},{kurus:02d} TL"


def format_balance_kurus(balance_kurus: int) -> str:
    """Format a signed kuruş balance using the frozen Turkish UI terminology."""
    amount = format_money_kurus(abs(balance_kurus))

    if balance_kurus > 0:
        return f"{amount} Borç"
    if balance_kurus < 0:
        return f"{amount} Fazla Ödeme"
    return amount


def format_date(value: date | None) -> str:
    """Format an optional date using the Turkish desktop convention."""
    if value is None:
        return "-"
    return value.strftime("%d.%m.%Y")


def format_transaction_moment(
    transaction_date: date | None,
    transaction_time: time | None,
) -> str:
    """Format an optional transaction date/time without inventing a missing time."""
    if transaction_date is None:
        return "-"

    formatted_date = format_date(transaction_date)
    if transaction_time is None:
        return formatted_date
    return f"{formatted_date} {transaction_time.strftime('%H:%M')}"
