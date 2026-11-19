"""HTTP client for Enea eBOK session + balancing download.

Since ~2026-10 eBOK signs in through OpenID Connect at moja.enea.pl. The password
form is protected by reCAPTCHA Enterprise and optionally an SMS / e-mail 2FA code,
so this client never submits credentials. The user signs in in a normal browser and
hands over session cookies (`EBOK_SESSION`, optionally moja.enea.pl `PHPSESSID`).

The client then:
- keeps the eBOK session alive with a light periodic request,
- when the eBOK session is gone, follows the normal OIDC redirect with the Moja
  Enea session (silent single sign-on — no form, no CAPTCHA),
- otherwise raises ``EneaClientAuthError`` so Home Assistant can ask for a new
  browser sign-in.

Hourly meter data is still ``POST /meter/summaryBalancingChart`` → JSON.
"""

from __future__ import annotations

import logging
import re
from datetime import date

import aiohttp
from yarl import URL

from .const import (
    EBOK_COOKIE_NAME,
    ENEA_BASE_URL,
    ENEA_COOKIEBOT_CONSENT_VALUE,
    ENEA_DASHBOARD_MANY_CLIENTS_URL,
    ENEA_LOGIN_PAGE_URL,
    ENEA_METER_SUMMARY_REFERER,
    ENEA_METER_SUMMARY_URL,
    ENEA_SELECT_CURRENT_CLIENT_BASE,
    ENEA_SSO_URL,
    SSO_COOKIE_NAME,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

_BROWSERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

_METER_HEADERS = {
    **_BROWSERS,
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": ENEA_BASE_URL,
    "Referer": ENEA_METER_SUMMARY_REFERER,
}


class EneaClientConfigError(RuntimeError):
    """Missing required configuration."""


class EneaClientAuthError(RuntimeError):
    """Session gone and could not be renewed — user must sign in again in a browser."""


class EneaClientUnavailableError(EneaClientAuthError):
    """eBOK portal temporarily unavailable."""


def parse_cookies(raw: str | None, default_name: str) -> dict[str, str]:
    """Accept a bare cookie value, ``name=value``, or a whole ``Cookie:`` header."""
    raw = (raw or "").strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()
    if not raw:
        return {}
    if "=" not in raw:
        return {default_name: raw}
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            cookies[name.strip()] = value.strip()
    return cookies


def format_cookies(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _format_date_pl(day: date) -> str:
    return day.strftime("%d.%m.%Y")


class EneaClient:
    """Browser-session client: cookies in → balancing JSON out."""

    def __init__(
        self,
        ebok_cookie: str | None,
        sso_cookie: str | None = None,
        point_of_delivery_id: str = "",
        current_client_id: str = "",
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._ebok_cookies = parse_cookies(ebok_cookie, EBOK_COOKIE_NAME)
        self._sso_cookies = parse_cookies(sso_cookie, SSO_COOKIE_NAME)
        self._point_of_delivery_id = (point_of_delivery_id or "").strip()
        self._current_client_id = (current_client_id or "").strip()
        self._session = session
        self._owns_session = session is None
        self._ready = False

    @property
    def point_of_delivery_id(self) -> str:
        return self._point_of_delivery_id

    def _ensure_http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            jar = aiohttp.CookieJar()
            ebok = URL(ENEA_BASE_URL)
            sso = URL(ENEA_SSO_URL)
            jar.update_cookies(
                {"CookieConsent": ENEA_COOKIEBOT_CONSENT_VALUE},
                response_url=ebok,
            )
            if self._ebok_cookies:
                jar.update_cookies(self._ebok_cookies, response_url=ebok)
            if self._sso_cookies:
                jar.update_cookies(self._sso_cookies, response_url=sso)
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": USER_AGENT},
                cookie_jar=jar,
                timeout=aiohttp.ClientTimeout(total=60),
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._ready = False

    def export_cookies(self) -> tuple[str, str]:
        """Current (possibly rotated) cookies — persist on the config entry."""
        if self._session is None:
            return format_cookies(self._ebok_cookies), format_cookies(self._sso_cookies)
        jar = self._session.cookie_jar
        ebok = {
            k: m.value
            for k, m in jar.filter_cookies(URL(ENEA_BASE_URL)).items()
            if k == EBOK_COOKIE_NAME
        } or self._ebok_cookies
        sso = {
            k: m.value
            for k, m in jar.filter_cookies(URL(ENEA_SSO_URL)).items()
            if not k.startswith("TS")
        } or self._sso_cookies
        self._ebok_cookies = ebok
        self._sso_cookies = sso
        return format_cookies(ebok), format_cookies(sso)

    @staticmethod
    def _bounced_to_login(url: URL) -> bool:
        host = (url.host or "").lower()
        path = url.path or ""
        if host and host != URL(ENEA_BASE_URL).host:
            return True
        if "signin-oidc" in path or "/logowanie" in path.lower():
            return True
        if "moja.enea.pl" in host:
            return True
        return False

    def _require_meter_target(self) -> None:
        if not self._point_of_delivery_id:
            raise EneaClientConfigError(
                "Missing point of delivery ID — configure it in the integration settings."
            )

    async def async_ensure_session(self) -> None:
        """Validate the handed-over session; renew via silent SSO when possible."""
        session = self._ensure_http()
        async with session.get(
            ENEA_METER_SUMMARY_REFERER,
            headers={
                **_BROWSERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            allow_redirects=True,
        ) as resp:
            html = await resp.text()
            final_url = resp.url

        if self._bounced_to_login(final_url):
            # Try once more via the login entrypoint — Moja PHPSESSID may complete OIDC.
            async with session.get(
                ENEA_LOGIN_PAGE_URL,
                headers={
                    **_BROWSERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                allow_redirects=True,
            ) as resp2:
                html = await resp2.text()
                final_url = resp2.url

        if self._bounced_to_login(final_url):
            self._ready = False
            raise EneaClientAuthError(
                "eBOK session expired — sign in again in a browser and paste "
                "EBOK_SESSION (and preferably moja.enea.pl PHPSESSID)."
            )

        self._ready = True
        self._discover_ppe(html)
        await self.async_prepare_meter_session(str(final_url))

    def _discover_ppe(self, html: str) -> None:
        if self._point_of_delivery_id:
            return
        match = re.search(
            r'pointOfDeliveryId"?\s*[:=]\s*"?'
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            html,
            re.I,
        )
        if match:
            self._point_of_delivery_id = match.group(1)
            _LOGGER.debug("eBOK: discovered pointOfDeliveryId=%s", self._point_of_delivery_id)

    async def async_keepalive(self) -> bool:
        """Touch eBOK so the session does not idle out. True = still signed in."""
        try:
            await self.async_ensure_session()
        except EneaClientAuthError:
            return False
        return True

    async def async_validate(self) -> str:
        """Check the session and return the (possibly discovered) PPE id."""
        await self.async_ensure_session()
        self._require_meter_target()
        return self._point_of_delivery_id

    # --- retained name used by older call sites / smoke script ---
    async def async_login(self, *, clear_cookies: bool = False) -> str:
        """Compatibility wrapper: ensure session (optionally drop jar first)."""
        if clear_cookies and self._session is not None:
            self._session.cookie_jar.clear()
            # Re-seed from the originally configured cookies.
            jar = self._session.cookie_jar
            jar.update_cookies(
                {"CookieConsent": ENEA_COOKIEBOT_CONSENT_VALUE},
                response_url=URL(ENEA_BASE_URL),
            )
            if self._ebok_cookies:
                jar.update_cookies(self._ebok_cookies, response_url=URL(ENEA_BASE_URL))
            if self._sso_cookies:
                jar.update_cookies(self._sso_cookies, response_url=URL(ENEA_SSO_URL))
            self._ready = False
        await self.async_ensure_session()
        return ENEA_METER_SUMMARY_REFERER

    async def _async_select_current_client_context(self) -> None:
        """GET select-current-client/{id} — select context when multiple clients exist."""
        cid = self._current_client_id
        if not cid:
            return
        url = f"{ENEA_SELECT_CURRENT_CLIENT_BASE}{cid}"
        session = self._ensure_http()
        headers = {
            **_BROWSERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": ENEA_DASHBOARD_MANY_CLIENTS_URL,
        }
        async with session.get(url, headers=headers, allow_redirects=True) as resp:
            await resp.read()
            if resp.status >= 400:
                _LOGGER.warning(
                    "eBOK client selection returned HTTP %s — meter API may respond with 401",
                    resp.status,
                )

    async def _async_bind_point_from_many_clients_dashboard(self) -> None:
        """Multi-contract account: follow link with our pointOfDeliveryId."""
        session = self._ensure_http()
        pid = self._point_of_delivery_id
        if not pid:
            return
        pid_compact = pid.replace("-", "").lower()
        async with session.get(
            ENEA_DASHBOARD_MANY_CLIENTS_URL,
            headers={
                **_BROWSERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"{ENEA_BASE_URL}/",
            },
            allow_redirects=True,
        ) as resp:
            html = await resp.text()

        href_rx = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.IGNORECASE)
        seen: set[str] = set()
        to_visit: list[str] = []
        for m in href_rx.finditer(html):
            href = m.group(1).replace("&amp;", "&").strip()
            h_norm = href.replace("-", "").lower()
            if pid not in href and pid_compact not in h_norm:
                continue
            if href.startswith("//"):
                full = "https:" + href
            elif href.startswith("/"):
                full = ENEA_BASE_URL + href
            elif href.startswith("http"):
                full = href
            else:
                continue
            if "ebok.enea.pl" not in full or full in seen:
                continue
            seen.add(full)
            to_visit.append(full)

        referer = ENEA_DASHBOARD_MANY_CLIENTS_URL
        to_visit.sort(
            key=lambda u: (
                0 if re.search(r"/meter(/|$)", u, re.IGNORECASE) else 1,
                len(u),
            )
        )

        for url in to_visit[:8]:
            async with session.get(
                url,
                headers={
                    **_BROWSERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": referer,
                },
                allow_redirects=True,
            ) as r2:
                await r2.read()
            referer = url

    async def async_prepare_meter_session(self, login_final_url: str = "") -> None:
        """After session check: select client (multi-contract) and warm the chart page."""
        if self._current_client_id:
            await self._async_select_current_client_context()
            referer = ENEA_DASHBOARD_MANY_CLIENTS_URL
        else:
            await self._async_bind_point_from_many_clients_dashboard()
            referer = (
                ENEA_DASHBOARD_MANY_CLIENTS_URL
                if "many-clients" in (login_final_url or "").lower()
                else f"{ENEA_BASE_URL}/"
            )

        session = self._ensure_http()
        pid = self._point_of_delivery_id
        for path in (
            f"{ENEA_METER_SUMMARY_REFERER}?pointOfDeliveryId={pid}" if pid else "",
            ENEA_METER_SUMMARY_REFERER,
        ):
            if not path:
                continue
            async with session.get(
                path,
                headers={
                    **_BROWSERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": referer,
                },
                allow_redirects=True,
            ) as resp:
                await resp.read()
            referer = ENEA_METER_SUMMARY_REFERER

    async def async_fetch_balancing_json(self, day: date) -> str:
        """POST summaryBalancingChart — returns JSON body for one day."""
        if not self._ready:
            await self.async_ensure_session()
        self._require_meter_target()
        session = self._ensure_http()
        form = {
            "duration": "day",
            "date": _format_date_pl(day),
            "pointOfDeliveryId": self._point_of_delivery_id,
        }
        async with session.post(
            ENEA_METER_SUMMARY_URL,
            data=form,
            headers=_METER_HEADERS,
        ) as resp:
            text = await resp.text()
            if resp.status == 401 or self._looks_like_login_html(text):
                self._ready = False
                raise EneaClientAuthError(
                    f"Balancing for {day}: unauthorized — eBOK session expired."
                )
            if resp.status >= 400:
                raise RuntimeError(
                    f"Balancing for {day}: HTTP {resp.status} — {text[:400]!r}"
                )
        return text

    @staticmethod
    def _looks_like_login_html(text: str) -> bool:
        stripped = text.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            return False
        lower = text.casefold()
        return "moja.enea.pl" in lower or "logowanie" in lower[:2000]
