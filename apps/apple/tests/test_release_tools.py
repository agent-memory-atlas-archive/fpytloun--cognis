"""Synthetic filesystem/command tests; not OS signing or release evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APPLE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APPLE))
package_dmg = __import__("package_dmg")
sign_bundle = __import__("sign_bundle")

spec = importlib.util.spec_from_file_location(
    "generate_cask", APPLE.parents[1] / "packaging/homebrew/generate_cask.py"
)
cask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cask)


class SigningTests(unittest.TestCase):
    @unittest.skipUnless(
        sys.platform == "darwin" and os.environ.get("COGNIS_TEST_SIGNED_APP"),
        "Requires an explicitly supplied real ad-hoc Mac bundle",
    )
    def test_real_final_entitlements_and_tampered_bundle_rejection(self):
        import shutil
        import subprocess

        app = Path(os.environ["COGNIS_TEST_SIGNED_APP"])
        sign_bundle.verify_signature(app, "development")
        for code in sign_bundle.nested_code(app):
            with self.subTest(code=str(code)):
                self.assertNotIn(
                    "com.apple.developer.usernotifications.communication",
                    sign_bundle.code_entitlements(code),
                )
        with tempfile.TemporaryDirectory() as temporary:
            tampered = Path(temporary) / app.name
            shutil.copytree(app, tampered, symlinks=True)
            info = tampered / "Contents/Info.plist"
            metadata = plistlib.loads(info.read_bytes())
            metadata["CFBundleDisplayName"] = "Tampered signing regression"
            info.write_bytes(plistlib.dumps(metadata))
            with self.assertRaises(subprocess.CalledProcessError):
                sign_bundle.verify_signature(tampered, "development")

    def test_adhoc_signing_explicitly_clears_entitlements_on_every_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "Cognis.app"
            for code in sign_bundle.nested_code(app):
                code.mkdir(parents=True, exist_ok=True)
            for mode in ("development", "adhoc", "release"):
                with (
                    patch.object(sign_bundle.sys, "platform", "darwin"),
                    patch.object(sign_bundle, "configuration", return_value=(mode, "-", "")),
                    patch.object(sign_bundle, "verify_signature"),
                    patch.object(sign_bundle, "run", return_value="-") as command,
                ):
                    sign_bundle.sign_bundle(app, {})
                    signed = [
                        call.args for call in command.call_args_list if "--force" in call.args
                    ]
                    for args in signed:
                        self.assertEqual("--entitlements" in args, mode != "release")
                        if mode != "release":
                            template = Path(args[args.index("--entitlements") + 1])
                            self.assertEqual(plistlib.loads(template.read_bytes()), {})

    def test_development_never_becomes_release_by_fallback(self):
        self.assertEqual(sign_bundle.configuration({}), ("development", "-", ""))
        for env in (
            {"COGNIS_RELEASE_BUILD": "1"},
            {"COGNIS_SIGNING_MODE": "release"},
            {"COGNIS_SIGNING_MODE": "unsigned"},
        ):
            with self.assertRaises(ValueError):
                sign_bundle.configuration(env)

    def test_nested_signing_order_and_bundle_seal_inspection(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "Cognis.app"
            for code in sign_bundle.nested_code(app):
                code.mkdir(parents=True, exist_ok=True)
            (app / "Contents/Info.plist").write_bytes(
                plistlib.dumps({"CFBundleIdentifier": "cz.fpy.cognis.companion"})
            )
            details = (
                "Identifier=cz.fpy.cognis.companion\n"
                "Signature=adhoc\nTeamIdentifier=not set\n"
                "Info.plist entries=30\nSealed Resources version=2 rules=13 files=80\n"
            )
            with (
                patch.object(sign_bundle.sys, "platform", "darwin"),
                patch.object(sign_bundle, "code_entitlements", return_value={}),
                patch.object(sign_bundle, "run", return_value=details) as command,
            ):
                sign_bundle.sign_bundle(app, {})
                signed = [call.args for call in command.call_args_list if "--force" in call.args]
                self.assertEqual(
                    [args[-1] for args in signed],
                    [str(path) for path in sign_bundle.nested_code(app)],
                )
                self.assertTrue(all("--deep" not in args for args in signed))
                self.assertTrue(all(args[3] == "-" for args in signed))
            for broken in (
                details.replace("cz.fpy.cognis.companion", "CognisCompanion"),
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
                    sign_bundle.verify_signature(app, "development")

    def test_actual_entitlement_reader_and_restricted_nested_signatures_fail_closed(self):
        import subprocess

        restricted = {"com.apple.developer.usernotifications.communication": True}
        with patch.object(
            sign_bundle.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, plistlib.dumps(restricted), b""),
        ):
            self.assertEqual(sign_bundle.code_entitlements(Path("Signed.app")), restricted)
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            (app / "Contents").mkdir()
            (app / "Contents/Info.plist").write_bytes(
                plistlib.dumps({"CFBundleIdentifier": "cz.fpy.cognis.companion"})
            )
            details = (
                "Identifier=cz.fpy.cognis.companion\nSignature=adhoc\nTeamIdentifier=not set\n"
                "Info.plist entries=30\nSealed Resources version=2 rules=13 files=80\n"
            )
            for target in sign_bundle.nested_code(app):
                for mode in ("development", "adhoc"):
                    with (
                        self.subTest(target=target.name, mode=mode),
                        patch.object(sign_bundle, "run", return_value=details),
                        patch.object(
                            sign_bundle,
                            "code_entitlements",
                            side_effect=lambda code, target=target: (
                                restricted if code == target else {}
                            ),
                        ),
                        self.assertRaisesRegex(ValueError, "Restricted communication entitlement"),
                    ):
                        sign_bundle.verify_signature(app, mode)

    def test_notary_rejection_is_not_success(self):
        with (
            patch.object(package_dmg, "run", return_value='{"status":"Invalid"}'),
            self.assertRaises(ValueError),
        ):
            package_dmg.notarize(Path("synthetic-test.dmg"), "test-only")


class CaskTests(unittest.TestCase):
    def fixtures(self, directory: Path) -> list[Path]:
        # These are labelled synthetic bytes, never distributed or written to a tap.
        manifests = []
        for arch in ("arm64", "x86_64"):
            name = f"cognis-0.17.1-macos-{arch}.dmg"
            content = f"synthetic unit-test payload {arch}".encode()
            (directory / name).write_bytes(content)
            manifest = directory / name.replace(".dmg", ".manifest.json")
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "cognis.macos.dmg.v1",
                        "asset": name,
                        "architecture": arch,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "app": "Cognis.app",
                        "bundleIdentifier": "cz.fpy.cognis.companion",
                        "team": "TESTONLY01",
                        "signing": "release",
                        "notarized": True,
                        "mountedVerified": True,
                        "identity": {
                            "version": "0.17.1",
                            "webVersion": "0.17.1",
                            "flavor": "standard",
                            "dirty": False,
                            "distribution": "homebrew",
                        },
                    }
                )
            )
            manifests.append(manifest)
        return manifests

    def test_cask_uses_hashes_of_exact_architecture_payloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixtures(root)
            records = cask.metadata(root)
            output = cask.render(records)
            for record in records.values():
                self.assertIn(record["sha256"], output)
                self.assertIn("/releases/download/v0.17.1/", cask.asset_url(record))
            self.assertNotIn("auto_updates", output)
            self.assertNotIn("no_quarantine", output)
            (root / records["arm64"]["asset"]).write_bytes(b"tampered synthetic test bytes")
            with self.assertRaises(ValueError):
                cask.metadata(root)

    def test_development_stale_and_incomplete_metadata_rejected(self):
        for field, value in (
            ("signing", "development"),
            ("notarized", False),
            ("asset", "../escape.dmg"),
            ("team", None),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifests = self.fixtures(root)
                data = json.loads(manifests[0].read_text())
                data[field] = value
                manifests[0].write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    cask.metadata(root)
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
            cask.metadata(Path(temporary))


if __name__ == "__main__":
    unittest.main()
