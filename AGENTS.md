# Enea Energy — Home Assistant custom integration

This repository contains a single Home Assistant **custom integration**, `enea_energy`
(`custom_components/enea_energy/`). It logs into the Polish **Portal Odbiorcy Enea**
(`portalodbiorcy.operator.enea.pl`), reads **period energy totals after balancing**
for a metering point (PPE), and exposes three sensors for the current billing window:
**bilans** (`export × recovery% − import`), **pobrana**, and **oddana** (raw export).

No hourly external statistics — refresh is every 3 hours and sensors are period totals.

The integration is UI-configured (config flow). Auth is e-mail + password.

## Cursor Cloud specific instructions

### Layout & how it runs
- There is no standalone app; the code runs *inside* Home Assistant. The dev setup runs
  Home Assistant from a Python 3.13 virtualenv and points its config dir at this repo via
  a `custom_components` symlink.
- Virtualenv: `~/ha-venv` (managed with `uv`). Home Assistant config dir: `~/ha-config`,
  where `~/ha-config/custom_components` is a symlink to `/workspace/custom_components`.

### Run / lint / checks
- Run Home Assistant (dev): `~/ha-venv/bin/hass -c ~/ha-config` — serves the UI on
  `http://localhost:8123`. Use a tmux session; it does not exit on its own.
- Lint: `~/ha-venv/bin/ruff check custom_components`.
- Syntax check: `~/ha-venv/bin/python -m compileall custom_components`.
- Local smoke test: fill `.local/dev_config.json` (gitignored) and run
  `.venv/bin/python scripts/smoke_portal.py`.

### Non-obvious gotchas
- **Billing period**: from dashboard `billingWeekData`. Each sync requests
  `start` → `start + 1 year − 1 day` once per series (pobrana + oddana) after
  balancing and reads **`sumConsumption`**.
- **Refresh**: every 3 hours (`DataUpdateCoordinator.update_interval`), plus
  setup / reload.
- **`default_config` / `go2rtc`**: may log a setup failure if the optional `go2rtc`
  binary is missing — unrelated to `enea_energy`.
- UI strings are in Polish (`strings.json`); it appears as **"Enea Energy"** in
  Settings → Devices & Services → Add Integration.
