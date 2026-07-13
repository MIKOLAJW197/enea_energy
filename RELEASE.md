# Release process

This repository uses **semantic versioning** (`MAJOR.MINOR.PATCH`) and git tags prefixed with `v`.

## First-time setup (done)

- `manifest.json` → `version`
- GitHub Actions: **CI** on push/PR, **Release** on tag push
- `CHANGELOG.md` for user-facing notes

## Cutting a new release

1. Update `custom_components/enea_energy/manifest.json` → bump `version` (e.g. `1.0.1`).
2. Add a section to `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD`.
3. Commit on `main` (e.g. `Bump version to 1.0.1`).
4. Create and push the tag (tag must match manifest, with a `v` prefix):

   ```bash
   git tag v1.0.1
   git push origin v1.0.1
   ```

5. GitHub Actions **Release** workflow will:
   - run lint + syntax checks
   - verify tag ↔ `manifest.json` version
   - attach `enea_energy.zip` (integration folder) to the GitHub Release

## Manual install asset

`enea_energy.zip` contains `custom_components/enea_energy/`. Unzip into your Home Assistant config:

```text
config/custom_components/enea_energy/
```

HACS users install from the repository tag; they do not need the zip.

## Version rules

| Change | Bump |
| --- | --- |
| Bug fix, no breaking config/API change | PATCH (`1.0.x`) |
| New feature, backward compatible | MINOR (`1.x.0`) |
| Breaking config migration or behavior | MAJOR (`x.0.0`) |

Config entry migration version (`ConfigFlow.VERSION`) is separate from the integration release version in `manifest.json`.
