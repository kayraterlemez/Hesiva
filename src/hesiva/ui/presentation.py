"""Small deterministic formatters for Hesiva UI values."""

from datetime import date, time


def format_balance_kurus(balance_kurus: int) -> str:
    """Format a signed kuruş balance using the frozen Turkish UI terminology."""
    magnitude = abs(balance_kurus)
    lira, kurus = divmod(magnitude, 100)
    formatted_lira = f"{lira:,}".replace(",", ".")
    amount = f"{formatted_lira},{kurus:02d} TL"

    if balance_kurus > 0:
        return f"{amount} Borç"
    if balance_kurus < 0:
        return f"{amount} Fazla Ödeme"
    return amount


def format_transaction_moment(
    transaction_date: date | None,
    transaction_time: time | None,
) -> str:
    """Format an optional transaction date/time without inventing a missing time."""
    if transaction_date is None:
        return "-"

    formatted_date = transaction_date.strftime("%d.%m.%Y")
    if transaction_time is None:
        return formatted_date
    return f"{formatted_date} {transaction_time.strftime('%H:%M')}"
