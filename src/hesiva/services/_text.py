from hesiva.services.exceptions import ValidationError


def normalize_required_text(value: str, field_name: str) -> str:
    """Strip required text and reject values with no visible content."""
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text.")

    normalized_value = value.strip()
    if not normalized_value:
        raise ValidationError(f"{field_name} must not be empty.")
    return normalized_value


def normalize_optional_text(value: str | None, field_name: str) -> str | None:
    """Strip optional text and convert empty values to None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text or None.")

    return value.strip() or None
