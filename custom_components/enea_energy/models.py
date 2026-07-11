"""Wspólne typy danych integracji."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyEnergyRow:
    """Zagregowane kWh za jeden dzień + opcjonalne wartości godzinowe z wykresu eBOK."""

    day: date
    import_kwh: float
    export_kwh: float
    hourly_import_kwh: tuple[float, ...] = ()
    hourly_export_kwh: tuple[float, ...] = ()
    # API zwróciło [] — dzień jeszcze nieopublikowany (nie traktować jako 0 kWh).
    no_data: bool = False
