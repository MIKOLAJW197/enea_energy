#!/usr/bin/env python3
"""Verify manifest.json version matches an optional git tag."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "custom_components" / "enea_energy" / "manifest.json"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")


def load_manifest_version() -> str:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = str(data.get("version", "")).strip()
    if not SEMVER_RE.fullmatch(version):
        raise SystemExit(f"manifest.json version must be semver (X.Y.Z), got: {version!r}")
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tag",
        help="Git tag to compare against (e.g. v1.0.0). Omit on CI pushes without a tag.",
    )
    args = parser.parse_args()

    manifest_version = load_manifest_version()
    print(f"manifest.json version: {manifest_version}")

    if args.tag:
        match = TAG_RE.fullmatch(args.tag)
        if not match:
            raise SystemExit(f"Release tags must look like v1.0.0, got: {args.tag!r}")
        tag_version = match.group(1)
        if tag_version != manifest_version:
            raise SystemExit(
                f"Tag version {tag_version} does not match manifest.json {manifest_version}"
            )
        print(f"Tag {args.tag} matches manifest.json")


if __name__ == "__main__":
    main()
