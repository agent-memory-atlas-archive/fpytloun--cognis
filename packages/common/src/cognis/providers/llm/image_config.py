"""Portable Gemini image sizing for controller and executor completion calls."""

import math
import re

_ASPECT_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
_NATIVE_DIMENSIONS = {
    (1024, 1024): "1:1",
    (848, 1264): "2:3",
    (1264, 848): "3:2",
    (896, 1200): "3:4",
    (1200, 896): "4:3",
    (928, 1152): "4:5",
    (1152, 928): "5:4",
    (768, 1376): "9:16",
    (1376, 768): "16:9",
    (1584, 672): "21:9",
    (1280, 896): "4:3",
    (896, 1280): "3:4",
}


def gemini_image_config(size: str | None, model: str) -> dict[str, str] | None:
    """Map WxH to Gemini's nearest ratio and resolution, not exact pixel output.

    The pinned LiteLLM lacks map_openai_size_to_gemini_image_config. Use the
    same logarithmic ratio distance and area-based resolution thresholds here.
    Invalid/auto sizes leave provider defaults intact. Gemini 2.5 Flash accepts
    aspectRatio but not imageSize.
    """
    match = re.fullmatch(r"([0-9]{1,6})x([0-9]{1,6})", (size or "").strip().lower())
    if match is None:
        return None
    width, height = map(int, match.groups())
    if width <= 0 or height <= 0:
        return None
    ratio = width / height

    def distance(aspect: str) -> float:
        w, h = map(int, aspect.split(":"))
        return abs(math.log((w / h) / ratio))

    # Documented native outputs are rounded, so their intended aspect ratio
    # can differ from the nearest mathematical ratio.
    native_ratio = next(
        (
            aspect
            for (w, h), aspect in _NATIVE_DIMENSIONS.items()
            for scale in (0.5, 1, 2, 4)
            if (width, height) == (w * scale, h * scale)
        ),
        None,
    )
    config = {"aspectRatio": native_ratio or min(_ASPECT_RATIOS, key=distance)}
    if "2.5-flash" not in model.lower():
        side = math.sqrt(width * height)
        config["imageSize"] = "1K" if side < 1536 else "2K" if side < 3072 else "4K"
    return config
