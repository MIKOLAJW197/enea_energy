"""Integracja Enea Energy dla Home Assistant."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_POINT_OF_DELIVERY_ID,
    DAILY_CHECK_HOUR,
    DAILY_CHECK_MINUTE,
    DOMAIN,
)
from .coordinator import EneaEnergyCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS: list[str] = []

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LEGACY_UPDATE_INTERVAL_HOURS = "update_interval_hours"


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migracje wpisu konfiguracyjnego."""
    data = dict(entry.data)
    version = entry.version

    if version == 1:
        data.setdefault(CONF_POINT_OF_DELIVERY_ID, "")
        version = 2

    if version == 2:
        data.pop(_LEGACY_UPDATE_INTERVAL_HOURS, None)
        version = 3

    if version != entry.version:
        hass.config_entries.async_update_entry(entry, data=data, version=version)

    return True


def _schedule_daily_check(hass: HomeAssistant, entry: ConfigEntry, coordinator: EneaEnergyCoordinator) -> None:
    @callback
    def _daily_check(_now: datetime) -> None:
        hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(
        async_track_time_change(
            hass,
            _daily_check,
            hour=DAILY_CHECK_HOUR,
            minute=DAILY_CHECK_MINUTE,
            second=0,
        )
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = EneaEnergyCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    _schedule_daily_check(hass, entry, coordinator)
    await coordinator.async_config_entry_first_refresh()

    if PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if PLATFORMS:
        ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if not ok:
            return False
    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
