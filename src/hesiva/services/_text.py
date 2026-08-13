from hesiva import data_limits
from hesiva.services.exceptions import ValidationError


def normalize_required_text(value: str, field_name: str) -> str:
    """Strip required text and reject values with no visible content."""
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text.")

    normalized_value = value.strip()
    if not normalized_value:
        raise ValidationError(f"{field_name} must not be empty.")
    _validate_persisted_text_size(normalized_value, field_name)
    return normalized_value


def normalize_optional_text(value: str | None, field_name: str) -> str | None:
    """Strip optional text and convert empty values to None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text or None.")

    normalized_value = value.strip() or None
    if normalized_value is not None:
        _validate_persisted_text_size(normalized_value, field_name)
    return normalized_value


def _validate_persisted_text_size(value: str, field_name: str) -> None:
    if len(value) > data_limits.PERSISTED_USER_TEXT_MAX_BYTES:
        raise ValidationError(f"{field_name} exceeds the supported UTF-8 size limit.")
    try:
        encoded_size = len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ValidationError(f"{field_name} must be valid Unicode text.") from error
    if encoded_size > data_limits.PERSISTED_USER_TEXT_MAX_BYTES:
        raise ValidationError(f"{field_name} exceeds the supported UTF-8 size limit.")
