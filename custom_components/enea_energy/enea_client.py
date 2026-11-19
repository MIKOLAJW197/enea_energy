"""HTTP client for Portal Odbiorcy Enea (operator.enea.pl).

Logs in with e-mail + password, lists metering points (PPE), and downloads
hourly energy series **after balancing** (prosument: pobrana / oddana).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import aiohttp

from .const import (
    BILLING_PERIOD_MIN_SEGMENT_DAYS,
    DASHBOARD_MEASUREMENT_CONSUMPTION,
    DATA_SOURCE_AFTER_BALANCING,
    MEASUREMENT_ENERGY_CONSUMED,
    MEASUREMENT_ENERGY_RETURNED,
    PORTAL_URL,
    REQUEST_TIMEOUT_SECONDS,
    RESOLUTION_HOURLY,
    URL_CONSUMPTION_RANGE,
    URL_CONSUMPTION_RANGE_DATA_SOURCE,
    URL_LOGIN,
    URL_PPE_DASHBOARD,
    URL_PPES,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Origin": PORTAL_URL,
    "Referer": f"{PORTAL_URL}/portalOdbiorcy/",
}


class EneaClientConfigError(RuntimeError):
    """Missing required configuration."""


class EneaClientAuthError(RuntimeError):
    """Invalid credentials or session expired."""


class EneaClientUnavailableError(RuntimeError):
    """Portal temporarily unavailable / unexpected response."""


class EneaClient:
    """Portal Odbiorcy session + consumption downloads."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        meter_id: int | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._username = (username or "").strip()
        self._password = password or ""
        self._meter_id = int(meter_id) if meter_id is not None else None
        self._owns_session = session is None
        self._session = session
        self._authenticated = False

    @property
    def meter_id(self) -> int | None:
        return self._meter_id

    def _ensure_http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                headers=_HEADERS,
            )
            self._owns_session = True
            self._authenticated = False
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        self._authenticated = False

    async def async_login(self) -> None:
        if not self._username or not self._password:
            raise EneaClientConfigError("Missing Portal Odbiorcy e-mail or password.")
        session = self._ensure_http()
        try:
            async with session.post(
                URL_LOGIN,
                json={"username": self._username, "password": self._password},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status == 401:
                    raise EneaClientAuthError("Invalid e-mail or password.")
                if resp.status != 200:
                    body = (await resp.text())[:200]
                    raise EneaClientUnavailableError(
                        f"Login failed HTTP {resp.status}: {body}"
                    )
        except (TimeoutError, aiohttp.ClientError) as err:
            raise EneaClientUnavailableError(f"Cannot reach Portal Odbiorcy: {err}") from err
        self._authenticated = True
        _LOGGER.debug("Portal Odbiorcy: authenticated as %s", self._username)

    async def _request(self, method: str, url: str, *, label: str) -> Any:
        if not self._authenticated:
            await self.async_login()
        session = self._ensure_http()

        async def _once() -> Any:
            async with session.request(method, url, timeout=_TIMEOUT) as resp:
                if resp.status in (401, 403):
                    raise EneaClientAuthError(f"{label}: session expired ({resp.status})")
                if resp.status != 200:
                    text = (await resp.text())[:300]
                    raise EneaClientUnavailableError(
                        f"{label}: unexpected HTTP {resp.status}: {text}"
                    )
                return await resp.json()

        try:
            return await _once()
        except EneaClientAuthError:
            self._authenticated = False
            await self.async_login()
            return await _once()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise EneaClientUnavailableError(f"{label}: {err}") from err

    async def async_list_meters(self) -> list[dict[str, Any]]:
        data = await self._request("GET", URL_PPES, label="ppes")
        if not isinstance(data, list):
            raise EneaClientUnavailableError("Unexpected /user/ppes payload")
        return data

    async def async_get_dashboard(self, meter_id: int | None = None) -> dict[str, Any]:
        mid = int(meter_id if meter_id is not None else (self._meter_id or 0))
        if not mid:
            raise EneaClientConfigError("Missing meter_id.")
        data = await self._request(
            "GET", URL_PPE_DASHBOARD.format(meter_id=mid), label="dashboard"
        )
        if not isinstance(data, dict):
            raise EneaClientUnavailableError("Unexpected dashboard payload")
        return data

    async def async_validate(self) -> dict[str, Any]:
        """Login, resolve meter, return the selected PPE dict."""
        meters = await self.async_list_meters()
        if not meters:
            raise EneaClientConfigError("No metering points on this Portal Odbiorcy account.")
        if self._meter_id is None:
            if len(meters) == 1:
                self._meter_id = int(meters[0]["id"])
            else:
                raise EneaClientConfigError(
                    "Multiple metering points — select meter_id in the config flow."
                )
        for meter in meters:
            if int(meter["id"]) == self._meter_id:
                return meter
        raise EneaClientConfigError(
            f"Meter id {self._meter_id} is not on this Portal Odbiorcy account."
        )

    async def async_billing_period_start(self, meter_id: int | None = None) -> date:
        """Current billing period start from dashboard (same as Enea Licznik)."""
        dashboard = await self.async_get_dashboard(meter_id)
        start = billing_period_start_from_dashboard(dashboard)
        if start is None:
            raise EneaClientConfigError(
                "Could not detect billing period start from Portal Odbiorcy dashboard."
            )
        return start

    async def async_fetch_energy_range(
        self,
        start: date,
        end: date,
        *,
        after_balancing: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (consumed, returned) raw JSON for [start, end] at hourly resolution."""
        if self._meter_id is None:
            raise EneaClientConfigError("Missing meter_id.")
        if start > end:
            raise ValueError(f"start ({start}) must be <= end ({end})")

        def _url(measurement: int) -> str:
            template = (
                URL_CONSUMPTION_RANGE_DATA_SOURCE
                if after_balancing
                else URL_CONSUMPTION_RANGE
            )
            return template.format(
                meter_id=self._meter_id,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                measurement_type=measurement,
                resolution=RESOLUTION_HOURLY,
                data_source=DATA_SOURCE_AFTER_BALANCING,
            )

        consumed = await self._request(
            "GET", _url(MEASUREMENT_ENERGY_CONSUMED), label="energy_consumed"
        )
        returned = await self._request(
            "GET", _url(MEASUREMENT_ENERGY_RETURNED), label="energy_returned"
        )
        return consumed, returned


def _ms_to_local_date(ms: float) -> date:
    utc = datetime.fromtimestamp(float(ms) / 1000.0, tz=UTC)
    try:
        from zoneinfo import ZoneInfo

        return utc.astimezone(ZoneInfo("Europe/Warsaw")).date()
    except Exception:  # noqa: BLE001
        return utc.date()


def billing_period_starts_from_dashboard(data: dict[str, Any]) -> list[date]:
    """Invoice period starts from ``billingWeekData`` (skip the first window)."""
    measurement = next(
        (
            m
            for m in data.get("billingWeekData") or []
            if m.get("measurementId") == DASHBOARD_MEASUREMENT_CONSUMPTION
        ),
        None,
    )
    if measurement is None:
        return []
    min_span = timedelta(days=BILLING_PERIOD_MIN_SEGMENT_DAYS)
    starts: list[date] = []
    for i, segment in enumerate(measurement.get("values") or []):
        if not isinstance(segment, dict):
            continue
        time_from, time_to = segment.get("timeFrom"), segment.get("timeTo")
        if i == 0 or time_from is None or time_to is None:
            continue
        start = datetime.fromtimestamp(float(time_from) / 1000.0, tz=UTC)
        end = datetime.fromtimestamp(float(time_to) / 1000.0, tz=UTC)
        if end - start >= min_span:
            starts.append(_ms_to_local_date(time_from))
    return starts


def billing_period_start_from_dashboard(data: dict[str, Any]) -> date | None:
    """Latest (current) billing period start, or ``None`` if unknown."""
    starts = billing_period_starts_from_dashboard(data)
    return starts[-1] if starts else None
