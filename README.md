# Enea Energy — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/MIKOLAJW197/enea_energy.svg)](https://github.com/MIKOLAJW197/enea_energy/releases)

Home Assistant custom integration for the Polish **Portal Odbiorcy Enea**
([portalodbiorcy.operator.enea.pl](https://portalodbiorcy.operator.enea.pl)).
It reads **period totals after balancing** (pobrana / oddana) and exposes three
sensors for the current billing window.

> **v2.0** switches the data source from eBOK (`ebok.enea.pl` cookies) to Portal
> Odbiorcy (e-mail + password). Existing v1 entries need re-authentication.

API access follows the same Portal endpoints as
[Enea Licznik](https://github.com/PanSzelescik/home-assistant-enea).

## How it works

1. **Login** — `POST /portalOdbiorcy/api/auth/login` with e-mail + password.
2. **Billing period start** — from the PPE dashboard
   (`GET /consumptionDashboard/ppe/{id}` → `billingWeekData`), same as
   „Początek okresu rozliczeniowego” in the portal.
3. **Period totals (po bilansowaniu)** — one request per series for
   `start` → `start + 1 year − 1 day` (e.g. `2026-02-01` → `2027-01-31`):

   ```text
   GET /consumption/{meter}/{from}/{to}/1/2/2   # pobrana
   GET /consumption/{meter}/{from}/{to}/5/2/2   # oddana
   ```

   Example: `…/consumption/105171/2026-02-01/2027-01-31/1/2/2`.

   Sensors use the response field **`sumConsumption`** (kWh for the whole window).
   No hourly history is stored — refresh is once per day, and the entities are
   period totals, not a time series.
4. **Refresh** — once a day at **07:00** (Home Assistant local time), plus on
   setup / reload.
5. **Sensors**

   | Sensor | Formula |
   | --- | --- |
   | Bilans energii | `(oddana × 70/80%) − pobrana` |
   | Energia pobrana (okres) | raw import (`sumConsumption`) |
   | Energia oddana (okres) | raw export (`sumConsumption`, no recovery %) |

## Features

- E-mail + password login (no browser cookie paste)
- Period totals **po bilansowaniu**
- Auto-detected billing period start from the portal
- Daily refresh at 07:00 local time
- Prosumer recovery **70% / 80%** on the balance sensor only
- Reconfigure + reauth flows

## Requirements

- Home Assistant **2024.1** or newer
- A verified account on [portalodbiorcy.operator.enea.pl](https://portalodbiorcy.operator.enea.pl)
- A remote-read (AMI) meter with energy history in the portal

## Installation

### HACS (recommended)

1. **HACS** → **Integrations** → **⋮** → **Custom repositories**.
2. Add `https://github.com/MIKOLAJW197/enea_energy` as type **Integration**.
3. Search for **Enea Energy**, install, restart Home Assistant.
4. **Settings** → **Devices & Services** → **Add Integration** → **Enea Energy**.

### Manual (from release zip)

1. Download the latest [`enea_energy.zip`](https://github.com/MIKOLAJW197/enea_energy/releases/latest).
2. Unzip so `enea_energy/` lands under `config/custom_components/`.
3. Restart Home Assistant.
4. Add the integration via **Settings** → **Devices & Services**.

## Configuration

1. Enter the **e-mail** and **password** used on Portal Odbiorcy.
2. Choose **70%** or **80%** export recovery (prosumer net-metering).
3. If the account has several PPEs, pick the metering point from the list.

The billing period start and the daily 07:00 refresh need no extra settings.

## Local smoke test

```bash
cp .local/dev_config.example.json .local/dev_config.json
# edit username / password / meter_id
.venv/bin/python scripts/smoke_portal.py
```

## Disclaimer

Unofficial integration. The Portal Odbiorcy API is undocumented and may change.
Use at your own risk; credentials stay in your Home Assistant config entry.
