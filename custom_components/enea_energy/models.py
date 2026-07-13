"""Shared data types for the integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyEnergyRow:
    """Aggregated kWh for one day plus optional hourly values from the eBOK chart."""

    day: date
    import_kwh: float
    export_kwh: float
    hourly_import_kwh: tuple[float, ...] = ()
    hourly_export_kwh: tuple[float, ...] = ()
    # API returned [] — day not published yet (do not treat as 0 kWh).
    no_data: bool = False
