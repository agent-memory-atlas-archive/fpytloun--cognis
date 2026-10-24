"""Ad-hoc distribution contract tests; synthetic bytes are not release evidence."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APPLE = Path(__file__).resolve().parents[1]
ROOT = APPLE.parents[1]
sys.path.insert(0, str(APPLE))
package_dmg = __import__("package_dmg")
sign_bundle = __import__("sign_bundle")

spec = importlib.util.spec_from_file_location(
    "adhoc_cask", ROOT / "packaging/homebrew/generate_cask.py"
)
cask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cask)

ENV = {
    "COGNIS_SIGNING_MODE": "adhoc",
    "COGNIS_RELEASE_BUILD": "1",
    "COGNIS_PACKAGE_FLAVOR": "standard",
    "COGNIS_MACOS_RELEASE_TAG": "macos-v0.17.1",
}
IDENTITY = {
    "version": "0.17.1",
    "webVersion": "0.17.1",
    "build": "7",
    "flavor": "standard",
    "dirty": False,
    "distribution": "homebrew",
    "source": hashlib.sha1(b"synthetic source").hexdigest(),
    "sourceDigest": hashlib.sha256(b"synthetic tree").hexdigest(),
}


def fixtures(root: Path) -> list[Path]:
    """Write synthetic dual-architecture payloads, never a real cask or DMG."""
    paths = []
    for arch in ("arm64", "x86_64"):
        name = f"cognis-0.17.1-macos-{arch}.dmg"
        content = f"synthetic payload {arch}".encode()
        (root / name).write_bytes(content)
        record = {
            "schema": "cognis.macos.dmg.v1",
            "asset": name,
            "architecture": arch,
            "sha256": hashlib.sha256(content).hexdigest(),
            "identity": IDENTITY,
            "app": "Cognis.app",
            "bundleIdentifier": "cz.fpy.cognis.companion",
            "signing": "adhoc",
            "team": None,
            "notarized": False,
            "appleTrusted": False,
            "signatureVerified": True,
            "infoPlistBound": True,
            "resourcesSealed": True,
            "mountedVerified": True,
            "releaseTag": "macos-v0.17.1",
        }
        path = root / name.replace(".dmg", ".manifest.json")
        path.write_text(json.dumps(record))
        paths.append(path)
    return paths


class AdhocSigningTests(unittest.TestCase):
    def test_package_records_actual_bytes_without_claiming_trust(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "Cognis.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(
                plistlib.dumps({"CFBundleIdentifier": "cz.fpy.cognis.companion"})
            )
            commands = []

            def command(*args):
                commands.append(args)
                if args[:2] == ("/usr/bin/hdiutil", "create"):
                    Path(args[-1]).write_bytes(b"synthetic final dmg bytes")
                if args[:2] == ("/usr/bin/hdiutil", "attach"):
                    mount = Path(args[args.index("-mountpoint") + 1])
                    mount.mkdir()
                    (mount / "Applications").symlink_to("/Applications")
                return ""

            with (
                patch.object(package_dmg, "inspect", return_value=IDENTITY),
                patch.object(package_dmg, "run", side_effect=command),
            ):
                dmg = package_dmg.package(app, root / "dist", "arm64", ENV)
                record = json.loads(dmg.with_suffix(".manifest.json").read_text())
                self.assertEqual(record["sha256"], hashlib.sha256(dmg.read_bytes()).hexdigest())
                self.assertEqual(record["signing"], "adhoc")
                self.assertIsNone(record["team"])
                self.assertIs(record["notarized"], False)
                self.assertIs(record["appleTrusted"], False)
                self.assertTrue(record["mountedVerified"])
                self.assertTrue(record["infoPlistBound"])
                self.assertNotIn("-development", dmg.name)
                self.assertFalse(
                    any("notarytool" in args or "stapler" in args for args in commands)
                )
                with self.assertRaises(ValueError):
                    package_dmg.package(app, root / "dist", "arm64", ENV)

    def test_explicit_mode_and_trusted_fail_closed(self):
        self.assertEqual(sign_bundle.configuration(ENV), ("adhoc", "-", ""))
        for delta in (
            {"COGNIS_RELEASE_BUILD": "0"},
            {"COGNIS_PACKAGE_FLAVOR": "preview"},
            {"COGNIS_SIGNING_TEAM": "TESTONLY01"},
            {"COGNIS_SIGNING_IDENTITY": "-"},
            {"COGNIS_NOTARY_PROFILE": "ci"},
            {"COGNIS_SIGNING_KEYCHAIN": "/tmp/test"},
            {"COGNIS_SIGNING_MODE": "release"},
            {"COGNIS_SIGNING_MODE": "development"},
        ):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                sign_bundle.configuration(ENV | delta)
        trusted = ENV | {
            "COGNIS_SIGNING_MODE": "release",
            "COGNIS_SIGNING_IDENTITY": hashlib.sha1(b"synthetic certificate").hexdigest(),
            "COGNIS_SIGNING_TEAM": "TESTONLY01",
            "COGNIS_NOTARY_PROFILE": "ci",
        }
        self.assertEqual(sign_bundle.configuration(trusted)[0], "release")
        for key in ("COGNIS_SIGNING_IDENTITY", "COGNIS_SIGNING_TEAM", "COGNIS_NOTARY_PROFILE"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                sign_bundle.configuration(trusted | {key: ""})

    def test_signature_trust_and_seals(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            (app / "Contents").mkdir()
            (app / "Contents/Info.plist").write_bytes(
                plistlib.dumps({"CFBundleIdentifier": "cz.fpy.cognis.companion"})
            )
            details = (
                "Identifier=cz.fpy.cognis.companion\nSignature=adhoc\n"
                "TeamIdentifier=not set\nInfo.plist entries=30\n"
                "Sealed Resources version=2 rules=13 files=80\n"
            )
            with (
                patch.object(sign_bundle, "run", return_value=details),
                patch.object(sign_bundle, "code_entitlements", return_value={}),
            ):
                sign_bundle.verify_signature(app, "adhoc")
                with self.assertRaises(ValueError):
                    sign_bundle.verify_signature(app, "release", "TESTONLY01")
            for broken in (
                details.replace("Signature=adhoc", "Signature=unknown"),
                details.replace("TeamIdentifier=not set", "TeamIdentifier=TESTONLY01"),
                details + "Authority=Developer ID Application: synthetic\n",
                details.replace("Info.plist entries=30", "Info.plist=not bound"),
                details.replace(
                    "Sealed Resources version=2 rules=13 files=80", "Sealed Resources=none"
                ),
            ):
                with (
                    patch.object(sign_bundle, "run", return_value=broken),
                    patch.object(sign_bundle, "code_entitlements", return_value={}),
                    self.assertRaises(ValueError),
                ):
                    sign_bundle.verify_signature(app, "adhoc")

    def test_inspect_binds_version_source_and_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            (app / "Contents").mkdir()
            info = {
                "CognisBuildIdentity": IDENTITY,
                "CFBundleShortVersionString": IDENTITY["version"],
                "CFBundleVersion": IDENTITY["build"],
                "CognisSourceCommit": IDENTITY["source"],
                "CognisWebVersion": IDENTITY["webVersion"],
            }
            with (
                patch.object(package_dmg, "verify_package"),
                patch.object(package_dmg, "verify_signature"),
                patch.object(package_dmg, "run", return_value="arm64\n"),
            ):
                (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
                self.assertEqual(package_dmg.inspect(app, "arm64", "adhoc", ""), IDENTITY)
                with self.assertRaises(ValueError):
                    package_dmg.inspect(app, "x86_64", "adhoc", "")
                for field, value in (
                    ("dirty", True),
                    ("webVersion", "0.17.0"),
                    ("flavor", "preview"),
                ):
                    broken = copy.deepcopy(info)
                    broken["CognisBuildIdentity"][field] = value
                    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(broken))
                    with self.assertRaises(ValueError):
                        package_dmg.inspect(app, "arm64", "adhoc", "")
            with (
                patch.object(package_dmg, "inspect", return_value=IDENTITY),
                self.assertRaises(ValueError),
            ):
                package_dmg.package(
                    app, app / "dist", "arm64", ENV | {"COGNIS_MACOS_RELEASE_TAG": "v0.17.1"}
                )


class AdhocCaskTests(unittest.TestCase):
    def read(self, root: Path):
        return cask.metadata(root, allow_adhoc=True, release_tag="macos-v0.17.1")

    def test_opt_in_urls_hashes_and_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures(root)
            with self.assertRaises(ValueError):
                cask.metadata(root)
            with self.assertRaises(ValueError):
                cask.metadata(root, allow_adhoc=True)
            records = self.read(root)
            rendered = cask.render(records)
            self.assertIn("macos-v#{version}", rendered)
            self.assertIn("Open Anyway", rendered)
            self.assertIn("not Apple Developer ID signed or notarized", rendered)
            for record in records.values():
                self.assertIn(record["sha256"], rendered)
                self.assertIn("/macos-v0.17.1/", cask.asset_url(record))

            def download(url, timeout):
                self.assertEqual(timeout, 120)
                return io.BytesIO((root / url.rsplit("/", 1)[-1]).read_bytes())

            with patch.object(cask, "urlopen", side_effect=download):
                cask.verify_downloads(records)
            with (
                patch.object(cask, "urlopen", return_value=io.BytesIO(b"wrong download")),
                self.assertRaises(ValueError),
            ):
                cask.verify_downloads(records)

    def test_corrupt_or_untruthful_manifests_fail(self):
        for field, value in (
            ("team", "TESTONLY01"),
            ("notarized", True),
            ("appleTrusted", True),
            ("mountedVerified", False),
            ("resourcesSealed", False),
            ("infoPlistBound", False),
            ("signatureVerified", False),
            ("releaseTag", "v0.17.1"),
            ("architecture", "aarch64"),
            ("asset", "../outside.dmg"),
            ("sha256", "0" * 64),
            ("signing", "development"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paths = fixtures(root)
                data = json.loads(paths[0].read_text())
                data[field] = value
                paths[0].write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    self.read(root)
        for field, value in (
            ("version", "0.17.0"),
            ("webVersion", "0.17.0"),
            ("source", "bad"),
            ("sourceDigest", "bad"),
            ("build", "0"),
            ("dirty", True),
            ("distribution", "direct"),
            ("flavor", "preview"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paths = fixtures(root)
                data = json.loads(paths[0].read_text())
                data["identity"][field] = value
                paths[0].write_text(json.dumps(data))
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.read(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = fixtures(root)
            paths[0].unlink()
            with self.assertRaises(ValueError):
                self.read(root)


if __name__ == "__main__":
    unittest.main()
