"""Klient HTTP do logowania i pobierania danych z eBOK Enea."""

from __future__ import annotations

from html.parser import HTMLParser
import logging
import re
import time
from datetime import date

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

# Zapasowe wzorce, gdyby parser HTML nie zadziałał (np. zniekształcony markup)
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


class _LoginTokenParser(HTMLParser):
    """Wyciąga value z ukrytego pola name=token (dowolna kolejność atrybutów)."""

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
    """Brak wymaganej konfiguracji."""


class EneaClientAuthError(RuntimeError):
    """Błąd logowania."""


def _extract_login_token(html: str) -> str:
    parser = _LoginTokenParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # pragma: no cover — parser nie powinien rzucać na typowym HTML
        pass
    if parser.token:
        return parser.token

    for rx in _TOKEN_REGEX_FALLBACKS:
        m = rx.search(html)
        if m and m.group(1).strip():
            return m.group(1).strip()

    snippet = " ".join(html[:2000].split())
    _LOGGER.debug("eBOK logowanie: brak tokena, fragment odpowiedzi GET: %s", snippet)
    raise EneaClientAuthError(
        "Nie znaleziono ukrytego pola token na stronie logowania. "
        "Możliwe: zmiana formularza eBOK, blokada cookies (Cookiebot) lub odpowiedź inna niż strona logowania. "
        "Włącz logowanie DEBUG dla custom_components.enea_energy i sprawdź fragment HTML."
    )


def _format_date_pl(day: date) -> str:
    return day.strftime("%d.%m.%Y")


class EneaClient:
    """Sesja: GET logowanie (token), POST logowanie, POST summaryBalancingChart."""

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
                "Uzupełnij w const.py: ENEA_LOGIN_SUBMIT_URL (Krok 2)."
            )

    def _require_meter_target(self) -> None:
        if not self._point_of_delivery_id:
            raise EneaClientConfigError(
                "Brak identyfikatora punktu poboru (point of delivery) — ustaw w konfiguracji integracji."
            )
        if not ENEA_METER_SUMMARY_URL:
            raise EneaClientConfigError("Brak ENEA_METER_SUMMARY_URL w const.py.")

    async def async_login(self, *, clear_cookies: bool = False) -> str:
        """GET strony logowania (cookies + token), POST danych z eBOK.

        ``clear_cookies=True`` — czyści jar (np. po 401): bez tego serwer często zwraca
        szablon „po zalogowaniu” zamiast formularza i nie ma pola ``token``.
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
            resp.raise_for_status()
            html = await resp.text()

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
            raise EneaClientAuthError(f"Logowanie HTTP {status}: {body[:500]!r}")

        if "/logowanie" in final and (
            'id="login-form"' in body or "name=\"logowanie\"" in body
        ):
            raise EneaClientAuthError(
                "Logowanie odrzucone (nadal strona logowania). "
                "Sprawdź e-mail, hasło i czy konto nie wymaga dodatkowego kroku w przeglądarce."
            )

        _LOGGER.debug("Logowanie eBOK zakończone, URL końcowy: %s", final)
        return final

    async def _async_select_current_client_context(self) -> None:
        """GET select-current-client/{id} — wybór kontekstu przy wielu klientach na koncie."""
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
            "eBOK wybór klienta: GET select-current-client → HTTP %s, URL %s",
            status,
            final,
        )
        if status >= 400:
            _LOGGER.warning(
                "Wybór klienta eBOK zwrócił HTTP %s — API licznika może zwracać 401",
                status,
            )

    async def _async_bind_point_from_many_clients_dashboard(self) -> None:
        """Konto z wieloma umowami: wejście w link z naszym pointOfDeliveryId (sesja pod API /meter/)."""
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

        href_rx = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)
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
                0 if re.search(r"/meter(/|$)", u, re.I) else 1,
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
                "eBOK many-clients: brak linku z pointOfDeliveryId w HTML (długość=%s)",
                len(html),
            )

    async def async_prepare_meter_session(self, login_final_url: str) -> None:
        """Po zalogowaniu: wybór klienta (wiele umów) lub skan linków + wejście na wykres."""
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
                        "Rozgrzewka licznika %s → HTTP %s", path, resp.status
                    )
            referer = ENEA_METER_SUMMARY_REFERER

    async def async_fetch_balancing_json(self, day: date) -> str:
        """POST summaryBalancingChart — zwraca treść JSON (nie CSV) dla jednego dnia."""
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
                    f"Bilans za {day}: HTTP 401 (brak autoryzacji — sesja eBOK)."
                )
            if resp.status >= 400:
                raise RuntimeError(
                    f"Bilans za {day}: HTTP {resp.status} — {text[:400]!r}"
                )
        return text
