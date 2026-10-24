"""Generate a cask only from locally verified, signed, released DMGs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.request import urlopen

REPOSITORY = "fpytloun/cognis"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def metadata(
    directory: Path, *, allow_adhoc: bool = False, release_tag: str | None = None
) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for path in directory.glob("cognis-*.manifest.json"):
        value = json.loads(path.read_text())
        if value.get("schema") != "cognis.macos.dmg.v1":
            continue
        arch = value["architecture"]
        identity = value["identity"]
        version = identity["version"]
        expected = f"cognis-{version}-macos-{arch}.dmg"
        adhoc = value.get("signing") == "adhoc"
        if adhoc and (not allow_adhoc or release_tag is None):
            raise ValueError("Ad-hoc cask requires explicit opt-in and Mac release tag")
        if release_tag is not None and (
            release_tag != f"macos-v{version}"
            or value.get("releaseTag") != release_tag
            or value.get("appleTrusted") is not (not adhoc)
            or any(
                value.get(key) is not True
                for key in ("signatureVerified", "infoPlistBound", "resourcesSealed")
            )
            or not re.fullmatch(r"[a-f0-9]{40}", identity.get("source", ""))
            or not re.fullmatch(r"[a-f0-9]{64}", identity.get("sourceDigest", ""))
            or not re.fullmatch(r"[1-9]\d{0,8}", identity.get("build", ""))
        ):
            raise ValueError("Mac release provenance or tag mismatch")
        if (
            arch not in {"arm64", "x86_64"}
            or arch in records
            or not re.fullmatch(r"\d+\.\d+\.\d+", version)
            or value["asset"] != expected
            or value["app"] != "Cognis.app"
            or value["bundleIdentifier"] != "cz.fpy.cognis.companion"
            or value["signing"] not in ({"adhoc"} if adhoc else {"release"})
            or value["notarized"] is not (not adhoc)
            or value["mountedVerified"] is not True
            or (
                value.get("team") is not None
                if adhoc
                else not re.fullmatch(r"[A-Z0-9]{10}", value.get("team") or "")
            )
            or identity["flavor"] != "standard"
            or identity["dirty"] is not False
            or identity["distribution"] != "homebrew"
            or identity["webVersion"] != version
            or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
            or digest(directory / expected) != value["sha256"]
        ):
            raise ValueError("Cask requires actual matching signed/notarized Homebrew DMGs")
        records[arch] = value
    if set(records) != {"arm64", "x86_64"}:
        raise ValueError("Both architectures are required")
    if records["arm64"]["identity"] != records["x86_64"]["identity"]:
        raise ValueError("Architecture build identities differ")
    if records["arm64"]["team"] != records["x86_64"]["team"]:
        raise ValueError("Architecture signing teams differ")
    if records["arm64"]["signing"] != records["x86_64"]["signing"]:
        raise ValueError("Architecture signing modes differ")
    return records


def asset_url(record: dict) -> str:
    tag = record.get("releaseTag", f"v{record['identity']['version']}")
    if tag not in {f"v{record['identity']['version']}", f"macos-v{record['identity']['version']}"}:
        raise ValueError("Invalid release tag")
    return f"https://github.com/{REPOSITORY}/releases/download/{tag}/{record['asset']}"


def verify_downloads(records: dict[str, dict]) -> None:
    for record in records.values():
        with urlopen(asset_url(record), timeout=120) as response:
            downloaded = hashlib.file_digest(response, "sha256").hexdigest()
        if downloaded != record["sha256"]:
            raise ValueError("Released download checksum mismatch")


def render(records: dict[str, dict]) -> str:
    version = records["arm64"]["identity"]["version"]
    prefix = "macos-v" if records["arm64"].get("releaseTag") else "v"
    caveats = (
        """
  caveats <<~EOS
    This release is ad-hoc signed, not Apple Developer ID signed or notarized.
    After attempting to open Cognis, use System Settings > Privacy & Security >
    Open Anyway only if you trust this download. Managed devices may prohibit
    this override; contact your administrator. Do not disable Gatekeeper.
  EOS
"""
        if records["arm64"]["signing"] == "adhoc"
        else ""
    )
    return f'''cask "cognis" do
  arch arm: "arm64", intel: "x86_64"

  version "{version}"
  sha256 arm:   "{records["arm64"]["sha256"]}",
         intel: "{records["x86_64"]["sha256"]}"

  url "https://github.com/{REPOSITORY}/releases/download/{prefix}#{{version}}/cognis-#{{version}}-macos-#{{arch}}.dmg"
  name "Cognis"
  desc "Desktop companion for Cognis"
  homepage "https://github.com/{REPOSITORY}"

  depends_on macos: :sequoia

  app "Cognis.app"
{caveats}end
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-downloads", action="store_true")
    parser.add_argument("--allow-adhoc", action="store_true")
    parser.add_argument("--release-tag")
    args = parser.parse_args()
    records = metadata(args.assets, allow_adhoc=args.allow_adhoc, release_tag=args.release_tag)
    if not args.verify_downloads:
        parser.error("Cask output requires --verify-downloads after public release")
    verify_downloads(records)
    if args.output.exists():
        parser.error("Refusing to replace an existing cask")
    args.output.write_text(render(records))
