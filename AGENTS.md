# Enea Energy — Home Assistant custom integration

This repository contains a single Home Assistant **custom integration**, `enea_energy`
(`custom_components/enea_energy/`). It logs into the Polish Enea eBOK portal
(`ebok.enea.pl`), downloads daily/hourly energy balancing data for a metering point,
and writes cumulative hourly **external statistics** into the Home Assistant recorder
(usable on the Energy dashboard). The integration is UI-configured (config flow) and has
no entities/platforms of its own.

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
- There is no automated test suite in this repo.

### Non-obvious gotchas
- **External portal / credentials**: adding the integration only validates the start date
  and `point_of_delivery_id` in the config flow. Actual data fetching happens in the
  coordinator's first refresh, which requires *real* Enea eBOK credentials plus a valid
  `pointOfDeliveryId` and internet access to `ebok.enea.pl`. Without them the config entry
  is still created but shows "retrying setup" — this is expected, not a code bug.
- **Compiler for optional HA deps**: on this image the default `c++`/`cc` alternatives
  point at clang, which fails to build some optional Home Assistant dependencies
  (`pymicro-vad`, `pyspeex-noise`) with `fatal error: 'cstdint' file not found`. The
  alternatives are switched to `gcc-13`/`g++-13` so those wheels build. If you reinstall
  Python or hit that error again, run
  `sudo update-alternatives --set c++ /usr/bin/g++-13` and
  `sudo update-alternatives --set cc /usr/bin/gcc-13`.
- **`default_config` / `go2rtc`**: `default_config` may log a setup failure because the
  optional `go2rtc` WebRTC binary is not installed. This is unrelated to `enea_energy` and
  does not block the config flow, recorder, or the UI.
- The integration UI strings are in Polish (`strings.json`); it appears as **"Enea Energy"**
  in Settings → Devices & Services → Add Integration.
