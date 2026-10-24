# /// script
# requires-python = ">=3.12"
# dependencies = ["cairosvg==2.8.2", "pillow==11.3.0", "pytest>=8.0"]
# ///
"""Check launch assets with: uv run scripts/test_brand_launch_assets.py."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "brand_assets", ROOT / "scripts/generate_brand_assets.py"
)
assert spec and spec.loader
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)


@pytest.mark.parametrize("suffix,background", [("", "#07111a"), ("light-", "#e9eef4")])
def test_committed_launch_artwork_geometry_and_classic_colors(suffix: str, background: str) -> None:
    """Check every launch size, exact flat background and unchanged jade composition."""
    html = (ROOT / "ui/src/app.html").read_text()
    color = brand.serialize(brand.color_mark())
    for width, height in brand.SPLASH_SIZES:
        filename = f"apple-splash-{suffix}{width}-{height}.png"
        assert f'href="/pwa/{filename}"' in html
        with Image.open(brand.STATIC / "pwa" / filename) as image:
            assert image.size == (width, height)
            assert image.mode == "RGB"
            expected = Image.new("RGB", image.size, background)
            size = round(min(width, height) * 0.25)
            mark = Image.open(io.BytesIO(brand.raster(color, size))).convert("RGBA")
            expected.paste(mark, ((width - size) // 2, (height - size) // 2), mark)
            assert ImageChops.difference(image, expected).getbbox() is None


def test_splash_only_generator_does_not_write_icons(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    static = tmp_path / "static"
    (static / "pwa").mkdir(parents=True)
    sentinel = static / "pwa/icon-192.png"
    sentinel.write_bytes(b"unchanged icon")
    monkeypatch.setattr(brand, "STATIC", static)
    monkeypatch.setattr(brand, "SPLASH_SIZES", ((192, 256),))
    monkeypatch.setattr(sys, "argv", ["generate_brand_assets.py", "--splash-only"])
    brand.main()
    assert sentinel.read_bytes() == b"unchanged icon"
    assert {path.name for path in (static / "pwa").iterdir()} == {
        "icon-192.png",
        "apple-splash-192-256.png",
        "apple-splash-light-192-256.png",
    }
    for suffix, background in [("", "#07111a"), ("light-", "#e9eef4")]:
        with Image.open(static / "pwa" / f"apple-splash-{suffix}192-256.png") as image:
            assert image.getpixel((0, 0)) == Image.new("RGB", (1, 1), background).getpixel((0, 0))


def test_full_canonical_generator_preserves_distribution_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Generate in isolation and compare every emitted asset with its committed contract."""
    original = brand.STATIC
    static = tmp_path / "static"
    (static / "pwa").mkdir(parents=True)
    (static / "brand").mkdir()
    monkeypatch.setattr(brand, "STATIC", static)
    monkeypatch.setattr(sys, "argv", ["generate_brand_assets.py"])
    brand.main()
    for generated in static.rglob("*"):
        if generated.is_file():
            assert generated.read_bytes() == (original / generated.relative_to(static)).read_bytes()


def test_manifest_keeps_icon_contract_with_classic_static_defaults() -> None:
    manifest = json.loads((brand.STATIC / "manifest.webmanifest").read_text())
    assert manifest["theme_color"] == manifest["background_color"] == "#E9EEF4"
    assert manifest["id"] == manifest["scope"] == "/"
    assert manifest["start_url"] == "/chat"
    assert manifest["display"] == "standalone"
    assert manifest["orientation"] == "any"
    assert manifest["icons"] == [
        {"src": "/pwa/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        {"src": "/pwa/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/pwa/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {
            "src": "/pwa/icon-maskable-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
