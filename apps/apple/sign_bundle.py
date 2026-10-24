"""Own completed bundle signatures; development is explicitly ad-hoc, never trusted."""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path


def run(*args: str) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        # Preserve native diagnostics; do not print credential-bearing arguments.
        print(error.output, file=sys.stderr)
        raise


def configuration(env: dict[str, str]) -> tuple[str, str, str]:
    mode = env.get("COGNIS_SIGNING_MODE", "development")
    if mode not in {"development", "adhoc", "release"}:
        raise ValueError("Signing mode must be development, adhoc or release")
    if env.get("COGNIS_RELEASE_BUILD") == "1" and mode == "development":
        raise ValueError("Release builds require an explicit distribution signing mode")
    if mode == "development":
        return mode, "-", ""
    if mode == "adhoc":
        if (
            env.get("COGNIS_RELEASE_BUILD") != "1"
            or env.get("COGNIS_PACKAGE_FLAVOR", "standard") != "standard"
            or any(
                env.get(key)
                for key in (
                    "COGNIS_SIGNING_IDENTITY",
                    "COGNIS_SIGNING_TEAM",
                    "COGNIS_NOTARY_PROFILE",
                    "COGNIS_SIGNING_KEYCHAIN",
                )
            )
        ):
            raise ValueError(
                "Ad-hoc distribution requires clean standard release mode, no Apple credentials"
            )
        return mode, "-", ""
    identity = env.get("COGNIS_SIGNING_IDENTITY", "")
    team = env.get("COGNIS_SIGNING_TEAM", "")
    if (
        not re.fullmatch(r"[A-Fa-f0-9]{40}", identity)
        or not re.fullmatch(r"[A-Z0-9]{10}", team)
        or not env.get("COGNIS_NOTARY_PROFILE")
        or env.get("COGNIS_RELEASE_BUILD") != "1"
        or env.get("COGNIS_PACKAGE_FLAVOR", "standard") != "standard"
    ):
        raise ValueError(
            "Release requires standard clean-release mode, identity SHA-1, team and notary profile"
        )
    return mode, identity, team


def nested_code(app: Path) -> list[Path]:
    """Sparkle's pinned layout, children before owners; never use --deep to sign."""
    framework = app / "Contents/Frameworks/Sparkle.framework"
    version = framework / "Versions/B"
    return [
        version / "Autoupdate",
        version / "Updater.app",
        version / "XPCServices/Downloader.xpc",
        version / "XPCServices/Installer.xpc",
        framework,
        app,
    ]


def code_entitlements(code: Path) -> dict[str, object]:
    """Read the actual final signature, not an input entitlement template."""
    result = subprocess.run(
        ["/usr/bin/codesign", "-d", "--entitlements", "-", "--xml", str(code)],
        check=True,
        capture_output=True,
    )
    entitlements = plistlib.loads(result.stdout) if result.stdout.strip() else {}
    if not isinstance(entitlements, dict):
        raise ValueError(f"Invalid signed entitlements: {code.name}")
    return entitlements


def verify_signature(app: Path, mode: str, team: str = "") -> None:
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    for code in nested_code(app):
        run("/usr/bin/codesign", "--verify", "--strict", "--verbose=2", str(code))
        details = run("/usr/bin/codesign", "-d", "--verbose=4", str(code))
        if mode in {"development", "adhoc"} and (
            "Signature=adhoc" not in details
            or "TeamIdentifier=not set" not in details
            or "Authority=" in details
        ):
            raise ValueError(f"Expected ad-hoc signature without Apple trust: {code.name}")
        if mode in {"development", "adhoc"} and (
            "com.apple.developer.usernotifications.communication" in code_entitlements(code)
        ):
            raise ValueError(f"Restricted communication entitlement in ad-hoc code: {code.name}")
        if mode == "release" and (
            f"TeamIdentifier={team}" not in details
            or "Authority=Developer ID Application:" not in details
            or "runtime" not in details
        ):
            raise ValueError(f"Missing Developer ID/hardened runtime/team: {code.name}")
    details = run("/usr/bin/codesign", "-d", "--verbose=4", str(app))
    if (
        f"Identifier={info['CFBundleIdentifier']}\n" not in details
        or "Info.plist=not bound" in details
        or not re.search(r"^Info.plist entries=[1-9]\d*$", details, re.M)
        or "Sealed Resources=none" in details
        or not re.search(r"^Sealed Resources version=\d+ rules=\d+ files=[1-9]\d*$", details, re.M)
    ):
        raise ValueError("Bundle identifier, bound Info.plist and resource seal are required")


def sign_bundle(app: Path, env: dict[str, str]) -> None:
    mode, identity, team = configuration(env)
    if sys.platform != "darwin":
        raise ValueError("Bundle signing requires macOS")
    if mode == "release":
        keychain = env.get("COGNIS_SIGNING_KEYCHAIN")
        identities = run(
            "/usr/bin/security",
            "find-identity",
            "-v",
            "-p",
            "codesigning",
            *([keychain] if keychain else []),
        )
        if identity.upper() not in identities.upper():
            raise ValueError("Configured signing identity is not available")
    for code in nested_code(app):
        if not code.exists() or code.is_symlink():
            raise ValueError(f"Missing or symlinked signing target: {code}")
        args = ["/usr/bin/codesign", "--force", "--sign", identity]
        if mode == "release":
            args += ["--options", "runtime", "--timestamp"]
            if env.get("COGNIS_SIGNING_KEYCHAIN"):
                args += ["--keychain", env["COGNIS_SIGNING_KEYCHAIN"]]
        else:
            # Explicitly replace inherited entitlements on every nested target.
            # A valid resource seal alone does not imply AMFI launch acceptance.
            args += [
                "--timestamp=none",
                "--entitlements",
                str(Path(__file__).with_name("adhoc.entitlements")),
            ]
        # Sparkle 2.9.3's non-sandboxed helpers require no added entitlements.
        # Signing each owning bundle seals its executable and resources together.
        run(*args, str(code))
    verify_signature(app, mode, team)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path, nargs="?")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    mode, _, team = configuration(dict(os.environ))
    if not args.check_config:
        if args.app is None:
            parser.error("app is required")
        if args.verify:
            verify_signature(args.app, mode, team)
        else:
            sign_bundle(args.app, dict(os.environ))
        print(f"PASS: whole-bundle {mode} signature (not notification authorization evidence)")
