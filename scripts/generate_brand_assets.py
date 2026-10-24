# /// script
# requires-python = ">=3.12"
# dependencies = ["cairosvg==2.8.2", "pillow==11.3.0"]
# ///
"""Generate Cognis distribution icons from the transparent vector master.

Run with: uv run scripts/generate_brand_assets.py [--splash-only] [--preview /tmp/brand-preview.png]
"""

from __future__ import annotations

import argparse
import copy
import io
import xml.etree.ElementTree as ET
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "ui" / "static"
MASTER = STATIC / "brand" / "cognis-mark.svg"
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)
SPLASH_SIZES = (
    (2048, 2732),
    (1668, 2388),
    (1536, 2048),
    (1320, 2868),
    (1290, 2796),
    (1206, 2622),
    (1179, 2556),
    (1170, 2532),
    (1125, 2436),
    (828, 1792),
    (750, 1334),
)


def color_mark() -> ET.Element:
    """Apply color without maintaining a second copy of the mark geometry."""
    mark = ET.parse(MASTER).getroot()
    assert len(mark.findall(f"{{{SVG}}}path")) == 4
    assert len(mark.findall(f"{{{SVG}}}circle")) == 1
    assert {child.tag for child in mark} == {
        f"{{{SVG}}}title",
        f"{{{SVG}}}path",
        f"{{{SVG}}}circle",
    }
    mark.set("fill", "url(#cognis-jade)")
    defs = ET.Element(f"{{{SVG}}}defs")
    gradient = ET.SubElement(
        defs,
        f"{{{SVG}}}linearGradient",
        {"id": "cognis-jade", "x1": "0", "y1": "0", "x2": "0", "y2": "1"},
    )
    ET.SubElement(gradient, f"{{{SVG}}}stop", {"stop-color": "#6dd6b5"})
    ET.SubElement(gradient, f"{{{SVG}}}stop", {"offset": "1", "stop-color": "#248a78"})
    mark.insert(1, defs)
    focus = mark.find(f"{{{SVG}}}circle")
    assert focus is not None
    focus.set("fill", "#a7f3d0")
    return mark


def serialize(element: ET.Element) -> bytes:
    return ET.tostring(element, encoding="utf-8") + b"\n"


def square(mark: ET.Element, *, opaque: bool = False) -> bytes:
    canvas = ET.Element(
        f"{{{SVG}}}svg", {"viewBox": "0 0 512 512", "role": "img", "aria-label": "Cognis"}
    )
    if opaque:
        ET.SubElement(
            canvas,
            f"{{{SVG}}}rect",
            {"width": "512", "height": "512", "fill": "#0b1420"},
        )
    inner = copy.deepcopy(mark)
    inner.attrib.update({"x": "48", "y": "48", "width": "416", "height": "416"})
    canvas.append(inner)
    return serialize(canvas)


def raster(source: bytes, size: int) -> bytes:
    return cairosvg.svg2png(bytestring=source, output_width=size, output_height=size)


def preview(destination: Path, color: bytes) -> None:
    sheet = Image.new("RGB", (1000, 590), "#e2e8f0")
    draw = ImageDraw.Draw(sheet)
    mono = MASTER.read_bytes()
    original = Image.open(STATIC / "pwa" / "icon-512.png").convert("RGBA")
    original.thumbnail((230, 230))
    sheet.paste(original, (20, 35), original)
    draw.text((20, 12), "Generated application icon", fill="#111827")
    for x, background, label in [
        (270, "#ffffff", "Transparent color on light"),
        (520, "#0b1420", "Transparent color on dark"),
        (770, "#64748b", "Monochrome template"),
    ]:
        draw.rectangle((x, 35, x + 220, 265), fill=background)
        source = mono if x == 770 else color
        if x == 770:
            source = source.replace(b'fill="currentColor"', b'fill="#ffffff"')
        mark = Image.open(io.BytesIO(raster(source, 200))).convert("RGBA")
        sheet.paste(mark, (x + 10, 50), mark)
        draw.text((x, 12), label, fill="#111827")
    for row, (background, foreground) in enumerate(
        [("#ffffff", "#0f172a"), ("#0b1420", "#f8fafc")]
    ):
        top = 310 + row * 125
        draw.rectangle((15, top, 985, top + 110), fill=background)
        draw.text((30, top + 12), "Menu / inline sizes", fill=foreground)
        for index, size in enumerate([16, 18, 22, 32, 48, 96]):
            source = mono.replace(b'fill="currentColor"', f'fill="{foreground}"'.encode())
            mark = Image.open(io.BytesIO(raster(source, size))).convert("RGBA")
            x = 200 + index * 120
            sheet.paste(mark, (x, top + 5), mark)
            draw.text((x, top + 92), str(size), fill=foreground)
    sheet.save(destination)


def generate_splash_images(color: bytes) -> None:
    """Render OS-selected Classic launch screens without account preferences."""
    for width, height in SPLASH_SIZES:
        size = round(min(width, height) * 0.25)
        mark = Image.open(io.BytesIO(raster(color, size))).convert("RGBA")
        for suffix, background in [("", "#07111a"), ("light-", "#e9eef4")]:
            canvas = Image.new("RGB", (width, height), background)
            canvas.paste(mark, ((width - size) // 2, (height - size) // 2), mark)
            canvas.save(
                STATIC / "pwa" / f"apple-splash-{suffix}{width}-{height}.png",
                optimize=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--splash-only", action="store_true", help="Regenerate launch images only")
    args = parser.parse_args()
    color = serialize(color_mark())
    if args.splash_only:
        generate_splash_images(color)
        return
    (STATIC / "brand" / "cognis-mark-color.svg").write_bytes(color)
    icon = square(color_mark())
    opaque = square(color_mark(), opaque=True)
    (STATIC / "favicon.svg").write_bytes(icon)
    (STATIC / "pwa" / "icon.svg").write_bytes(icon)
    for size in (192, 512):
        (STATIC / "pwa" / f"icon-{size}.png").write_bytes(raster(icon, size))
    (STATIC / "pwa" / "icon-maskable-512.png").write_bytes(raster(opaque, 512))
    (STATIC / "pwa" / "apple-touch-icon.png").write_bytes(raster(opaque, 180))
    badge = ET.parse(MASTER).getroot()
    badge.set("fill", "#ffffff")
    (STATIC / "pwa" / "badge-96.png").write_bytes(raster(square(badge), 96))
    generate_splash_images(color)
    Image.open(io.BytesIO(raster(icon, 256))).save(
        STATIC / "favicon.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    if args.preview:
        preview(args.preview, color)


if __name__ == "__main__":
    main()
