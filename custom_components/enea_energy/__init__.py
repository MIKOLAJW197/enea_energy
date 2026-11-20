"""Enea Energy integration for Home Assistant (Portal Odbiorcy)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv

from .const import CONF_METER_ID, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import EneaEnergyCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS: list[str] = ["sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry data across schema versions."""
    version = entry.version

    # v1–v5 were eBOK / cookie based. v6 switches to Portal Odbiorcy credentials.
    if version < 6:
        from .const import CONF_EXPORT_RECOVERY_PERCENT, CONF_START_DATE

        old = dict(entry.data)
        data = {
            CONF_USERNAME: str(old.get(CONF_USERNAME) or "").strip(),
            CONF_PASSWORD: "",
        }
        if old.get(CONF_START_DATE):
            data[CONF_START_DATE] = old[CONF_START_DATE]
        if old.get(CONF_EXPORT_RECOVERY_PERCENT) is not None:
            data[CONF_EXPORT_RECOVERY_PERCENT] = old[CONF_EXPORT_RECOVERY_PERCENT]
        hass.config_entries.async_update_entry(entry, data=data, version=6)
        return True

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not str(entry.data.get(CONF_USERNAME) or "").strip() or not entry.data.get(
        CONF_PASSWORD
    ):
        raise ConfigEntryAuthFailed(
            "Podaj e-mail i hasło do Portalu Odbiorcy Enea "
            "(portalodbiorcy.operator.enea.pl)."
        )
    if entry.data.get(CONF_METER_ID) is None:
        raise ConfigEntryAuthFailed("Brak wybranego punktu poboru (meter_id).")

    coordinator = EneaEnergyCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    if DOMAIN in hass.data:
        coordinator: EneaEnergyCoordinator | None = hass.data[DOMAIN].pop(
            entry.entry_id, None
        )
        if coordinator is not None:
            await coordinator.async_shutdown_client()
    return True
