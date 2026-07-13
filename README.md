# Enea Energy — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/MIKOLAJW197/enea_energy.svg)](https://github.com/MIKOLAJW197/enea_energy/releases)

Home Assistant custom integration that logs into the Polish **Enea eBOK** portal ([ebok.enea.pl](https://ebok.enea.pl)), downloads daily and hourly energy balancing data for your metering point, and writes **external statistics** to the Home Assistant recorder (usable on the Energy dashboard and Lovelace statistics cards).

## Features

- Automatic login to Enea eBOK (Cookiebot consent handled in code)
- Historical backfill from a configurable start date
- Hourly cumulative grid import and export statistics
- Energy balance sensor for the current billing period (prosumer export recovery % supported)
- Daily sync at 20:00 local time plus coordinator refresh on setup
- Reconfigure flow to change credentials, metering point, or start date without re-adding the integration

## Requirements

- Home Assistant **2024.1** or newer
- The **Recorder** integration enabled (dependency)
- A valid Enea eBOK account with access to the metering point
- `pointOfDeliveryId` UUID for your metering point (see below)

## Installation

### HACS (recommended)

1. Open **HACS** → **Integrations** → **⋮** → **Custom repositories**.
2. Add `https://github.com/MIKOLAJW197/enea_energy` as type **Integration**.
3. Search for **Enea Energy**, install, and restart Home Assistant.
4. Go to **Settings** → **Devices & Services** → **Add Integration** → **Enea Energy**.

### Manual

1. Download the [latest release](https://github.com/MIKOLAJW197/enea_energy/releases) or clone this repository.
2. Copy the folder `custom_components/enea_energy` into your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.
4. Add the integration via **Settings** → **Devices & Services**.

Directory layout after manual install:

```text
config/
  custom_components/
    enea_energy/
      __init__.py
      manifest.json
      ...
```

## Configuration

| Field | Description |
| --- | --- |
| **E-mail (eBOK)** | Your eBOK login e-mail |
| **Password** | eBOK password |
| **Point of delivery ID** | UUID sent as `pointOfDeliveryId` to `summaryBalancingChart` |
| **Current client ID** (optional) | Required when one eBOK account has multiple contracts — UUID from `…/dashboard/select-current-client/<UUID>` |
| **History start date** | First day to backfill (default: ~2 years ago) |
| **Export recovery %** | Share of exported energy counted toward balance (70% or 80%, default 80% for prosumers) |

### Finding `pointOfDeliveryId`

1. Log in to [ebok.enea.pl](https://ebok.enea.pl) in a desktop browser.
2. Open **Developer Tools** → **Network**.
3. Open the energy balancing chart for your metering point.
4. Find a POST request to `/meter/summaryBalancingChart`.
5. Copy the `pointOfDeliveryId` value from the form body.

If you have multiple clients on one account, click the correct contract first and copy the UUID from the `select-current-client/…` URL.

## Entities and statistics

| Name | Type | Description |
| --- | --- | --- |
| **Energy balance** | Sensor | Period balance: adjusted export minus grid import (kWh) |
| **Grid import (cumulative, hourly)** | External statistic | Cumulative grid consumption |
| **Grid export (cumulative, hourly)** | External statistic | Cumulative export after recovery % |

Statistic IDs are logged on first sync and visible under **Developer Tools** → **Statistics**. Use a Lovelace **Statistics** card with the statistic ID to chart hourly data.

## Troubleshooting

- **Setup keeps retrying**: The config flow only validates the start date and point ID. The first data fetch needs working eBOK credentials and network access. Check logs for `enea_energy`.
- **Empty recent days**: eBOK often publishes full days with a delay; the integration syncs through yesterday by default.
- **401 / HTML instead of JSON**: Session expired — the integration retries login automatically; reconfigure credentials if needed.
- **Debug logging**: Add to `configuration.yaml`:

  ```yaml
  logger:
    logs:
      custom_components.enea_energy: debug
  ```

## Disclaimer

This is an unofficial community integration. It is not affiliated with or endorsed by Enea S.A. Use at your own risk. eBOK HTML/API behavior may change without notice.

## License

[MIT](LICENSE)
