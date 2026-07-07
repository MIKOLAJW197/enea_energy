"""Zapis godzinowych statystyk do recordera (async_add_external_statistics)."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def hour_start_local(hass: HomeAssistant, day: date, hour: int) -> datetime:
    """Początek przedziału godzinowego w strefie HA (hour: 0..23)."""
    tz = dt_util.get_time_zone(hass.config.time_zone)
    base = datetime.combine(day, time.min, tzinfo=tz)
    return base + timedelta(hours=hour)


def _build_metadata(*, statistic_id: str, name: str) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "statistic_id": statistic_id,
        "source": DOMAIN,
        "name": name,
        "unit_of_measurement": "kWh",
        "has_sum": True,
    }
    try:
        from homeassistant.components.recorder.models import StatisticMeanType

        meta["mean_type"] = StatisticMeanType.NONE
    except (ImportError, AttributeError):
        meta["has_mean"] = False
    meta["unit_class"] = None
    return meta


def async_add_hourly_cumulative_statistics(
    hass: HomeAssistant,
    *,
    statistic_id_import: str,
    statistic_id_export: str,
    points_imp: list[tuple[datetime, float]],
    points_exp: list[tuple[datetime, float]],
) -> None:
    """Dodaje punkty godzinowe: state i sum = skumulowane kWh od początku serii (total increasing).

    ``points_*`` — chronologicznie: (start UTC na pełnej godzinie, skumulowany_import / eksport).
    """
    if not points_imp and not points_exp:
        return

    try:
        from homeassistant.components.recorder.statistics import (
            async_add_external_statistics,
        )
    except ImportError:
        _LOGGER.warning("Recorder statistics niedostępne — pominięto zapis godzinowy")
        return

    meta_imp = _build_metadata(
        statistic_id=statistic_id_import,
        name="Enea — pobór z sieci (skumulowane, godz.)",
    )
    meta_exp = _build_metadata(
        statistic_id=statistic_id_export,
        name="Enea — oddanie (skumulowane po współcz. odbioru, godz.)",
    )

    def _rows(points: list[tuple[datetime, float]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for start, cum in points:
            su = dt_util.as_utc(start)
            if su.minute or su.second or su.microsecond:
                _LOGGER.error(
                    "Punkt statystyki musi być na pełnej godzinie UTC (pomijam): %s",
                    su,
                )
                continue
            out.append({"start": su, "state": cum, "sum": cum})
        return out

    if points_imp:
        async_add_external_statistics(hass, meta_imp, _rows(points_imp))
    if points_exp:
        async_add_external_statistics(hass, meta_exp, _rows(points_exp))
