"""Parse Portal Odbiorcy period totals (no hourly breakdown)."""

from __future__ import annotations

from typing import Any


class EneaPortalParseError(ValueError):
    """Malformed portal consumption payload."""


def period_total_kwh(payload: dict[str, Any]) -> float:
    """Return ``sumConsumption`` for a range response (already in kWh)."""
    if not isinstance(payload, dict):
        raise EneaPortalParseError("Expected dict payload from portal")
    raw = payload.get("sumConsumption")
    if raw is None:
        raise EneaPortalParseError("Missing sumConsumption in portal response")
    try:
        return float(raw)
    except (TypeError, ValueError) as err:
        raise EneaPortalParseError(f"Bad sumConsumption: {raw!r}") from err
