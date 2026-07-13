"""Parse JSON responses from /meter/summaryBalancingChart (endpoint does not return CSV)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

from .models import DailyEnergyRow

_LOGGER = logging.getLogger(__name__)

# eBOK summaryBalancingChart field names
KEY_ENERGY_IMPORT_CASB = "aecasb"  # balanced import [kWh] (daily or hourly row)
KEY_ENERGY_EXPORT_CASB = "eaecasb"  # balanced export [kWh]
KEY_ENERGY_IMPORT_RAW = "aec"  # raw import in hourly row
KEY_ENERGY_EXPORT_RAW = "eaec"  # raw export in hourly row


class EneaBalancingParseError(ValueError):
    """Failed to read import/export values from JSON."""


# Series labels (lowercase) — substring match
_IMPORT_LABEL_PARTS = (
    "pobór",
    "pobor",
    "pobranie",
    "zużycie",
    "zuzycie",
    "import",
    "consumption",
    "odbiór",
    "odbior",
    "energia pobrana",
    "bilans poboru",
)
_EXPORT_LABEL_PARTS = (
    "oddanie",
    "oddawanie",
    "eksport",
    "export",
    "wydanie",
    "injection",
    "energia oddana",
    "bilans oddania",
)


def _is_number(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int | float):
        return True
    if isinstance(v, str):
        try:
            float(v.replace(",", ".").replace(" ", ""))
            return True
        except ValueError:
            return False
    return False


def _to_float(v: Any) -> float:
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        return float(v.replace(",", ".").replace(" ", ""))
    raise ValueError


def _label(obj: Mapping[str, Any]) -> str:
    return str(obj.get("label") or obj.get("name") or obj.get("title") or "").lower()


def _sum_data_array(data: Any) -> float:
    if not isinstance(data, list):
        return 0.0
    total = 0.0
    for x in data:
        if x is None:
            continue
        if _is_number(x):
            total += _to_float(x)
    return total


def _classify_series(label_lower: str) -> str | None:
    for part in _IMPORT_LABEL_PARTS:
        if part in label_lower:
            return "import"
    for part in _EXPORT_LABEL_PARTS:
        if part in label_lower:
            return "export"
    return None


def _normalize_hourly_list(data: Any) -> list[float]:
    if not isinstance(data, list):
        return []
    out: list[float] = []
    for x in data:
        if x is None:
            out.append(0.0)
        elif _is_number(x):
            out.append(_to_float(x))
        else:
            out.append(0.0)
    return out


def _add_series_aligned(a: list[float] | None, b: list[float]) -> list[float]:
    if not b:
        return a or []
    if a is None:
        return list(b)
    n = max(len(a), len(b))
    return [
        (a[i] if i < len(a) else 0.0) + (b[i] if i < len(b) else 0.0) for i in range(n)
    ]


def _hourly_from_datasets(datasets: Any) -> tuple[list[float], list[float]]:
    """Merge datasets: first import + first export series (aligned to max length)."""
    if not isinstance(datasets, list):
        return [], []
    imp_acc: list[float] | None = None
    exp_acc: list[float] | None = None
    for ds in datasets:
        if not isinstance(ds, dict):
            continue
        kind = _classify_series(_label(ds))
        if kind is None:
            continue
        series = _normalize_hourly_list(ds.get("data"))
        if not series:
            continue
        if kind == "import":
            imp_acc = _add_series_aligned(imp_acc, series)
        else:
            exp_acc = _add_series_aligned(exp_acc, series)
    return imp_acc or [], exp_acc or []


def _hourly_score(imp: list[float], exp: list[float]) -> int:
    return len(imp) + len(exp)


def _best_hourly_series(root: Any) -> tuple[list[float], list[float]]:
    """Pick the richest datasets block in the JSON tree (most hourly points)."""
    best_imp: list[float] = []
    best_exp: list[float] = []
    best_score = 0

    def visit(node: Any, depth: int) -> None:
        nonlocal best_imp, best_exp, best_score
        if depth > 14:
            return
        if isinstance(node, dict) and "datasets" in node:
            imp, exp = _hourly_from_datasets(node["datasets"])
            sc = _hourly_score(imp, exp)
            if sc > best_score and (imp or exp):
                best_imp, best_exp = imp, exp
                best_score = sc
        if isinstance(node, dict):
            for v in node.values():
                visit(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                visit(item, depth + 1)

    visit(root, 0)
    return best_imp, best_exp


def _parse_datasets(datasets: Any) -> tuple[float | None, float | None]:
    if not isinstance(datasets, list):
        return None, None
    imp: float | None = None
    exp: float | None = None
    for ds in datasets:
        if not isinstance(ds, dict):
            continue
        lbl = _label(ds)
        kind = _classify_series(lbl)
        if kind is None:
            continue
        s = _sum_data_array(ds.get("data"))
        if kind == "import":
            imp = (imp or 0.0) + s
        else:
            exp = (exp or 0.0) + s
    return imp, exp


def _walk_for_datasets(obj: Any, depth: int = 0) -> tuple[float | None, float | None]:
    if depth > 12:
        return None, None
    if isinstance(obj, dict):
        if "datasets" in obj:
            imp, exp = _parse_datasets(obj["datasets"])
            if imp is not None or exp is not None:
                return imp, exp
        for v in obj.values():
            imp, exp = _walk_for_datasets(v, depth + 1)
            if imp is not None or exp is not None:
                return imp, exp
    elif isinstance(obj, list):
        for item in obj:
            imp, exp = _walk_for_datasets(item, depth + 1)
            if imp is not None or exp is not None:
                return imp, exp
    return None, None


def _coerce_energy_value(val: Any) -> float | None:
    """Number or list of numbers (e.g. hourly series) → sum in kWh."""
    if _is_number(val):
        return _to_float(val)
    if isinstance(val, list):
        total = _sum_data_array(val)
        return total
    return None


def _deep_find_casb_fields(obj: Any) -> tuple[float | None, float | None]:
    """Walk JSON tree for aecasb / eaecasb (last encountered value wins)."""
    imp: float | None = None
    exp: float | None = None

    def visit(node: Any) -> None:
        nonlocal imp, exp
        if isinstance(node, dict):
            if KEY_ENERGY_IMPORT_CASB in node:
                v = _coerce_energy_value(node[KEY_ENERGY_IMPORT_CASB])
                if v is not None:
                    imp = v
            if KEY_ENERGY_EXPORT_CASB in node:
                v = _coerce_energy_value(node[KEY_ENERGY_EXPORT_CASB])
                if v is not None:
                    exp = v
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(obj)
    return imp, exp


def _row_energy_kwh(row: Mapping[str, Any]) -> tuple[float, float]:
    """Values from one hourly row: (import, export), prefer *casb fields."""
    imp = 0.0
    exp = 0.0
    if _is_number(row.get(KEY_ENERGY_IMPORT_CASB)):
        imp = _to_float(row[KEY_ENERGY_IMPORT_CASB])
    elif _is_number(row.get(KEY_ENERGY_IMPORT_RAW)):
        imp = _to_float(row[KEY_ENERGY_IMPORT_RAW])
    if _is_number(row.get(KEY_ENERGY_EXPORT_CASB)):
        exp = _to_float(row[KEY_ENERGY_EXPORT_CASB])
    elif _is_number(row.get(KEY_ENERGY_EXPORT_RAW)):
        exp = _to_float(row[KEY_ENERGY_EXPORT_RAW])
    return imp, exp


def _parse_hourly_row_array(root: list[Any], day: date) -> DailyEnergyRow | None:
    """Response as row array: [{ dateFrom, dateTo, aecasb, eaecasb, ... }, ...]."""
    rows = [r for r in root if isinstance(r, dict)]
    if not rows:
        return None
    sample = rows[0]
    if not any(
        k in sample
        for k in (
            KEY_ENERGY_IMPORT_CASB,
            KEY_ENERGY_EXPORT_CASB,
            KEY_ENERGY_IMPORT_RAW,
            KEY_ENERGY_EXPORT_RAW,
        )
    ):
        return None

    rows = sorted(rows, key=lambda r: str(r.get("dateFrom") or ""))
    hourly_imp: list[float] = []
    hourly_exp: list[float] = []
    total_imp = 0.0
    total_exp = 0.0
    for row in rows:
        hi, he = _row_energy_kwh(row)
        hourly_imp.append(hi)
        hourly_exp.append(he)
        total_imp += hi
        total_exp += he

    return DailyEnergyRow(
        day=day,
        import_kwh=total_imp,
        export_kwh=total_exp,
        hourly_import_kwh=tuple(hourly_imp),
        hourly_export_kwh=tuple(hourly_exp),
    )


def _flat_energy_keys(obj: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """Look for flat keys such as importKwh / energyImported."""
    lower_map = {str(k).lower(): v for k, v in obj.items()}
    imp = None
    exp = None
    for key, val in lower_map.items():
        if not _is_number(val):
            continue
        v = _to_float(val)
        if any(
            p in key
            for p in (
                "import",
                "pobor",
                "pobór",
                "consumption",
                "zuzycie",
                "zużycie",
                "pobranie",
            )
        ) and "export" not in key and "odd" not in key:
            imp = (imp or 0.0) + v
        elif any(
            p in key for p in ("export", "oddanie", "injection", "wydanie", "eksport")
        ):
            exp = (exp or 0.0) + v
    return imp, exp


def parse_balancing_json(text: str, day: date) -> DailyEnergyRow:
    """Parse XHR response: daily kWh (aecasb/eaecasb or series sum) and hourly series."""
    text = text.strip()
    if not text:
        raise EneaBalancingParseError("Empty balancing API response")
    if text.startswith("<!") or text.startswith("<html"):
        raise EneaBalancingParseError(
            "Received HTML instead of JSON — session may have expired or access was denied."
        )

    try:
        root: Any = json.loads(text)
    except json.JSONDecodeError as err:
        raise EneaBalancingParseError(f"Invalid JSON: {err}") from err

    if isinstance(root, dict):
        if root.get("success") is False or root.get("error"):
            msg = root.get("message") or root.get("error") or root
            raise EneaBalancingParseError(f"API returned an error: {msg!r}")

    if isinstance(root, list):
        if not root:
            return DailyEnergyRow(
                day=day,
                import_kwh=0.0,
                export_kwh=0.0,
                hourly_import_kwh=tuple([0.0] * 24),
                hourly_export_kwh=tuple([0.0] * 24),
                no_data=True,
            )
        hourly_table = _parse_hourly_row_array(root, day)
        if hourly_table is not None:
            return hourly_table

    h_imp, h_exp = _best_hourly_series(root)
    hourly_imp_t = tuple(h_imp)
    hourly_exp_t = tuple(h_exp)

    # On row lists _deep_find_casb_fields would only return the last element — skip
    casb_imp, casb_exp = (
        (None, None) if isinstance(root, list) else _deep_find_casb_fields(root)
    )
    if casb_imp is not None or casb_exp is not None:
        return DailyEnergyRow(
            day=day,
            import_kwh=float(casb_imp if casb_imp is not None else 0.0),
            export_kwh=float(casb_exp if casb_exp is not None else 0.0),
            hourly_import_kwh=hourly_imp_t,
            hourly_export_kwh=hourly_exp_t,
        )

    imp: float | None = None
    exp: float | None = None

    if isinstance(root, dict):
        imp, exp = _flat_energy_keys(root)

    if imp is None and exp is None:
        imp, exp = _walk_for_datasets(root)

    if imp is None and exp is None and isinstance(root, dict):
        inner = root.get("data") or root.get("content") or root.get("result")
        if isinstance(inner, dict):
            imp, exp = _flat_energy_keys(inner)
        if imp is None and exp is None:
            imp, exp = _walk_for_datasets(inner)

    if imp is None and exp is None and (hourly_imp_t or hourly_exp_t):
        imp = sum(hourly_imp_t) if hourly_imp_t else 0.0
        exp = sum(hourly_exp_t) if hourly_exp_t else 0.0

    if imp is None and exp is None:
        _LOGGER.debug(
            "Unrecognized JSON structure (first 800 chars): %s", text[:800]
        )
        raise EneaBalancingParseError(
            "Could not find import/export series in JSON — attach a response snippet in your issue."
        )

    return DailyEnergyRow(
        day=day,
        import_kwh=float(imp or 0.0),
        export_kwh=float(exp or 0.0),
        hourly_import_kwh=hourly_imp_t,
        hourly_export_kwh=hourly_exp_t,
    )
