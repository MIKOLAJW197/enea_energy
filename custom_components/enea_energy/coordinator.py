"""Coordinator: daily period totals from Portal Odbiorcy (po bilansowaniu)."""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXPORT_RECOVERY_PERCENT,
    CONF_METER_CODE,
    CONF_METER_ID,
    CONF_PASSWORD,
    CONF_START_DATE,
    CONF_USERNAME,
    DEFAULT_EXPORT_RECOVERY_PERCENT,
    DOMAIN,
)
from .enea_client import (
    EneaClient,
    EneaClientAuthError,
    EneaClientConfigError,
    EneaClientUnavailableError,
)
from .portal_parser import EneaPortalParseError, period_total_kwh

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _period_end(start: date) -> date:
    """Last day of the billing window: start → start + 1 year − 1 day."""
    year = start.year + 1
    day = min(start.day, monthrange(year, start.month)[1])
    return date(year, start.month, day) - timedelta(days=1)


class EneaEnergyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch period import/export totals once a day at 07:00."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self._meter_id = int(entry.data[CONF_METER_ID])
        self._meter_code = str(entry.data.get(CONF_METER_CODE) or self._meter_id)
        self._start_date = date.fromisoformat(entry.data[CONF_START_DATE])
        pct = int(entry.data.get(CONF_EXPORT_RECOVERY_PERCENT, DEFAULT_EXPORT_RECOVERY_PERCENT))
        self._export_recovery_ratio = max(0.0, min(1.0, pct / 100.0))
        self._client = EneaClient(
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            meter_id=self._meter_id,
        )

        # Daily 07:00 refresh is scheduled from __init__.py.
        super().__init__(hass, _LOGGER, name=DOMAIN)

    async def async_shutdown_client(self) -> None:
        await self._client.close()

    async def _async_ensure_client(self) -> EneaClient:
        try:
            await self._client.async_validate()
        except EneaClientAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EneaClientConfigError as err:
            raise UpdateFailed(str(err)) from err
        except EneaClientUnavailableError as err:
            raise UpdateFailed(str(err)) from err
        return self._client

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.entry.title,
            manufacturer="Enea Operator",
            model=f"PPE {self._meter_code}",
        )

    async def _async_refresh_period_start_from_portal(self) -> date:
        try:
            client = await self._async_ensure_client()
            portal_start = await client.async_billing_period_start()
        except (ConfigEntryAuthFailed, UpdateFailed, EneaClientConfigError) as err:
            _LOGGER.debug("Enea: billing period from portal unavailable: %s", err)
            return self._start_date

        if portal_start != self._start_date:
            _LOGGER.info(
                "Enea: portal billing period start is now %s (was %s)",
                portal_start.isoformat(),
                self._start_date.isoformat(),
            )
            self._start_date = portal_start
            new_data = {**self.entry.data, CONF_START_DATE: portal_start.isoformat()}
            self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        return portal_start

    async def _async_update_data(self) -> dict[str, Any]:
        period_start = await self._async_refresh_period_start_from_portal()
        period_end = _period_end(period_start)

        _LOGGER.info(
            "Enea portal: period totals %s → %s (po bilansowaniu)",
            period_start.isoformat(),
            period_end.isoformat(),
        )

        client = await self._async_ensure_client()
        try:
            consumed, returned = await client.async_fetch_energy_range(
                period_start, period_end, after_balancing=True
            )
            period_imp = period_total_kwh(consumed)
            period_exp = period_total_kwh(returned)
        except EneaClientAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (EneaClientUnavailableError, EneaClientConfigError) as err:
            raise UpdateFailed(str(err)) from err
        except EneaPortalParseError as err:
            raise UpdateFailed(str(err)) from err

        balance = period_exp * self._export_recovery_ratio - period_imp
        _LOGGER.info(
            "Enea: period import=%.3f export=%.3f balance=%.3f kWh (recovery %s%%)",
            period_imp,
            period_exp,
            balance,
            round(self._export_recovery_ratio * 100),
        )

        return {
            "configured_start_date": period_start.isoformat(),
            "balance_period_start": period_start.isoformat(),
            "balance_period_end": period_end.isoformat(),
            "period_import_kwh": period_imp,
            "period_export_kwh": period_exp,
            "energy_balance_kwh": balance,
            "export_recovery_percent": round(self._export_recovery_ratio * 100),
            "meter_id": self._meter_id,
            "meter_code": self._meter_code,
            "refreshed_at": dt_util.now().isoformat(),
        }
