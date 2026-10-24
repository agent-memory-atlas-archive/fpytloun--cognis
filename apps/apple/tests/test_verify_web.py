import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "verify_web", Path(__file__).resolve().parents[1] / "verify_web.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BundleVerificationTests(unittest.TestCase):
    def test_https_incompatible_recorded_bootstrap_is_rejected_even_with_all_modules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "_app").mkdir()
            (root / "_app/env.js").write_text("export const env = {};")
            (root / "index.html").write_text(
                '<script>import("/_app/env.js");import("cognisbundle://app/_app/start.js")</script>'
            )
            with self.assertRaises(ValueError):
                MODULE.verify(root)
            (root / "_app/start.js").write_text('import {value} from "./chunk.js";')
            with self.assertRaises(ValueError):
                MODULE.verify(root)
            (root / "_app/chunk.js").write_text("export const value = 1;")
            with self.assertRaises(ValueError):
                MODULE.verify(root)
            (root / "index.html").write_text(
                "<style>body{color:red}</style><script>__sveltekit_fixture={app:{start(){}}};"
                "__sveltekit_fixture.app.start(document.body);</script>"
            )
            manifest = MODULE.verify(root)
            self.assertEqual(len(manifest), 4)
            (root / "_app/start.js").write_text('import "./missing-side-effect.js";')
            with self.assertRaises(ValueError):
                MODULE.verify(root)

    def test_external_boot_script_or_stylesheet_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inline = "<script>__sveltekit_fixture.app.start(document.body)</script>"
            for external in (
                '<script src="cognisbundle://app/_app/immutable/entry/start.CnXSNxK1.js"></script>',
                '<link rel="modulepreload" href="cognisbundle://app/_app/entry.js">',
                '<link rel="stylesheet" href="cognisbundle://app/_app/app.css">',
            ):
                (root / "index.html").write_text(inline + external)
                with self.assertRaises(ValueError):
                    MODULE.verify(root)
            (root / "index.html").write_text("<html>Remote web export</html>")
            with self.assertRaises(ValueError):
                MODULE.verify(root)


if __name__ == "__main__":
    unittest.main()
