# Enea Energy — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/MIKOLAJW197/enea_energy.svg)](https://github.com/MIKOLAJW197/enea_energy/releases)

Home Assistant custom integration for the Polish **Enea eBOK** portal
([ebok.enea.pl](https://ebok.enea.pl)). It downloads daily/hourly energy balancing
data for your metering point and writes **external statistics** to the Home Assistant
recorder (Energy dashboard + Lovelace statistics cards).

> **Since ~October 2026** eBOK signs in through **Moja Enea** (`moja.enea.pl`) with
> reCAPTCHA and sometimes an SMS code. This integration does **not** log in with your
> password. You sign in once in a normal browser and paste two session cookies into HA.

## Features

- Browser session cookies (`EBOK_SESSION` + recommended `PHPSESSID`)
- Session keepalive every 10 minutes + cookie rotation (survives HA restarts)
- Silent SSO renewal via moja.enea.pl when the eBOK cookie expires
- Historical backfill from a configurable start date
- Hourly cumulative grid import / export statistics
- Energy balance sensor (prosumer export recovery 70% / 80%)
- Daily sync at 20:00 local time
- Reconfigure + reauth flows when the session dies

## Requirements

- Home Assistant **2024.1** or newer
- The **Recorder** integration enabled
- An Enea eBOK / Moja Enea account with access to the metering point
- A desktop browser (Chrome / Edge / Firefox / Safari) to copy cookies

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

```text
config/
  custom_components/
    enea_energy/
      __init__.py
      manifest.json
      ...
```

---

## Sign-in (cookies) — do this every time HA asks for a session

Password login is **impossible** to automate (reCAPTCHA Enterprise + optional SMS).
Other Enea HA projects use the same cookie hand-over.

### Step A — Log in in a normal browser

1. Open a **desktop** browser (preferably a normal window, not a profile you will log out of).
2. Go to [https://ebok.enea.pl](https://ebok.enea.pl) — you will be redirected to Moja Enea.
3. Accept cookies if asked.
4. Sign in with e-mail + password.
5. Complete **reCAPTCHA** and, if shown, the **6-digit SMS / e-mail code**.
6. You should land on the eBOK dashboard (or the list of contracts).
7. **Do not click „Wyloguj”.** Closing the tab is OK; logging out kills the session.

If you have **several contracts**, click **Zobacz** on the correct one first
(so the session is bound to that client).

### Step B — Copy `EBOK_SESSION` (required)

**Chrome / Edge**

1. Press `F12` (macOS: `Cmd+Option+I`) → tab **Application**.
2. Left sidebar: **Storage** → **Cookies** → `https://ebok.enea.pl`.
3. Find the row named **`EBOK_SESSION`**.
4. Double-click the **Value** cell → copy the whole string
   (or right-click → Copy).

**Firefox**

1. `F12` → **Storage** → **Cookies** → `https://ebok.enea.pl`.
2. Copy the value of **`EBOK_SESSION`**.

**Safari**

1. Enable Develop menu: Safari → Settings → Advanced → “Show features for web developers”.
2. **Develop** → **Show Web Inspector** → **Storage** → **Cookies**.
3. Select `ebok.enea.pl` → copy **`EBOK_SESSION`**.

**Preferred paste format** (avoids Chrome copy quirks):

```text
EBOK_SESSION=wklej_tu_całą_wartość_z_kolumny_Value
```

Also accepted:

- just the Value cell (even if it contains `=` characters),
- a full `Cookie:` header from the Network tab.

### Step C — Copy `PHPSESSID` (strongly recommended)

Same DevTools → Cookies, but for domain **`https://moja.enea.pl`**.

Copy **`PHPSESSID`**. This lets HA renew the eBOK session via silent SSO without
another CAPTCHA, as long as the Moja Enea session is still valid.

### Step D — Paste into Home Assistant

1. **Settings** → **Devices & Services** → **Add Integration** → **Enea Energy**
   (or **Reconfigure** / reauth if the entry already exists).
2. Paste:

| Field in HA | What to paste |
| --- | --- |
| **EBOK_SESSION (ebok.enea.pl)** | from Step B (required) |
| **PHPSESSID (moja.enea.pl)** | from Step C (recommended) |
| **Point of delivery ID** | optional — leave empty to auto-detect, or paste UUID (see below) |
| **Current client ID** | only if you have multiple contracts — UUID from the URL (see below) |
| **History start date** | first day to backfill |
| **Export recovery %** | `80` (default) or `70` for prosumer settlement |

3. Submit. HA validates the session against eBOK immediately.
4. Leave the browser logged in (or at least don’t log out).

### After setup

- HA touches eBOK about every **10 minutes** so the session does not idle out.
- Rotated cookies are saved in the config entry (survive restarts).
- When both cookies finally die, HA shows **Re-authentication required** —
  repeat Steps A–D (only the two cookie fields).

---

## Optional IDs (when auto-detect is not enough)

### `pointOfDeliveryId` (PPE)

Usually discovered automatically. If the setup form complains:

1. While signed in, open DevTools → **Network**.
2. Open the energy balancing chart for your meter.
3. Find a **POST** to `/meter/summaryBalancingChart`.
4. In the form body, copy `pointOfDeliveryId`
   (looks like `c3ebdcdc-9908-e911-80de-005056b326a5`).

### `current_client_id` (multiple contracts)

This is **not** the numeric “numer kontrahenta” from the contract list.

1. On **Lista kontrahentów**, click **Zobacz** on the right contract.
2. Look at the address bar — it should contain  
   `/dashboard/select-current-client/<UUID>`.
3. Copy that **UUID** into **Current client ID**.

Example: contractor number `29206995` → UUID like
`9359e084-18a1-f011-9102-005056ab29b0`.

---

## Configuration reference

| Field | Required | Description |
| --- | --- | --- |
| `ebok_cookie` | yes | `EBOK_SESSION` from `ebok.enea.pl` |
| `sso_cookie` | recommended | `PHPSESSID` from `moja.enea.pl` |
| `point_of_delivery_id` | no* | PPE UUID (`pointOfDeliveryId`) |
| `current_client_id` | no* | UUID from `select-current-client/…` |
| `start_date` | no | History start (default ~2 years ago) |
| `export_recovery_percent` | no | `70` or `80` (default `80`) |

\*Required if auto-discovery fails or you have several contracts.

## Entities and statistics

| Name | Type | Description |
| --- | --- | --- |
| **Energy balance** | Sensor | Period balance: adjusted export − grid import (kWh) |
| **Grid import (cumulative, hourly)** | External statistic | Cumulative grid consumption |
| **Grid export (cumulative, hourly)** | External statistic | Cumulative export after recovery % |

Statistic IDs appear in the integration log on first sync and under
**Developer Tools** → **Statistics**. Use a Lovelace **Statistics** card with
the `statistic_id`.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| **Re-authentication required** / invalid session | Repeat Sign-in Steps A–D with **fresh** cookies. Don’t log out in the browser. |
| Setup error after pasting cookies | Make sure you copied from the correct domain (`ebok` vs `moja`). Try pasting only the raw value. |
| Wrong house / empty data | Set `current_client_id` to the UUID of the correct contract, then reconfigure. |
| Empty recent days | eBOK often publishes with 1–2 days lag; sync goes through yesterday by default. |
| Old password-based entry | Remove it or use reauth — password login no longer works (v1.1.0+). |

Debug logging:

```yaml
logger:
  logs:
    custom_components.enea_energy: debug
```

## Local development (maintainers)

```bash
python3 -m venv .venv && .venv/bin/pip install aiohttp
cp .local/dev_config.example.json .local/dev_config.json   # gitignored
# fill ebok_cookie + sso_cookie, then:
.venv/bin/python scripts/smoke_ebok.py --day 2026-02-01
```

## Disclaimer

Unofficial community integration — not affiliated with or endorsed by Enea S.A.
Use at your own risk. eBOK / Moja Enea behaviour may change without notice.

## Contributing / releases

- [CHANGELOG.md](CHANGELOG.md) — version history
- [RELEASE.md](RELEASE.md) — how to cut a new release (maintainers)

## License

[MIT](LICENSE)
