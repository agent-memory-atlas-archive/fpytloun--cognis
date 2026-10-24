"""Create and inspect a versioned DMG from a completed, signed app on macOS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import tempfile
from pathlib import Path

from sign_bundle import configuration, run, verify_signature
from verify_package import verify_package


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def notarize(path: Path, profile: str) -> None:
    result = json.loads(
        run(
            "/usr/bin/xcrun",
            "notarytool",
            "submit",
            str(path),
            "--keychain-profile",
            profile,
            "--wait",
            "--output-format",
            "json",
            *(
                ["--keychain", os.environ["COGNIS_SIGNING_KEYCHAIN"]]
                if os.environ.get("COGNIS_SIGNING_KEYCHAIN")
                else []
            ),
        )
    )
    if result.get("status") != "Accepted":
        raise ValueError("Apple notarization was not Accepted")


def inspect(app: Path, architecture: str, mode: str, team: str) -> dict:
    verify_package(app, mach_o=True)
    verify_signature(app, mode, team)
    actual = run("/usr/bin/lipo", "-archs", str(app / "Contents/MacOS/Cognis")).strip()
    if actual != architecture:
        raise ValueError(f"Expected {architecture} executable, found {actual}")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    identity = info["CognisBuildIdentity"]
    if mode in {"release", "adhoc"} and (
        identity["dirty"] is not False
        or identity["flavor"] != "standard"
        or identity["version"] != identity["webVersion"]
        or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", identity["version"])
        or not re.fullmatch(r"[a-f0-9]{40}", identity["source"])
        or not re.fullmatch(r"[a-f0-9]{64}", identity["sourceDigest"])
        or info["CFBundleShortVersionString"] != identity["version"]
        or info["CFBundleVersion"] != identity["build"]
        or info["CognisSourceCommit"] != identity["source"]
        or info["CognisWebVersion"] != identity["webVersion"]
    ):
        raise ValueError("Release requires clean standard app and matching app/web versions")
    return identity


def package(app: Path, output: Path, architecture: str, env: dict[str, str]) -> Path:
    if architecture not in {"arm64", "x86_64"}:
        raise ValueError("Unsupported architecture")
    mode, identity, team = configuration(env)
    built = inspect(app, architecture, mode, team)
    tag = env.get("COGNIS_MACOS_RELEASE_TAG")
    if (mode == "adhoc" or tag is not None) and tag != f"macos-v{built['version']}":
        raise ValueError("Mac distribution requires matching macos-v<canonical version> tag")
    suffix = "-development" if mode == "development" else ""
    name = f"cognis-{built['version']}-macos-{architecture}{suffix}"
    output.mkdir(parents=True, exist_ok=True)
    dmg = output / f"{name}.dmg"
    manifest = output / f"{name}.manifest.json"
    checksum = output / f"{name}.sha256"
    if any(path.exists() for path in (dmg, manifest, checksum)):
        raise ValueError("Refusing to replace an existing package or metadata")
    with tempfile.TemporaryDirectory(prefix="cognis-dmg-") as temporary:
        root = Path(temporary)
        stage = root / "stage"
        stage.mkdir()
        copy = stage / app.name
        run("/usr/bin/ditto", str(app), str(copy))
        if mode == "release":
            archive = root / "app.zip"
            run("/usr/bin/ditto", "-c", "-k", "--keepParent", str(copy), str(archive))
            notarize(archive, env["COGNIS_NOTARY_PROFILE"])
            run("/usr/bin/xcrun", "stapler", "staple", str(copy))
            run("/usr/bin/xcrun", "stapler", "validate", str(copy))
            run("/usr/sbin/spctl", "--assess", "--type", "execute", "--verbose=2", str(copy))
        (stage / "Applications").symlink_to("/Applications")
        run(
            "/usr/bin/hdiutil",
            "create",
            "-volname",
            f"Cognis {built['version']}{suffix}",
            "-srcfolder",
            str(stage),
            "-format",
            "UDZO",
            str(dmg),
        )
        if mode == "release":
            run(
                "/usr/bin/codesign",
                "--sign",
                identity,
                "--timestamp",
                *(
                    ["--keychain", env["COGNIS_SIGNING_KEYCHAIN"]]
                    if env.get("COGNIS_SIGNING_KEYCHAIN")
                    else []
                ),
                str(dmg),
            )
            notarize(dmg, env["COGNIS_NOTARY_PROFILE"])
            run("/usr/bin/xcrun", "stapler", "staple", str(dmg))
            run("/usr/bin/xcrun", "stapler", "validate", str(dmg))
            run("/usr/bin/codesign", "--verify", "--strict", str(dmg))
            run(
                "/usr/sbin/spctl",
                "--assess",
                "--type",
                "open",
                "--context",
                "context:primary-signature",
                "--verbose=2",
                str(dmg),
            )
        mount = root / "mounted"
        run(
            "/usr/bin/hdiutil",
            "attach",
            "-readonly",
            "-nobrowse",
            "-mountpoint",
            str(mount),
            str(dmg),
        )
        try:
            mounted = mount / app.name
            if inspect(mounted, architecture, mode, team) != built:
                raise ValueError("Mounted app identity differs from build")
            if (
                not (mount / "Applications").is_symlink()
                or os.readlink(mount / "Applications") != "/Applications"
            ):
                raise ValueError("Missing Applications installation shortcut")
            if mode == "release":
                run("/usr/bin/xcrun", "stapler", "validate", str(mounted))
        finally:
            run("/usr/bin/hdiutil", "detach", str(mount))
    digest = sha256(dmg)
    record = {
        "schema": "cognis.macos.dmg.v1",
        "asset": dmg.name,
        "sha256": digest,
        "architecture": architecture,
        "identity": built,
        "app": app.name,
        "bundleIdentifier": plistlib.loads((app / "Contents/Info.plist").read_bytes())[
            "CFBundleIdentifier"
        ],
        "signing": mode,
        "team": team or None,
        "notarized": mode == "release",
        "mountedVerified": True,
    }
    if tag:
        record.update(
            {
                "releaseTag": tag,
                "appleTrusted": mode == "release",
                "signatureVerified": True,
                "infoPlistBound": True,
                "resourcesSealed": True,
            }
        )
    manifest.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    checksum.write_text(f"{digest}  {dmg.name}\n")
    return dmg


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--architecture", choices=["arm64", "x86_64"], required=True)
    args = parser.parse_args()
    print(package(args.app, args.output, args.architecture, dict(os.environ)))
