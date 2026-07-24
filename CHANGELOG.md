# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.2]: https://github.com/MIKOLAJW197/enea_energy/releases/tag/v1.0.2
[1.0.1]: https://github.com/MIKOLAJW197/enea_energy/releases/tag/v1.0.1
[1.0.0]: https://github.com/MIKOLAJW197/enea_energy/releases/tag/v1.0.0
