# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2026-11-19

### Fixed

- Cookie paste: bare `EBOK_SESSION` values that contain `=` are no longer mis-parsed (Chrome DevTools paste)
- More robust session probe (`/dashboard` + meter page + silent SSO) before rejecting the session

## [1.1.0] - 2026-11-19

### Breaking

- Password login removed: eBOK now authenticates via Moja Enea OIDC (`moja.enea.pl`) with reCAPTCHA and optional SMS/e-mail 2FA. Configure with browser session cookies (`EBOK_SESSION`, recommended `PHPSESSID`) instead.
- Existing entries without cookies will ask for re-authentication on setup.

### Added

- Session keepalive (every 10 minutes) and cookie rotation persistence
- Silent SSO renewal via moja.enea.pl session when `EBOK_SESSION` expires
- Reauth config flow for expired sessions
- Optional auto-discovery of `pointOfDeliveryId` from the signed-in meter page

### Changed

- Config entry schema version 5
- Local smoke test (`scripts/smoke_ebok.py`) uses cookies from `.local/dev_config.json`

## [1.0.2] - 2026-07-24

### Fixed

- Detect eBOK maintenance / block pages on login and raise a clear unavailable error instead of the opaque `Hidden token field not found` message

## [1.0.1] - 2026-07-13

### Fixed

- HACS / Home Assistant 2026.3+ icon visibility: ship brand images under `brand/` (local brands proxy) and add `mdi:lightning-bolt` fallback in `manifest.json`

## [1.0.0] - 2026-07-13

### Added

- Public release packaging: README, LICENSE (MIT), HACS metadata, integration icon
- English code comments and log messages
- Entity translations (`en` / `pl`) and clearer statistic names
- Config flow reconfigure support and prosumer export recovery (70% / 80%)

### Fixed

- Sync cursor no longer advances past unpublished eBOK days without energy data

[1.1.1]: https://github.com/MIKOLAJW197/enea_energy/releases/tag/v1.1.1
[1.1.0]: https://github.com/MIKOLAJW197/enea_energy/releases/tag/v1.1.0
[1.0.2]: https://github.com/MIKOLAJW197/enea_energy/releases/tag/v1.0.2
[1.0.1]: https://github.com/MIKOLAJW197/enea_energy/releases/tag/v1.0.1
[1.0.0]: https://github.com/MIKOLAJW197/enea_energy/releases/tag/v1.0.0
