import importlib.util
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SPEC = importlib.util.spec_from_file_location(
    "install_preview", Path(__file__).resolve().parents[1] / "install_preview.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
BASE = "23920d5b7903e74ef5f411c022943d45f13fbb49"


class PreviewInstallTests(unittest.TestCase):
    def bundle(self, path, bundle_id=MODULE.PREVIEW_ID):
        (path / "Contents").mkdir(parents=True)
        (path / "Contents/Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleIdentifier": bundle_id,
                    "CognisPackageFlavor": "preview",
                    "CognisSourceCommit": BASE,
                    "CognisBuildIdentity": {"dirty": False},
                }
            )
        )

    def test_first_install_and_wrong_identity_never_replace_pwa_or_user_state(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "verify_package"):
            root = Path(directory)
            source, applications = root / MODULE.PREVIEW_NAME, root / "Applications"
            self.bundle(source)
            applications.mkdir()
            pwa = applications / "Cognis.app"
            pwa.mkdir()
            (pwa / "user-pwa").write_text("preserve")
            user_data = root / "Library/WebKit"
            user_data.mkdir(parents=True)
            (user_data / "state").write_text("preserve")
            installed = MODULE.install(source, applications, BASE)
            self.assertEqual(installed.name, MODULE.PREVIEW_NAME)
            self.assertTrue((pwa / "user-pwa").is_file())
            self.assertEqual((user_data / "state").read_text(), "preserve")
            info = installed / "Contents/Info.plist"
            info.write_bytes(
                plistlib.dumps({"CFBundleIdentifier": "cz.fpy.cognis.companion.acceptance"})
            )
            with self.assertRaises(ValueError):
                MODULE.install(source, applications, BASE)
            self.assertEqual(
                plistlib.loads(info.read_bytes())["CFBundleIdentifier"],
                "cz.fpy.cognis.companion.acceptance",
            )

    def test_atomic_exchange_boundary_and_previous_bundle_preserved(self):
        def injected_exchange(left, right):
            # Fixtures only: production uses one Darwin RENAME_SWAP operation.
            temporary = right.parent / "exchange-fixture"
            right.rename(temporary)
            left.rename(right)
            temporary.rename(left)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(MODULE, "verify_package"),
            patch.object(MODULE, "exchange", side_effect=injected_exchange) as exchange,
        ):
            root = Path(directory)
            source, applications = root / "source.app", root / "Applications"
            self.bundle(source)
            applications.mkdir()
            existing = applications / MODULE.PREVIEW_NAME
            self.bundle(existing)
            (existing / "old-bundle").write_text("preserve")
            MODULE.install(source, applications, BASE)
            exchange.assert_called_once()
            backups = list(applications.glob(".Cognis Preview.previous-*.app"))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "old-bundle").exists())
            self.assertFalse((existing / "old-bundle").exists())

    def test_symlink_or_wrong_source_commit_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "verify_package"):
            root = Path(directory)
            source = root / "source.app"
            self.bundle(source)
            alias = root / "alias.app"
            alias.symlink_to(source)
            with self.assertRaises(ValueError):
                MODULE.install(alias, root / "Applications", BASE)
            with self.assertRaises(ValueError):
                MODULE.install(
                    source, root / "Applications", "d593d10d93939f3232325c9c72cd32d5e351b124"
                )
