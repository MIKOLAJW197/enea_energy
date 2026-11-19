#!/usr/bin/env python3
"""Smoke-test eBOK session + one-day balancing fetch using .local/dev_config.json."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import types
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "enea_energy"
DEFAULT_CONFIG = ROOT / ".local" / "dev_config.json"


def _load(name: str, filename: str):
    """Load a package module without executing enea_energy/__init__.py (needs HA)."""
    if "enea_energy" not in sys.modules:
        pkg = types.ModuleType("enea_energy")
        pkg.__path__ = [str(PKG)]  # type: ignore[attr-defined]
        sys.modules["enea_energy"] = pkg
    path = PKG / filename
    spec = importlib.util.spec_from_file_location(f"enea_energy.{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("const", "const.py")
_load("models", "models.py")
balancing_parser = _load("balancing_parser", "balancing_parser.py")
enea_client = _load("enea_client", "enea_client.py")

parse_balancing_json = balancing_parser.parse_balancing_json
EneaClient = enea_client.EneaClient
EneaClientAuthError = enea_client.EneaClientAuthError


def _load_config(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(
            f"Missing config: {path}\n"
            "Copy .local/dev_config.example.json → .local/dev_config.json and fill cookies."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_day(value: str | None, fallback: str | None) -> date:
    raw = (value or fallback or "").strip()
    if not raw:
        raise SystemExit("No day given — pass --day YYYY-MM-DD or set start_date in config")
    if "." in raw:
        d, m, y = raw.split(".")
        return date(int(y), int(m), int(d))
    return date.fromisoformat(raw)


async def _run(cfg: dict, day: date, *, dump_html: Path | None) -> int:
    ebok = str(cfg.get("ebok_cookie") or "").strip()
    sso = str(cfg.get("sso_cookie") or "").strip()
    if not ebok:
        print(
            "FAIL: missing ebok_cookie in config.\n"
            "Sign in at ebok.enea.pl in a browser, then set:\n"
            "  ebok_cookie = EBOK_SESSION value (or full Cookie header)\n"
            "  sso_cookie  = PHPSESSID from moja.enea.pl (recommended)"
        )
        return 1

    pod = str(cfg.get("point_of_delivery_id") or "").strip()
    client_id = str(cfg.get("current_client_id") or "").strip()

    client = EneaClient(ebok, sso, point_of_delivery_id=pod, current_client_id=client_id)
    try:
        print("Validating browser session …")
        try:
            ppe = await client.async_validate()
        except EneaClientAuthError as err:
            print(f"FAIL auth: {err}")
            return 1

        print(f"OK session — pointOfDeliveryId={ppe}")
        ebok_out, sso_out = client.export_cookies()
        print(f"Cookies rotated: ebok_len={len(ebok_out)} sso_len={len(sso_out)}")

        print(f"Fetching balancing for {day.isoformat()} …")
        try:
            raw = await client.async_fetch_balancing_json(day)
        except EneaClientAuthError as err:
            print(f"FAIL fetch auth: {err}")
            return 1
        except Exception as err:  # noqa: BLE001
            print(f"FAIL fetch: {type(err).__name__}: {err}")
            return 1

        preview = raw[:400].replace("\n", " ")
        print(f"OK raw ({len(raw)} bytes): {preview!r}")
        if dump_html:
            dump_html.write_text(raw, encoding="utf-8")
            print(f"Wrote response → {dump_html}")

        try:
            row = parse_balancing_json(raw, day)
        except Exception as err:  # noqa: BLE001
            print(f"WARN parse failed: {type(err).__name__}: {err}")
            return 3

        print(
            f"OK parsed: import={row.import_kwh} kWh, "
            f"export={row.export_kwh} kWh, "
            f"hours={len(row.hourly_import_kwh)}, no_data={row.no_data}"
        )
        return 0
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to JSON config (default: .local/dev_config.json)",
    )
    parser.add_argument("--day", help="Day to fetch (YYYY-MM-DD or DD.MM.YYYY)")
    parser.add_argument(
        "--dump",
        type=Path,
        help="Optional path to save raw API response",
    )
    args = parser.parse_args()
    cfg = _load_config(args.config)
    day = _parse_day(args.day, cfg.get("start_date"))
    raise SystemExit(asyncio.run(_run(cfg, day, dump_html=args.dump)))


if __name__ == "__main__":
    main()
