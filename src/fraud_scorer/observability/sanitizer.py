"""Client-side PII and PCI-DSS payload sanitizer for telemetry and distributed tracing (PRD-018)."""

import re
from typing import Any

# Regex matching 13 to 19 digit Primary Account Numbers (PANs), optionally separated by spaces or hyphens
_PAN_REGEX = re.compile(r"\b(?:\d[ -]*?){12,18}\d\b")

# Sensitive dictionary keys that must be masked before leaving the application boundary
_REDACTED_EXACT_KEYS = frozenset(
    {
        "pan",
        "card_number",
        "full_pan",
        "primary_account_number",
        "cvv",
        "cvc",
        "cvv2",
        "security_code",
        "pin",
        "account_number",
        "bank_account_number",
        "iban",
        "ssn",
        "social_security_number",
        "tax_id",
        "password",
        "secret",
        "api_key",
        "access_token",
    }
)

_ADDRESS_AND_NAME_KEYS = frozenset(
    {
        "address",
        "street",
        "street_address",
        "billing_address",
        "billing_street",
        "shipping_address",
        "full_name",
        "customer_name",
        "cardholder_name",
        "email",
        "phone",
        "phone_number",
    }
)

_PARTIAL_MASK_KEYS = frozenset(
    {
        "routing_number",
        "ip",
        "ip_address",
    }
)


def mask_pan(text: str) -> str:
    """Replace 13-to-19 digit card numbers in a string with ****-****-****-1234 format."""
    if not text:
        return text

    def _replacer(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = "".join(ch for ch in raw if ch.isdigit())
        if 13 <= len(digits) <= 19:
            return f"****-****-****-{digits[-4:]}"
        return raw

    return _PAN_REGEX.sub(_replacer, text)


def _mask_ip(ip_str: str) -> str:
    """Mask the last octet/segment of an IPv4 or IPv6 address."""
    clean = ip_str.strip()
    if "." in clean:
        parts = clean.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.***"
    if ":" in clean:
        parts = clean.split(":")
        if len(parts) > 2:
            return ":".join(parts[:-1]) + ":****"
    return "***"


def _sanitize_value(key: str | None, value: Any) -> Any:
    """Recursively sanitize a value based on its field name and type."""
    norm_key = key.lower().strip() if key else ""

    if value is None:
        return None

    if norm_key in _REDACTED_EXACT_KEYS:
        if isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if 13 <= len(digits) <= 19:
                return f"****-****-****-{digits[-4:]}"
        return "***REDACTED***"

    if norm_key in _ADDRESS_AND_NAME_KEYS:
        return "***REDACTED_PII***"

    if norm_key in _PARTIAL_MASK_KEYS and isinstance(value, str):
        if "ip" in norm_key:
            return _mask_ip(value)
        if len(value) >= 4:
            return f"*****{value[-4:]}"
        return "***REDACTED***"

    if isinstance(value, dict):
        return {str(k): _sanitize_value(str(k), v) for k, v in value.items()}

    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_value(key, item) for item in value)

    if isinstance(value, str):
        return mask_pan(value)

    return value


def sanitize_transaction_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively scrub PCI-DSS and PII fields from a transaction dictionary while preserving risk metadata."""
    if not isinstance(data, dict):
        return {}
    return {str(k): _sanitize_value(str(k), v) for k, v in data.items()}


# Alias for package exports
sanitize_payload = sanitize_transaction_payload
