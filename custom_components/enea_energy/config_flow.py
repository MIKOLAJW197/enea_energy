"""Config flow for the Enea Energy integration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import DateSelector

from .const import (
    CONF_CURRENT_CLIENT_ID,
    CONF_EXPORT_RECOVERY_PERCENT,
    CONF_PASSWORD,
    CONF_POINT_OF_DELIVERY_ID,
    CONF_START_DATE,
    CONF_USERNAME,
    DEFAULT_EXPORT_RECOVERY_PERCENT,
    DOMAIN,
    EXPORT_RECOVERY_PERCENT_OPTIONS,
)

DEFAULT_BACKFILL_START = (
    datetime.now(UTC).date() - timedelta(days=730)
).isoformat()


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def _normalize_start_date(value: Any, *, default: str | None = None) -> str:
    if value is None:
        if default is None:
            raise ValueError("missing date")
        return default
    if isinstance(value, date):
        return value.isoformat()
    try:
        return _parse_iso_date(str(value)).isoformat()
    except ValueError as err:
        if default is not None:
            return default
        raise InvalidDate from err


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate config flow input."""
    _normalize_start_date(data[CONF_START_DATE])
    if not str(data.get(CONF_POINT_OF_DELIVERY_ID, "")).strip():
        raise InvalidPod


def _normalize_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
    normalized = {**user_input}
    normalized[CONF_START_DATE] = _normalize_start_date(user_input[CONF_START_DATE])
    return normalized


class InvalidDate(HomeAssistantError):
    """Invalid history start date."""


class InvalidPod(HomeAssistantError):
    """Missing point of delivery identifier."""


def _normalize_export_recovery_percent(value: Any) -> int:
    pct = int(value) if value is not None else DEFAULT_EXPORT_RECOVERY_PERCENT
    if pct not in EXPORT_RECOVERY_PERCENT_OPTIONS:
        return DEFAULT_EXPORT_RECOVERY_PERCENT
    return pct


def _entry_schema_defaults(entry_data: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_USERNAME: entry_data.get(CONF_USERNAME, ""),
        CONF_PASSWORD: "",
        CONF_POINT_OF_DELIVERY_ID: entry_data.get(CONF_POINT_OF_DELIVERY_ID, ""),
        CONF_CURRENT_CLIENT_ID: entry_data.get(CONF_CURRENT_CLIENT_ID, ""),
        CONF_START_DATE: _normalize_start_date(
            entry_data.get(CONF_START_DATE),
            default=DEFAULT_BACKFILL_START,
        ),
        CONF_EXPORT_RECOVERY_PERCENT: _normalize_export_recovery_percent(
            entry_data.get(CONF_EXPORT_RECOVERY_PERCENT)
        ),
    }


def _build_data_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults[CONF_USERNAME]): str,
            vol.Required(CONF_PASSWORD, default=defaults[CONF_PASSWORD]): str,
            vol.Required(
                CONF_POINT_OF_DELIVERY_ID,
                default=defaults[CONF_POINT_OF_DELIVERY_ID],
            ): str,
            vol.Optional(
                CONF_CURRENT_CLIENT_ID,
                default=defaults[CONF_CURRENT_CLIENT_ID],
            ): str,
            vol.Optional(CONF_START_DATE, default=defaults[CONF_START_DATE]): DateSelector(),
            vol.Optional(
                CONF_EXPORT_RECOVERY_PERCENT,
                default=defaults[CONF_EXPORT_RECOVERY_PERCENT],
            ): vol.In(EXPORT_RECOVERY_PERCENT_OPTIONS),
        }
    )


class EneaEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config and reconfigure flows."""

    VERSION = 4

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _normalize_user_input(user_input)
            try:
                await validate_input(self.hass, user_input)
            except InvalidDate:
                errors["base"] = "invalid_start_date"
            except InvalidPod:
                errors["base"] = "invalid_point_of_delivery"
            else:
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Enea Energy ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        defaults = _entry_schema_defaults(
            {
                CONF_USERNAME: "",
                CONF_PASSWORD: "",
                CONF_POINT_OF_DELIVERY_ID: "",
                CONF_CURRENT_CLIENT_ID: "",
                CONF_START_DATE: DEFAULT_BACKFILL_START,
                CONF_EXPORT_RECOVERY_PERCENT: DEFAULT_EXPORT_RECOVERY_PERCENT,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=_build_data_schema(defaults),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure an existing entry (credentials, point of delivery, etc.)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _normalize_user_input(user_input)
            new_data = {**entry.data, **user_input}
            new_data[CONF_POINT_OF_DELIVERY_ID] = user_input[
                CONF_POINT_OF_DELIVERY_ID
            ].strip()
            new_data[CONF_CURRENT_CLIENT_ID] = user_input.get(
                CONF_CURRENT_CLIENT_ID, ""
            ).strip()
            if not user_input.get(CONF_PASSWORD):
                new_data[CONF_PASSWORD] = entry.data[CONF_PASSWORD]
            try:
                await validate_input(self.hass, new_data)
            except InvalidDate:
                errors["base"] = "invalid_start_date"
            except InvalidPod:
                errors["base"] = "invalid_point_of_delivery"
            else:
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        defaults = _entry_schema_defaults(entry.data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_data_schema(defaults),
            errors=errors,
        )
