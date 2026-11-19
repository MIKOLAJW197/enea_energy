"""Config flow for the Enea Energy integration (Portal Odbiorcy)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .const import (
    CONF_EXPORT_RECOVERY_PERCENT,
    CONF_METER_CODE,
    CONF_METER_ID,
    CONF_PASSWORD,
    CONF_START_DATE,
    CONF_USERNAME,
    DEFAULT_EXPORT_RECOVERY_PERCENT,
    DOMAIN,
    EXPORT_RECOVERY_PERCENT_OPTIONS,
)
from .enea_client import (
    EneaClient,
    EneaClientAuthError,
    EneaClientConfigError,
    EneaClientUnavailableError,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_export_recovery_percent(value: Any) -> int:
    pct = int(value) if value is not None else DEFAULT_EXPORT_RECOVERY_PERCENT
    if pct not in EXPORT_RECOVERY_PERCENT_OPTIONS:
        return DEFAULT_EXPORT_RECOVERY_PERCENT
    return pct


class InvalidAuth(HomeAssistantError):
    """Bad credentials."""


class CannotConnect(HomeAssistantError):
    """Portal unreachable."""


class NoMeters(HomeAssistantError):
    """Account has no PPE."""


class NoBillingPeriod(HomeAssistantError):
    """Dashboard has no billing period start."""


async def _login_and_list_meters(username: str, password: str) -> list[dict[str, Any]]:
    client = EneaClient(username, password)
    try:
        meters = await client.async_list_meters()
    except EneaClientAuthError as err:
        raise InvalidAuth from err
    except EneaClientUnavailableError as err:
        raise CannotConnect from err
    finally:
        await client.close()

    if not meters:
        raise NoMeters
    return meters


async def _build_entry_data(
    *,
    username: str,
    password: str,
    meter_id: int,
    export_pct: int,
) -> dict[str, Any]:
    client = EneaClient(username, password, meter_id=meter_id)
    try:
        meter = await client.async_validate()
        start = await client.async_billing_period_start(meter_id)
    except EneaClientAuthError as err:
        raise InvalidAuth from err
    except EneaClientConfigError as err:
        msg = str(err).lower()
        if "billing period" in msg:
            raise NoBillingPeriod from err
        raise NoMeters from err
    except EneaClientUnavailableError as err:
        raise CannotConnect from err
    finally:
        await client.close()

    return {
        CONF_USERNAME: username,
        CONF_PASSWORD: password,
        CONF_METER_ID: int(meter["id"]),
        CONF_METER_CODE: str(meter.get("code") or meter["id"]),
        CONF_START_DATE: start.isoformat(),
        CONF_EXPORT_RECOVERY_PERCENT: export_pct,
    }


class EneaEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """E-mail / password / recovery % — start date comes from the portal."""

    VERSION = 6

    def __init__(self) -> None:
        self._username: str = ""
        self._password: str = ""
        self._meters: list[dict[str, Any]] = []
        self._export_pct: int = DEFAULT_EXPORT_RECOVERY_PERCENT

    def _user_schema(self) -> vol.Schema:
        username_field = (
            vol.Required(CONF_USERNAME, default=self._username)
            if self._username
            else vol.Required(CONF_USERNAME)
        )
        return vol.Schema(
            {
                username_field: str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_EXPORT_RECOVERY_PERCENT,
                    default=self._export_pct,
                ): vol.In(EXPORT_RECOVERY_PERCENT_OPTIONS),
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = str(user_input[CONF_USERNAME]).strip()
            self._password = str(user_input[CONF_PASSWORD])
            self._export_pct = _normalize_export_recovery_percent(
                user_input.get(CONF_EXPORT_RECOVERY_PERCENT)
            )
            try:
                self._meters = await _login_and_list_meters(
                    self._username, self._password
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except NoMeters:
                errors["base"] = "no_meters"
            except Exception:
                _LOGGER.exception("Enea Energy: unexpected error during login")
                errors["base"] = "cannot_connect"
            else:
                if len(self._meters) == 1:
                    return await self._async_create_from_meter(self._meters[0])
                return await self.async_step_meter()

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(),
            errors=errors,
        )

    async def async_step_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        options = {
            str(m["id"]): f"{m.get('code') or m['id']} (id {m['id']})"
            for m in self._meters
        }
        if user_input is not None:
            meter_id = str(user_input[CONF_METER_ID])
            meter = next((m for m in self._meters if str(m["id"]) == meter_id), None)
            if meter is None:
                errors["base"] = "no_meters"
            else:
                return await self._async_create_from_meter(meter)

        return self.async_show_form(
            step_id="meter",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_METER_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": k, "label": v} for k, v in options.items()
                            ],
                            mode="dropdown",
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_create_from_meter(self, meter: dict[str, Any]) -> FlowResult:
        try:
            data = await _build_entry_data(
                username=self._username,
                password=self._password,
                meter_id=int(meter["id"]),
                export_pct=self._export_pct,
            )
        except InvalidAuth:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(),
                errors={"base": "invalid_auth"},
            )
        except NoBillingPeriod:
            return self.async_abort(reason="no_billing_period")
        except (CannotConnect, NoMeters):
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(str(data[CONF_METER_ID]))
        self._abort_if_unique_id_configured()
        title = f"Enea Energy ({data[CONF_METER_CODE]})"
        return self.async_create_entry(title=title, data=data)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            username = str(
                user_input.get(CONF_USERNAME) or entry.data.get(CONF_USERNAME)
            ).strip()
            password = str(
                user_input.get(CONF_PASSWORD) or entry.data.get(CONF_PASSWORD)
            )
            export_pct = _normalize_export_recovery_percent(
                user_input.get(
                    CONF_EXPORT_RECOVERY_PERCENT,
                    entry.data.get(CONF_EXPORT_RECOVERY_PERCENT),
                )
            )
            try:
                data = await _build_entry_data(
                    username=username,
                    password=password,
                    meter_id=int(entry.data[CONF_METER_ID]),
                    export_pct=export_pct,
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except NoBillingPeriod:
                errors["base"] = "no_billing_period"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except NoMeters:
                errors["base"] = "no_meters"
            except Exception:
                _LOGGER.exception("Enea Energy: unexpected error during reconfigure")
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(entry, data=data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")
                    ): str,
                    vol.Optional(CONF_PASSWORD, default=""): str,
                    vol.Optional(
                        CONF_EXPORT_RECOVERY_PERCENT,
                        default=_normalize_export_recovery_percent(
                            entry.data.get(CONF_EXPORT_RECOVERY_PERCENT)
                        ),
                    ): vol.In(EXPORT_RECOVERY_PERCENT_OPTIONS),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            username = str(
                user_input.get(CONF_USERNAME) or entry.data.get(CONF_USERNAME)
            ).strip()
            password = str(user_input[CONF_PASSWORD])
            try:
                data = await _build_entry_data(
                    username=username,
                    password=password,
                    meter_id=int(entry.data[CONF_METER_ID]),
                    export_pct=_normalize_export_recovery_percent(
                        entry.data.get(CONF_EXPORT_RECOVERY_PERCENT)
                    ),
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except NoBillingPeriod:
                errors["base"] = "no_billing_period"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Enea Energy: unexpected error during reauth")
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={"title": entry.title},
        )
