"""Integracja Enea Energy dla Home Assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import config_validation as cv

from .const import CONF_POINT_OF_DELIVERY_ID, DOMAIN
from .coordinator import EneaEnergyCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS: list[str] = []

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """v1 → v2: pole point_of_delivery_id (puste do uzupełnienia w konfiguracji)."""
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_POINT_OF_DELIVERY_ID: entry.data.get(CONF_POINT_OF_DELIVERY_ID, ""),
            },
            version=2,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = EneaEnergyCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

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
