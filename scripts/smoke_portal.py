#!/usr/bin/env python3
"""Smoke-test Portal Odbiorcy login + period totals (po bilansowaniu)."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import types
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "enea_energy"


def _load(name: str, filename: str):
    path = PKG / filename
    spec = importlib.util.spec_from_file_location(f"enea_energy.{name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pkg = types.ModuleType("enea_energy")
pkg.__path__ = [str(PKG)]  # type: ignore[attr-defined]
sys.modules["enea_energy"] = pkg

const = _load("const", "const.py")
pkg.const = const
enea_client = _load("enea_client", "enea_client.py")
portal_parser = _load("portal_parser", "portal_parser.py")

EneaClient = enea_client.EneaClient
EneaClientAuthError = enea_client.EneaClientAuthError
EneaClientConfigError = enea_client.EneaClientConfigError
EneaClientUnavailableError = enea_client.EneaClientUnavailableError
period_total_kwh = portal_parser.period_total_kwh


def _period_end(start: date) -> date:
    year = start.year + 1
    day = min(start.day, monthrange(year, start.month)[1])
    return date(year, start.month, day) - timedelta(days=1)


def _load_config() -> dict:
    path = ROOT / ".local" / "dev_config.json"
    if not path.is_file():
        raise SystemExit(f"Missing {path} — copy from .local/dev_config.example.json")
    return json.loads(path.read_text())


async def _run(cfg: dict, dump: Path | None) -> int:
    client = EneaClient(
        cfg["username"],
        cfg["password"],
        meter_id=cfg.get("meter_id"),
    )
    try:
        print("Validating Portal Odbiorcy session …")
        meter = await client.async_validate()
        print(
            f"OK meter id={meter['id']} code={meter.get('code')} type={meter.get('type')}"
        )
        start = await client.async_billing_period_start()
        end = _period_end(start)
        print(f"Billing period: {start.isoformat()} → {end.isoformat()}")
        print("Fetching period totals (po bilansowaniu) …")
        consumed, returned = await client.async_fetch_energy_range(
            start, end, after_balancing=True
        )
        if dump:
            dump.parent.mkdir(parents=True, exist_ok=True)
            dump.write_text(
                json.dumps(
                    {"consumed": consumed, "returned": returned},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print(f"Wrote {dump}")
        imp = period_total_kwh(consumed)
        exp = period_total_kwh(returned)
        pct = int(cfg.get("export_recovery_percent", 80))
        balance = exp * pct / 100.0 - imp
        print(f"OK import={imp:.3f} kWh export={exp:.3f} kWh")
        print(f"Balance (export×{pct}% − import) = {balance:.3f} kWh")
        return 0
    except (EneaClientAuthError, EneaClientConfigError, EneaClientUnavailableError) as err:
        print(f"FAIL: {err}", file=sys.stderr)
        return 1
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(_load_config(), args.dump)))


if __name__ == "__main__":
    main()
