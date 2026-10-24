"""Keep third-party runtime assets bundled and network-free in the controller.

Several dependencies lazily download data on first use: tiktoken fetches BPE
ranks from ``openaipublic.blob.core.windows.net``, LiteLLM fetches its model
cost map from GitHub at import time, and ``tokenizers`` pulls Hugging Face
tokenizers. Those downloads run on request paths without timeouts and, for
tiktoken, while holding a process-wide lock. The controller must never depend
on them: every asset ships in the image, and anything that is not bundled
fails fast so callers use their estimate fallback instead.

``configure_offline_runtime`` must run before ``litellm``, ``tiktoken`` or
``huggingface_hub`` are imported, because those libraries read their settings
at import time.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
from typing import Any

from cognis.logging import get_logger

logger = get_logger(__name__)

# Encodings the controller relies on. o200k_base is the generic fallback for
# unknown models, cl100k_base is used by LiteLLM's default encoding and the
# knowledgebase chunker.
REQUIRED_TIKTOKEN_ENCODINGS: tuple[str, ...] = ("o200k_base", "cl100k_base")
_TIKTOKEN_URL_TEMPLATE = "https://openaipublic.blob.core.windows.net/encodings/{name}.tiktoken"

_configured = False


class BundledAssetUnavailable(RuntimeError):
    """A runtime asset is not bundled and downloading it is disabled."""


def tiktoken_cache_key(encoding_name: str) -> str:
    """Return tiktoken's cache file name for an OpenAI public encoding."""

    url = _TIKTOKEN_URL_TEMPLATE.format(name=encoding_name)
    return hashlib.sha1(url.encode()).hexdigest()


def bundled_tiktoken_dir() -> Path | None:
    """Return the tiktoken data directory shipped inside the LiteLLM wheel."""

    spec = importlib.util.find_spec("litellm")
    if spec is None or not spec.submodule_search_locations:
        return None
    for location in spec.submodule_search_locations:
        candidate = Path(location) / "litellm_core_utils" / "tokenizers"
        if candidate.is_dir():
            return candidate
    return None


def configure_offline_runtime() -> None:
    """Point dependencies at bundled assets and disable their downloads.

    Explicit operator overrides in the environment are preserved. Idempotent.
    """

    global _configured
    if _configured:
        return
    # LiteLLM: use the cost map shipped with the pinned package version.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    # huggingface_hub / tokenizers.from_pretrained: never reach the Hub.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    # tiktoken: read BPE ranks from the bundled directory.
    if not os.environ.get("TIKTOKEN_CACHE_DIR"):
        bundled = bundled_tiktoken_dir()
        if bundled is not None:
            os.environ["TIKTOKEN_CACHE_DIR"] = str(bundled)
    cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR")
    if cache_dir:
        # LiteLLM rewrites TIKTOKEN_CACHE_DIR on import unless this is set.
        os.environ.setdefault("CUSTOM_TIKTOKEN_CACHE_DIR", cache_dir)
    _install_tiktoken_network_guard()
    _configured = True


def _install_tiktoken_network_guard() -> None:
    try:
        import tiktoken.load as tiktoken_load
    except ImportError:
        return
    original = tiktoken_load.read_file
    if getattr(original, "_cognis_offline_guard", False):
        return

    def _offline_read_file(blobpath: str) -> bytes:
        if "://" in blobpath:
            raise BundledAssetUnavailable(
                f"tiktoken asset {blobpath} is not bundled in "
                f"{os.environ.get('TIKTOKEN_CACHE_DIR') or '<unset>'}; "
                "runtime downloads are disabled"
            )
        return original(blobpath)

    _offline_read_file._cognis_offline_guard = True  # type: ignore[attr-defined]
    tiktoken_load.read_file = _offline_read_file


def preload_bundled_encodings(*, strict: bool = False) -> dict[str, Any]:
    """Load required tiktoken encodings from bundled files.

    Loading at startup keeps the one-time parse off request paths. When an
    encoding is missing, token counting degrades to a character estimate; with
    ``strict`` the failure is raised (used to validate image builds).
    """

    configure_offline_runtime()
    import tiktoken

    loaded: list[str] = []
    missing: dict[str, str] = {}
    for name in REQUIRED_TIKTOKEN_ENCODINGS:
        try:
            tiktoken.get_encoding(name)
        except Exception as exc:
            missing[name] = f"{type(exc).__name__}: {exc}"
        else:
            loaded.append(name)
    status = {
        "tiktoken_cache_dir": os.environ.get("TIKTOKEN_CACHE_DIR"),
        "loaded": loaded,
        "missing": missing,
    }
    if missing:
        if strict:
            raise BundledAssetUnavailable(f"bundled tiktoken encodings unavailable: {missing}")
        logger.error(
            "offline runtime: bundled tokenizer encodings unavailable; "
            "token counting will use character estimates",
            extra={"extra_data": status},
        )
    else:
        logger.info(
            "offline runtime: bundled tokenizer encodings loaded", extra={"extra_data": status}
        )
    return status
