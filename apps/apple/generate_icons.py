# /// script
# requires-python = ">=3.12"
# dependencies = ["cairosvg==2.8.2", "pillow==11.3.0"]
# ///
"""Generate Mac distribution icons using the canonical brand generator."""

import importlib.util
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]


def generate(destination: Path) -> None:
    specification = importlib.util.spec_from_file_location(
        "cognis_brand", ROOT / "scripts/generate_brand_assets.py"
    )
    assert specification is not None and specification.loader is not None
    brand = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(brand)
    iconset = destination / "Cognis.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    source = brand.square(brand.color_mark(), opaque=True)
    for points in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            size = points * scale
            image = Image.open(io.BytesIO(brand.raster(source, size))).convert("RGBA")
            mask = Image.new("L", (size, size))
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, size - 1, size - 1), radius=size * 0.22, fill=255
            )
            image.putalpha(mask)
            suffix = "@2x" if scale == 2 else ""
            image.save(iconset / f"icon_{points}x{points}{suffix}.png")
    for scale in (1, 2):
        suffix = "@2x" if scale == 2 else ""
        (destination / f"CognisMenuTemplate{suffix}.png").write_bytes(
            brand.raster(brand.MASTER.read_bytes(), 18 * scale)
        )
    (destination / "CognisMenuTemplate.svg").write_bytes(brand.MASTER.read_bytes())


if __name__ == "__main__":
    generate(Path(sys.argv[1]))
