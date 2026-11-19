"""Config flow for the Enea Energy integration."""

from __future__ import annotations

import logging
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
    CONF_EBOK_COOKIE,
    CONF_EXPORT_RECOVERY_PERCENT,
    CONF_POINT_OF_DELIVERY_ID,
    CONF_SSO_COOKIE,
    CONF_START_DATE,
    CONF_USERNAME,
    DEFAULT_EXPORT_RECOVERY_PERCENT,
    DOMAIN,
    EXPORT_RECOVERY_PERCENT_OPTIONS,
)
from .enea_client import EneaClient, EneaClientAuthError, EneaClientConfigError

_LOGGER = logging.getLogger(__name__)

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


def _normalize_export_recovery_percent(value: Any) -> int:
    pct = int(value) if value is not None else DEFAULT_EXPORT_RECOVERY_PERCENT
    if pct not in EXPORT_RECOVERY_PERCENT_OPTIONS:
        return DEFAULT_EXPORT_RECOVERY_PERCENT
    return pct


class InvalidDate(HomeAssistantError):
    """Invalid history start date."""


class InvalidPod(HomeAssistantError):
    """Missing point of delivery identifier."""


class InvalidSession(HomeAssistantError):
    """Browser session cookies are missing or rejected by eBOK."""


async def _validate_session(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate cookies against eBOK; return normalised entry data."""
    _normalize_start_date(data[CONF_START_DATE])
    ebok = str(data.get(CONF_EBOK_COOKIE) or "").strip()
    if not ebok:
        raise InvalidSession

    client = EneaClient(
        ebok,
        data.get(CONF_SSO_COOKIE),
        point_of_delivery_id=str(data.get(CONF_POINT_OF_DELIVERY_ID) or "").strip(),
        current_client_id=str(data.get(CONF_CURRENT_CLIENT_ID) or "").strip(),
    )
    try:
        try:
            ppe = await client.async_validate()
        except EneaClientAuthError as err:
            raise InvalidSession from err
        except EneaClientConfigError as err:
            raise InvalidPod from err
        ebok_out, sso_out = client.export_cookies()
    finally:
        await client.close()

    out = {
        **data,
        CONF_EBOK_COOKIE: ebok_out,
        CONF_SSO_COOKIE: sso_out,
        CONF_POINT_OF_DELIVERY_ID: ppe,
        CONF_CURRENT_CLIENT_ID: str(data.get(CONF_CURRENT_CLIENT_ID) or "").strip(),
        CONF_START_DATE: _normalize_start_date(data[CONF_START_DATE]),
        CONF_EXPORT_RECOVERY_PERCENT: _normalize_export_recovery_percent(
            data.get(CONF_EXPORT_RECOVERY_PERCENT)
        ),
    }
    return out


def _normalize_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
    normalized = {**user_input}
    normalized[CONF_START_DATE] = _normalize_start_date(user_input[CONF_START_DATE])
    normalized[CONF_EBOK_COOKIE] = str(user_input.get(CONF_EBOK_COOKIE) or "").strip()
    normalized[CONF_SSO_COOKIE] = str(user_input.get(CONF_SSO_COOKIE) or "").strip()
    normalized[CONF_POINT_OF_DELIVERY_ID] = str(
        user_input.get(CONF_POINT_OF_DELIVERY_ID) or ""
    ).strip()
    normalized[CONF_CURRENT_CLIENT_ID] = str(
        user_input.get(CONF_CURRENT_CLIENT_ID) or ""
    ).strip()
    normalized[CONF_EXPORT_RECOVERY_PERCENT] = _normalize_export_recovery_percent(
        user_input.get(CONF_EXPORT_RECOVERY_PERCENT)
    )
    return normalized


def _entry_schema_defaults(entry_data: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_EBOK_COOKIE: "",
        CONF_SSO_COOKIE: "",
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


def _build_data_schema(defaults: dict[str, Any], *, require_cookies: bool = True) -> vol.Schema:
    ebok_key = (
        vol.Required(CONF_EBOK_COOKIE, default=defaults[CONF_EBOK_COOKIE])
        if require_cookies
        else vol.Optional(CONF_EBOK_COOKIE, default=defaults[CONF_EBOK_COOKIE])
    )
    return vol.Schema(
        {
            ebok_key: str,
            vol.Optional(CONF_SSO_COOKIE, default=defaults[CONF_SSO_COOKIE]): str,
            vol.Optional(
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


def _session_only_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_EBOK_COOKIE): str,
            vol.Optional(CONF_SSO_COOKIE, default=""): str,
        }
    )


class EneaEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Browser session cookies (never password) + metering options."""

    VERSION = 5

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _normalize_user_input(user_input)
            try:
                data = await _validate_session(self.hass, user_input)
            except InvalidDate:
                errors["base"] = "invalid_start_date"
            except InvalidPod:
                errors["base"] = "invalid_point_of_delivery"
            except InvalidSession:
                errors["base"] = "invalid_session"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Enea Energy: unexpected error during setup")
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(data[CONF_POINT_OF_DELIVERY_ID].lower())
                self._abort_if_unique_id_configured()
                title_src = data.get(CONF_USERNAME) or data[CONF_POINT_OF_DELIVERY_ID][:8]
                return self.async_create_entry(
                    title=f"Enea Energy ({title_src})",
                    data=data,
                )

        defaults = _entry_schema_defaults({})
        return self.async_show_form(
            step_id="user",
            data_schema=_build_data_schema(defaults),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure session cookies and metering options."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _normalize_user_input(user_input)
            new_data = {**entry.data, **user_input}
            # Empty cookie fields keep the stored session.
            if not user_input.get(CONF_EBOK_COOKIE):
                new_data[CONF_EBOK_COOKIE] = entry.data.get(CONF_EBOK_COOKIE, "")
            if not user_input.get(CONF_SSO_COOKIE):
                new_data[CONF_SSO_COOKIE] = entry.data.get(CONF_SSO_COOKIE, "")
            try:
                data = await _validate_session(self.hass, new_data)
            except InvalidDate:
                errors["base"] = "invalid_start_date"
            except InvalidPod:
                errors["base"] = "invalid_point_of_delivery"
            except InvalidSession:
                errors["base"] = "invalid_session"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Enea Energy: unexpected error during reconfigure")
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(entry, data=data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        defaults = _entry_schema_defaults(entry.data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_data_schema(defaults, require_cookies=False),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Session expired — take over a fresh browser session."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            merged = {
                **entry.data,
                CONF_EBOK_COOKIE: str(user_input.get(CONF_EBOK_COOKIE) or "").strip(),
                CONF_SSO_COOKIE: str(user_input.get(CONF_SSO_COOKIE) or "").strip(),
            }
            try:
                data = await _validate_session(self.hass, merged)
            except InvalidSession:
                errors["base"] = "invalid_session"
            except InvalidPod:
                errors["base"] = "invalid_point_of_delivery"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Enea Energy: unexpected error during reauth")
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_session_only_schema(),
            errors=errors,
            description_placeholders={"title": entry.title},
        )
