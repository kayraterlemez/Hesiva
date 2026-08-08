"""Small deterministic formatters for Hesiva UI values."""

import re
from datetime import date, time


class MoneyInputError(ValueError):
    """Raised when a Turkish-formatted positive money magnitude is invalid."""


def parse_money_kurus(value: str) -> int:
    """Parse a strict positive Turkish lira magnitude without floating point."""
    normalized = value.strip()
    if not normalized:
        raise MoneyInputError("Tutar boş bırakılamaz.")
    if normalized.startswith(("+", "-")) or normalized.count(",") > 1:
        raise MoneyInputError("Tutar pozitif bir sayı olmalıdır.")

    whole_part, separator, fraction_part = normalized.partition(",")
    if "." in whole_part:
        valid_whole = re.fullmatch(r"\d{1,3}(?:\.\d{3})+", whole_part)
    else:
        valid_whole = re.fullmatch(r"\d+", whole_part)
    if valid_whole is None:
        raise MoneyInputError("Tutar biçimi geçersiz.")
    if separator and re.fullmatch(r"\d{1,2}", fraction_part) is None:
        raise MoneyInputError("Kuruş en fazla iki basamak olmalıdır.")

    lira = int(whole_part.replace(".", ""))
    kurus = int(fraction_part.ljust(2, "0")) if separator else 0
    amount_kurus = lira * 100 + kurus
    if amount_kurus <= 0:
        raise MoneyInputError("Tutar sıfırdan büyük olmalıdır.")
    return amount_kurus


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


def format_animal_display(
    ear_tag: str | None,
    name: str | None,
    species: str | None,
) -> str:
    """Build a restrained animal label from existing V1 identifying fields."""
    identifiers = [part for part in (ear_tag, name) if part]
    if identifiers:
        return " — ".join(identifiers)
    if species:
        return species
    return "Tanımsız Hayvan"


def format_animal_identity(
    ear_tag: str | None,
    name: str | None,
    species: str | None,
) -> str:
    """Build a deterministic user-facing identity without exposing a database ID."""
    if ear_tag and name:
        return f"{ear_tag} — {name}"
    return name or ear_tag or species or "Adsız hayvan"


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
