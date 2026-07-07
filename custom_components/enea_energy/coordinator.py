"""Coordinator: pobieranie bilansu (JSON), zapis godzinowych statystyk (recorder)."""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .balancing_parser import EneaBalancingParseError, parse_balancing_json
from .const import (
    CONF_CURRENT_CLIENT_ID,
    CONF_EXPORT_RECOVERY_PERCENT,
    CONF_PASSWORD,
    CONF_POINT_OF_DELIVERY_ID,
    CONF_START_DATE,
    CONF_USERNAME,
    DEFAULT_EXPORT_RECOVERY_PERCENT,
    DOMAIN,
    STORAGE_VERSION,
)
from .enea_client import EneaClient, EneaClientAuthError, EneaClientConfigError
from .models import DailyEnergyRow
from .statistics_helper import (
    async_add_hourly_cumulative_statistics,
    hour_start_local,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _daterange_inclusive(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _log_hourly_vs_daily_totals(row: DailyEnergyRow) -> None:
    """Ostrzeżenie, gdy suma segmentów ≠ pole dobowe z JSON (wpływa na sens skumulowania)."""
    deltas = _hourly_deltas(row)
    s_imp = sum(d[0] for d in deltas)
    s_exp = sum(d[1] for d in deltas)
    if abs(s_imp - row.import_kwh) > 0.05 or abs(s_exp - row.export_kwh) > 0.05:
        _LOGGER.warning(
            "Enea dzień %s: suma segmentów godzinowych (imp=%.4f, exp=%.4f) ≠ doba z API "
            "(imp=%.4f, exp=%.4f). Skumulowanie i statystyki opierają się na segmentach godzinowych.",
            row.day.isoformat(),
            s_imp,
            s_exp,
            row.import_kwh,
            row.export_kwh,
        )


def _hourly_deltas(row: DailyEnergyRow) -> list[tuple[float, float]]:
    """24 (lub więcej/mniej) segmentów kWh — preferowane 24 godziny z API."""
    hi = row.hourly_import_kwh
    he = row.hourly_export_kwh
    if hi or he:
        return [
            (
                float(hi[h]) if h < len(hi) else 0.0,
                float(he[h]) if h < len(he) else 0.0,
            )
            for h in range(24)
        ]
    return [(row.import_kwh, row.export_kwh)] + [(0.0, 0.0)] * 23


def _persist_cumulative_from_statistic_points(
    persisted: dict[str, Any],
    points_imp: list[tuple[datetime, float]],
    points_exp: list[tuple[datetime, float]],
) -> None:
    """Skumulowane kWh w storage = ostatni punkt sum zapisany do recordera (1:1 z external statistics)."""
    if not points_imp or not points_exp:
        return
    n_imp = len(points_imp)
    n_exp = len(points_exp)
    if n_imp != n_exp:
        _LOGGER.warning(
            "Enea: liczba punktów import (%s) ≠ export (%s) — obcinam do wspólnego końca",
            n_imp,
            n_exp,
        )
    n = min(n_imp, n_exp)
    persisted["cum_import_kwh"] = points_imp[n - 1][1]
    persisted["cum_export_kwh"] = points_exp[n - 1][1]
    persisted["last_statistic_period_end_local"] = points_imp[n - 1][0].isoformat()


def _safe_statistic_suffix(entry_id: str) -> str:
    s = "".join(c if c.isalnum() or c == "_" else "_" for c in entry_id.lower())
    if s and s[0].isdigit():
        return f"x_{s}"
    return s or "entry"


def _period_anniversary(anchor: date, year: int) -> date:
    """Rocznica daty początku okresu (np. 29.02 → 28.02 w latach nieprzestępnych)."""
    day = min(anchor.day, monthrange(year, anchor.month)[1])
    return date(year, anchor.month, day)


class EneaEnergyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Pobiera dane z eBOK i zapisuje skumulowane statystyki godzinowe (async_add_external_statistics)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self._username = entry.data[CONF_USERNAME]
        self._password = entry.data[CONF_PASSWORD]
        self._point_of_delivery_id = str(
            entry.data.get(CONF_POINT_OF_DELIVERY_ID, "")
        ).strip()
        self._current_client_id = str(
            entry.data.get(CONF_CURRENT_CLIENT_ID, "")
        ).strip()
        self._start_date = date.fromisoformat(entry.data[CONF_START_DATE])
        pct = int(entry.data.get(CONF_EXPORT_RECOVERY_PERCENT, DEFAULT_EXPORT_RECOVERY_PERCENT))
        self._export_recovery_ratio = max(0.0, min(1.0, pct / 100.0))

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )

        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{self.entry.entry_id}")
        self._persisted: dict[str, Any] = {}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.entry.title,
            manufacturer="Enea",
            model="eBOK",
        )

    @property
    def statistic_id_import(self) -> str:
        suf = _safe_statistic_suffix(self.entry.entry_id)
        return f"{DOMAIN}:{suf}_grid_import"

    @property
    def statistic_id_export(self) -> str:
        suf = _safe_statistic_suffix(self.entry.entry_id)
        return f"{DOMAIN}:{suf}_grid_export"

    async def _async_load_store(self) -> None:
        self._persisted = await self._store.async_load() or {}

    async def _async_save_store(self) -> None:
        await self._store.async_save(self._persisted)

    def _reset_backfill_progress(self) -> None:
        self._persisted.pop("last_synced_day", None)
        self._persisted["cum_import_kwh"] = 0.0
        self._persisted["cum_export_kwh"] = 0.0
        self._persisted.pop("oldest_synced_day", None)
        self._reset_balance_period()

    def _reset_balance_period(self) -> None:
        self._persisted.pop("balance_period_start", None)
        self._persisted.pop("balance_baseline_import_kwh", None)
        self._persisted.pop("balance_baseline_export_kwh", None)

    async def _async_apply_start_date_change(self) -> None:
        key = "sync_start_date"
        cur = self._start_date.isoformat()
        prev = self._persisted.get(key)
        changed = False
        if prev:
            try:
                prev_d = date.fromisoformat(prev)
            except ValueError:
                prev_d = self._start_date
            if self._start_date < prev_d:
                _LOGGER.warning(
                    "Zmieniono datę początku historii na wcześniejszą (%s → poprzednio %s). "
                    "Resetuję postęp synchronizacji.",
                    self._start_date,
                    prev_d,
                )
                self._reset_backfill_progress()
                changed = True
        if prev != cur:
            self._persisted[key] = cur
            self._reset_balance_period()
            changed = True
        ls = self._persisted.get("last_synced_day")
        if (
            ls
            and self._persisted.get("oldest_synced_day") is None
            and self._start_date < date.fromisoformat(ls)
        ):
            _LOGGER.warning(
                "Migracja: niepełny backfill (brak oldest_synced_day). Reset postępu — backfill od %s.",
                self._start_date,
            )
            self._reset_backfill_progress()
            changed = True
        if changed:
            await self._async_save_store()

    def _today_local(self) -> date:
        return dt_util.now().date()

    def _current_balance_period_start(self, today: date) -> date:
        """Początek bieżącego okresu rozliczeniowego (rocznica daty startu z konfiguracji)."""
        if today < self._start_date:
            return self._start_date
        candidate = _period_anniversary(self._start_date, today.year)
        if candidate <= today:
            return candidate
        return _period_anniversary(self._start_date, today.year - 1)

    async def _async_apply_balance_period_rollover(self) -> None:
        """Wyzeruj bilans sensora na początku nowego okresu (np. 01.02 → 01.02 nast. roku)."""
        period_start = self._current_balance_period_start(self._today_local())
        stored = self._persisted.get("balance_period_start")
        if stored == period_start.isoformat():
            return

        cum_imp = float(self._persisted.get("cum_import_kwh", 0.0))
        cum_exp = float(self._persisted.get("cum_export_kwh", 0.0))
        if stored is not None:
            _LOGGER.info(
                "Enea: nowy okres bilansu od %s — sensor startuje od zera "
                "(bazowy import=%.3f kWh, eksport=%.3f kWh)",
                period_start.isoformat(),
                cum_imp,
                cum_exp,
            )

        self._persisted["balance_period_start"] = period_start.isoformat()
        self._persisted["balance_baseline_import_kwh"] = cum_imp
        self._persisted["balance_baseline_export_kwh"] = cum_exp
        await self._async_save_store()

    def _period_energy_balance_kwh(self) -> float:
        cum_imp = float(self._persisted.get("cum_import_kwh", 0.0))
        cum_exp = float(self._persisted.get("cum_export_kwh", 0.0))
        base_imp = float(self._persisted.get("balance_baseline_import_kwh", 0.0))
        base_exp = float(self._persisted.get("balance_baseline_export_kwh", 0.0))
        return (cum_exp - base_exp) - (cum_imp - base_imp)

    def _status_payload(self, sync_through: date) -> dict[str, Any]:
        cum_imp = float(self._persisted.get("cum_import_kwh", 0.0))
        cum_exp = float(self._persisted.get("cum_export_kwh", 0.0))
        base_imp = float(self._persisted.get("balance_baseline_import_kwh", 0.0))
        base_exp = float(self._persisted.get("balance_baseline_export_kwh", 0.0))
        return {
            "sync_through": sync_through.isoformat(),
            "configured_start_date": self._start_date.isoformat(),
            "balance_period_start": self._persisted.get("balance_period_start"),
            "statistic_id_import": self.statistic_id_import,
            "statistic_id_export": self.statistic_id_export,
            "backfill_last_synced_day": self._persisted.get("last_synced_day"),
            "backfill_oldest_synced_day": self._persisted.get("oldest_synced_day"),
            "cum_import_kwh": cum_imp,
            "cum_export_kwh": cum_exp,
            "period_import_kwh": cum_imp - base_imp,
            "period_export_kwh": cum_exp - base_exp,
            "energy_balance_kwh": self._period_energy_balance_kwh(),
            "last_data_date": self._persisted.get("last_data_date"),
            "last_day_import_total_kwh": self._persisted.get("last_day_import_total"),
            "last_day_export_total_kwh": self._persisted.get("last_day_export_total"),
            "export_recovery_percent": int(round(self._export_recovery_ratio * 100)),
            "last_statistic_period_end_local": self._persisted.get(
                "last_statistic_period_end_local"
            ),
            "cumulative_meaning_pl": (
                "Skumulowane kWh w integracji = ostatni punkt zapisu do recordera (import z API; "
                "eksport × % odbioru). Wykres: karta Statystyka na pulpicie Lovelace + statistic_id "
                "import/export. Narzędzia deweloperskie → Statystyki."
            ),
        }

    async def _async_fetch_row(
        self,
        client: EneaClient,
        d: date,
    ) -> DailyEnergyRow | None:
        for attempt in (0, 1):
            try:
                raw = await client.async_fetch_balancing_json(d)
                return parse_balancing_json(raw, d)
            except EneaClientAuthError as err:
                if attempt == 0:
                    _LOGGER.info(
                        "eBOK 401 — ponowne logowanie (dzień %s): %s",
                        d.isoformat(),
                        err,
                    )
                    try:
                        login_final = await client.async_login(clear_cookies=True)
                        await client.async_prepare_meter_session(login_final)
                    except (EneaClientAuthError, EneaClientConfigError) as login_err:
                        _LOGGER.warning("Dzień %s: %s", d.isoformat(), login_err)
                        return None
                else:
                    _LOGGER.warning("Dzień %s: %s", d.isoformat(), err)
                    return None
            except (
                TimeoutError,
                aiohttp.ClientError,
                RuntimeError,
                EneaBalancingParseError,
            ) as err:
                _LOGGER.warning("Dzień %s: %s", d.isoformat(), err)
                return None
        return None

    def _append_hourly_points(
        self,
        row: DailyEnergyRow,
        cum_imp: float,
        cum_exp: float,
        points_imp: list[tuple[datetime, float]],
        points_exp: list[tuple[datetime, float]],
    ) -> tuple[float, float]:
        deltas = _hourly_deltas(row)
        day = row.day
        for h, (di, de) in enumerate(deltas):
            de *= self._export_recovery_ratio
            cum_imp += di
            cum_exp += de
            start_local = hour_start_local(self.hass, day, h)
            points_imp.append((start_local, cum_imp))
            points_exp.append((start_local, cum_exp))
        _log_hourly_vs_daily_totals(row)
        return cum_imp, cum_exp

    async def _async_refresh_last_day_hourly_statistics(self, day: date) -> None:
        """Gdy brak nowych dni — ponownie pobierz ostatnią zsynchronizowaną dobę i nadpisz punkty godzinowe."""
        last_total_imp = float(
            self._persisted.get(
                "last_day_import_total",
                self._persisted.get("last_import_kwh", 0.0),
            )
        )
        last_total_exp = float(
            self._persisted.get(
                "last_day_export_total",
                self._persisted.get("last_export_kwh", 0.0),
            )
        )
        cum_imp = float(self._persisted.get("cum_import_kwh", 0.0))
        cum_exp = float(self._persisted.get("cum_export_kwh", 0.0))
        base_imp = cum_imp - last_total_imp
        base_exp = cum_exp - last_total_exp

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            client = EneaClient(
                session,
                self._username,
                self._password,
                self._point_of_delivery_id,
                self._current_client_id,
            )
            try:
                login_final = await client.async_login()
                await client.async_prepare_meter_session(login_final)
            except (EneaClientConfigError, EneaClientAuthError) as err:
                _LOGGER.warning("Odświeżenie statystyk (dzień %s): %s", day.isoformat(), err)
                return
            row = await self._async_fetch_row(client, day)
            if row is None:
                return

        _LOGGER.info(
            "Enea: odświeżanie godzin dla ostatniej doby %s (24 segmentów z API)",
            day.isoformat(),
        )
        points_imp: list[tuple[datetime, float]] = []
        points_exp: list[tuple[datetime, float]] = []
        self._append_hourly_points(row, base_imp, base_exp, points_imp, points_exp)
        async_add_hourly_cumulative_statistics(
            self.hass,
            statistic_id_import=self.statistic_id_import,
            statistic_id_export=self.statistic_id_export,
            points_imp=points_imp,
            points_exp=points_exp,
        )
        _persist_cumulative_from_statistic_points(
            self._persisted, points_imp, points_exp
        )
        self._persisted["last_day_import_total"] = row.import_kwh
        self._persisted["last_day_export_total"] = row.export_kwh * self._export_recovery_ratio
        self._persisted["last_data_date"] = row.day.isoformat()
        await self._async_save_store()
        _LOGGER.info(
            "Enea: zapisano %s punktów godzinowych (skumulowane import/export do %.3f / %.3f kWh)",
            len(points_imp),
            points_imp[-1][1],
            points_exp[-1][1],
        )

    async def _async_update_data(self) -> dict[str, Any]:
        await self._async_load_store()
        await self._async_apply_start_date_change()
        await self._async_apply_balance_period_rollover()

        sync_through = self._today_local()
        last_str = self._persisted.get("last_synced_day")
        last_synced: date | None = date.fromisoformat(last_str) if last_str else None

        start = self._start_date if last_synced is None else last_synced + timedelta(days=1)
        if start < self._start_date:
            start = self._start_date

        _LOGGER.info(
            "Enea: plan synchronizacji — data początku (config)=%s, pierwszy dzień do pobrania=%s, "
            "ostatni dzień w kolejce (dziś)=%s, ostatnio zsynchronizowano=%s",
            self._start_date.isoformat(),
            start.isoformat(),
            sync_through.isoformat(),
            last_synced.isoformat() if last_synced else "(brak)",
        )

        if last_synced is not None and start > sync_through:
            _LOGGER.info(
                "Enea: brak nowych dni w kolejce — tylko odświeżenie ostatniej doby %s",
                last_synced.isoformat(),
            )
            if self._point_of_delivery_id:
                await self._async_refresh_last_day_hourly_statistics(last_synced)
            return self._status_payload(sync_through)

        if not self._point_of_delivery_id:
            raise UpdateFailed(
                "Brak identyfikatora punktu poboru (pointOfDeliveryId). "
                "Uzupełnij w konfiguracji integracji."
            )

        day_list = list(_daterange_inclusive(start, sync_through))
        total_days = len(day_list)
        _LOGGER.info(
            "Enea: backfill — %s dni do pobrania (od %s do %s włącznie)",
            total_days,
            start.isoformat(),
            sync_through.isoformat(),
        )

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            client = EneaClient(
                session,
                self._username,
                self._password,
                self._point_of_delivery_id,
                self._current_client_id,
            )
            try:
                login_final = await client.async_login()
                await client.async_prepare_meter_session(login_final)
            except EneaClientConfigError as err:
                raise UpdateFailed(str(err)) from err
            except EneaClientAuthError as err:
                raise UpdateFailed(str(err)) from err

            cum_imp = float(self._persisted.get("cum_import_kwh", 0.0))
            cum_exp = float(self._persisted.get("cum_export_kwh", 0.0))
            points_imp: list[tuple[datetime, float]] = []
            points_exp: list[tuple[datetime, float]] = []
            last_ok: date | None = last_synced
            last_row: DailyEnergyRow | None = None
            batch_oldest: date | None = None

            for idx, d in enumerate(day_list, start=1):
                _LOGGER.info(
                    "Enea eBOK: pobieranie bilansu za dzień %s — %s/%s w tej serii "
                    "(zakres %s → %s)",
                    d.isoformat(),
                    idx,
                    total_days,
                    start.isoformat(),
                    sync_through.isoformat(),
                )
                row = await self._async_fetch_row(client, d)
                if row is None:
                    _LOGGER.info(
                        "Enea: brak danych za dzień %s — kończę serię (kolejne dni pomijam)",
                        d.isoformat(),
                    )
                    break

                cum_imp, cum_exp = self._append_hourly_points(
                    row, cum_imp, cum_exp, points_imp, points_exp
                )
                last_ok = d
                last_row = row
                batch_oldest = d if batch_oldest is None else min(batch_oldest, d)

            if points_imp:
                _LOGGER.info(
                    "Enea: zapis do recordera — %s punktów godzinowych (skumulowane kWh), "
                    "ostatni dzień w serii: %s",
                    len(points_imp),
                    last_ok.isoformat() if last_ok else "?",
                )
                async_add_hourly_cumulative_statistics(
                    self.hass,
                    statistic_id_import=self.statistic_id_import,
                    statistic_id_export=self.statistic_id_export,
                    points_imp=points_imp,
                    points_exp=points_exp,
                )
                _persist_cumulative_from_statistic_points(
                    self._persisted, points_imp, points_exp
                )
                assert last_ok is not None
                self._persisted["last_synced_day"] = last_ok.isoformat()
                if batch_oldest is not None:
                    po = self._persisted.get("oldest_synced_day")
                    if po:
                        self._persisted["oldest_synced_day"] = min(
                            date.fromisoformat(po), batch_oldest
                        ).isoformat()
                    else:
                        self._persisted["oldest_synced_day"] = batch_oldest.isoformat()
                if last_row is not None:
                    self._persisted["last_day_import_total"] = last_row.import_kwh
                    self._persisted["last_day_export_total"] = (
                        last_row.export_kwh * self._export_recovery_ratio
                    )
                    self._persisted["last_data_date"] = last_row.day.isoformat()
                await self._async_save_store()
            elif last_synced is not None and self._point_of_delivery_id:
                await self._async_refresh_last_day_hourly_statistics(last_synced)

        return self._status_payload(sync_through)
