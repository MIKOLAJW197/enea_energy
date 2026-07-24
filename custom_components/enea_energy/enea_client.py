"""HTTP client for Enea eBOK login and data download."""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from html.parser import HTMLParser

import aiohttp
from yarl import URL

from .const import (
    ENEA_COOKIEBOT_CONSENT_VALUE,
    ENEA_DASHBOARD_MANY_CLIENTS_URL,
    ENEA_FORM_PASSWORD_FIELD,
    ENEA_FORM_TOKEN_FIELD,
    ENEA_FORM_USER_FIELD,
    ENEA_LOGIN_EXTRA_FIELDS,
    ENEA_LOGIN_PAGE_URL,
    ENEA_LOGIN_SUBMIT_URL,
    ENEA_METER_SUMMARY_REFERER,
    ENEA_METER_SUMMARY_URL,
    ENEA_SELECT_CURRENT_CLIENT_BASE,
)

_LOGGER = logging.getLogger(__name__)

_BROWSERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

_COOKIEBOT_HEADER = f"CookieConsent={ENEA_COOKIEBOT_CONSENT_VALUE}"

_METER_HEADERS = {
    **_BROWSERS,
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://ebok.enea.pl",
    "Referer": ENEA_METER_SUMMARY_REFERER,
}

# Fallback patterns when the HTML parser fails (e.g. malformed markup)
_TOKEN_REGEX_FALLBACKS = (
    re.compile(
        r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']token["\'][^>]*value=["\']([^"\']*)["\']',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r'<input[^>]*name=["\']token["\'][^>]*value=["\']([^"\']*)["\']',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r'<input[^>]*value=["\']([^"\']+)["\'][^>]*name=["\']token["\']',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r'name=["\']token["\'][^>]*value=["\']([^"\']*)["\']',
        re.IGNORECASE | re.DOTALL,
    ),
)

# eBOK sometimes replaces /logowanie with a maintenance / WAF block page (no login form).
_EBOK_UNAVAILABLE_MARKERS = (
    "strona zablokowana",
    "prace serwisowe",
    "prac serwisowych",
    "aplikacja ebok jest niedostępna",
    "aplikacja ebok jest niedostepna",
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


class _LoginTokenParser(HTMLParser):
    """Extract value from hidden input name=token (any attribute order)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.token is not None or tag.lower() != "input":
            return
        ad = {str(k).lower(): (v if v is not None else "") for k, v in attrs}
        if ad.get("name", "").lower() != ENEA_FORM_TOKEN_FIELD.lower():
            return
        typ = (ad.get("type") or "").lower()
        if typ not in ("hidden", ""):
            return
        val = (ad.get("value") or "").strip()
        if val:
            self.token = val


class EneaClientConfigError(RuntimeError):
    """Missing required configuration."""


class EneaClientAuthError(RuntimeError):
    """Login or session error."""


class EneaClientUnavailableError(EneaClientAuthError):
    """eBOK portal temporarily unavailable (maintenance / block page)."""


def _strip_html_to_text(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    return " ".join(text.split()).strip()


def _maintenance_message_from_html(html: str) -> str:
    """Build a short human-readable summary from a maintenance/block page."""
    parts: list[str] = []
    title_m = _TITLE_RE.search(html)
    if title_m:
        title = _strip_html_to_text(title_m.group(1))
        if title:
            parts.append(title)
    h3_m = _H3_RE.search(html)
    if h3_m:
        heading = _strip_html_to_text(h3_m.group(1))
        if heading and heading not in parts:
            parts.append(heading)
    for p_m in _P_RE.finditer(html):
        para = _strip_html_to_text(p_m.group(1))
        if para and para not in parts:
            parts.append(para)
        if sum(len(p) for p in parts) > 400:
            break
    if parts:
        return " ".join(parts)[:500]
    return _strip_html_to_text(html[:1500])[:500]


def _raise_if_ebok_unavailable(html: str) -> None:
    """Raise when GET /logowanie returned a maintenance or block page instead of the form."""
    lowered = html.casefold()
    if not any(marker in lowered for marker in _EBOK_UNAVAILABLE_MARKERS):
        return
    details = _maintenance_message_from_html(html)
    raise EneaClientUnavailableError(
        "eBOK is temporarily unavailable (maintenance or blocked page) — "
        "no login form/token was returned. "
        f"Portal message: {details}"
    )


def _extract_login_token(html: str) -> str:
    _raise_if_ebok_unavailable(html)

    parser = _LoginTokenParser()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, AssertionError) as err:
        # Malformed markup — fall through to regex fallbacks below.
        _LOGGER.debug("eBOK login HTML parser failed (%s); trying regex", err)
    if parser.token:
        return parser.token

    for rx in _TOKEN_REGEX_FALLBACKS:
        m = rx.search(html)
        if m and m.group(1).strip():
            return m.group(1).strip()

    snippet = " ".join(html[:2000].split())
    _LOGGER.debug("eBOK login: token not found, GET response snippet: %s", snippet)
    raise EneaClientAuthError(
        "Hidden token field not found on the login page. "
        "Possible causes: eBOK maintenance/block page, form change, cookie consent "
        "block (Cookiebot), or unexpected response. "
        "Enable DEBUG logging for custom_components.enea_energy and inspect the HTML snippet."
    )


def _format_date_pl(day: date) -> str:
    return day.strftime("%d.%m.%Y")


class EneaClient:
    """Session: GET login page (token), POST credentials, POST summaryBalancingChart."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        point_of_delivery_id: str,
        current_client_id: str = "",
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._point_of_delivery_id = (point_of_delivery_id or "").strip()
        self._current_client_id = (current_client_id or "").strip()

    def _require_login_urls(self) -> None:
        if not ENEA_LOGIN_SUBMIT_URL:
            raise EneaClientConfigError(
                "Set ENEA_LOGIN_SUBMIT_URL in const.py."
            )

    def _require_meter_target(self) -> None:
        if not self._point_of_delivery_id:
            raise EneaClientConfigError(
                "Missing point of delivery ID — configure it in the integration settings."
            )
        if not ENEA_METER_SUMMARY_URL:
            raise EneaClientConfigError("Missing ENEA_METER_SUMMARY_URL in const.py.")

    async def async_login(self, *, clear_cookies: bool = False) -> str:
        """GET login page (cookies + token), then POST eBOK credentials.

        ``clear_cookies=True`` clears the jar (e.g. after 401); otherwise the server
        may return a post-login template without the ``token`` field.
        """
        self._require_login_urls()
        assert ENEA_LOGIN_SUBMIT_URL is not None

        ebok_url = URL("https://ebok.enea.pl")
        if clear_cookies:
            self._session.cookie_jar.clear()
        self._session.cookie_jar.update_cookies(
            {"CookieConsent": ENEA_COOKIEBOT_CONSENT_VALUE},
            response_url=ebok_url,
        )

        page_url = ENEA_LOGIN_PAGE_URL or ENEA_LOGIN_SUBMIT_URL
        if clear_cookies:
            sep = "&" if "?" in page_url else "?"
            page_url = f"{page_url}{sep}_nc={int(time.time() * 1000)}"

        page_headers = {
            **_BROWSERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cookie": _COOKIEBOT_HEADER,
        }
        async with self._session.get(page_url, headers=page_headers) as resp:
            html = await resp.text()
            status = resp.status
            final_url = str(resp.url)

        if status >= 400:
            raise EneaClientAuthError(
                f"Login page HTTP {status} ({final_url}): {html[:500]!r}"
            )
        if status != 200:
            _LOGGER.warning(
                "eBOK login GET returned HTTP %s (url=%s) — expecting 200 with login form",
                status,
                final_url,
            )

        token = _extract_login_token(html)
        payload: dict[str, str] = {
            ENEA_FORM_USER_FIELD: self._username,
            ENEA_FORM_PASSWORD_FIELD: self._password,
            ENEA_FORM_TOKEN_FIELD: token,
            "btnSubmit": "",
        }
        if ENEA_LOGIN_EXTRA_FIELDS:
            payload.update(ENEA_LOGIN_EXTRA_FIELDS)

        post_headers = {
            **_BROWSERS,
            "Referer": page_url,
            "Origin": "https://ebok.enea.pl",
            "Cookie": _COOKIEBOT_HEADER,
        }
        async with self._session.post(
            ENEA_LOGIN_SUBMIT_URL,
            data=payload,
            headers=post_headers,
            allow_redirects=True,
        ) as resp:
            body = await resp.text()
            status = resp.status
            final = str(resp.url)

        if status >= 400:
            raise EneaClientAuthError(f"Login HTTP {status}: {body[:500]!r}")

        if "/logowanie" in final and (
            'id="login-form"' in body or "name=\"logowanie\"" in body
        ):
            raise EneaClientAuthError(
                "Login rejected (still on login page). "
                "Check e-mail, password, and whether the account needs an extra browser step."
            )

        _LOGGER.debug("eBOK login finished, final URL: %s", final)
        return final

    async def _async_select_current_client_context(self) -> None:
        """GET select-current-client/{id} — select context when multiple clients exist."""
        cid = self._current_client_id
        url = f"{ENEA_SELECT_CURRENT_CLIENT_BASE}{cid}"
        headers = {
            **_BROWSERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": ENEA_DASHBOARD_MANY_CLIENTS_URL,
        }
        async with self._session.get(
            url, headers=headers, allow_redirects=True
        ) as resp:
            await resp.read()
            status = resp.status
            final = str(resp.url)
        _LOGGER.debug(
            "eBOK client selection: GET select-current-client → HTTP %s, URL %s",
            status,
            final,
        )
        if status >= 400:
            _LOGGER.warning(
                "eBOK client selection returned HTTP %s — meter API may respond with 401",
                status,
            )

    async def _async_bind_point_from_many_clients_dashboard(self) -> None:
        """Multi-contract account: follow link with our pointOfDeliveryId (session for /meter/ API)."""
        pid = self._point_of_delivery_id
        pid_compact = pid.replace("-", "").lower()
        async with self._session.get(
            ENEA_DASHBOARD_MANY_CLIENTS_URL,
            headers={
                **_BROWSERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://ebok.enea.pl/",
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
                full = "https://ebok.enea.pl" + href
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
            async with self._session.get(
                url,
                headers={
                    **_BROWSERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": referer,
                },
                allow_redirects=True,
            ) as r2:
                await r2.read()
                _LOGGER.debug("eBOK PPE: GET %s → HTTP %s", url, r2.status)
            referer = url

        if not to_visit:
            _LOGGER.debug(
                "eBOK many-clients: no link with pointOfDeliveryId in HTML (length=%s)",
                len(html),
            )

    async def async_prepare_meter_session(self, login_final_url: str) -> None:
        """After login: select client (multi-contract) or scan links and open the chart page."""
        if self._current_client_id:
            await self._async_select_current_client_context()
            referer = ENEA_DASHBOARD_MANY_CLIENTS_URL
        else:
            await self._async_bind_point_from_many_clients_dashboard()
            referer = (
                ENEA_DASHBOARD_MANY_CLIENTS_URL
                if "many-clients" in login_final_url.lower()
                else "https://ebok.enea.pl/"
            )

        pid = self._point_of_delivery_id

        for path in (
            f"{ENEA_METER_SUMMARY_REFERER}?pointOfDeliveryId={pid}",
            ENEA_METER_SUMMARY_REFERER,
        ):
            async with self._session.get(
                path,
                headers={
                    **_BROWSERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": referer,
                },
                allow_redirects=True,
            ) as resp:
                await resp.read()
                if resp.status >= 400:
                    _LOGGER.warning(
                        "Meter warm-up %s → HTTP %s", path, resp.status
                    )
            referer = ENEA_METER_SUMMARY_REFERER

    async def async_fetch_balancing_json(self, day: date) -> str:
        """POST summaryBalancingChart — returns JSON body (not CSV) for one day."""
        self._require_meter_target()
        form = {
            "duration": "day",
            "date": _format_date_pl(day),
            "pointOfDeliveryId": self._point_of_delivery_id,
        }
        async with self._session.post(
            ENEA_METER_SUMMARY_URL,
            data=form,
            headers=_METER_HEADERS,
        ) as resp:
            text = await resp.text()
            if resp.status == 401:
                raise EneaClientAuthError(
                    f"Balancing for {day}: HTTP 401 (unauthorized — eBOK session)."
                )
            if resp.status >= 400:
                raise RuntimeError(
                    f"Balancing for {day}: HTTP {resp.status} — {text[:400]!r}"
                )
        return text
