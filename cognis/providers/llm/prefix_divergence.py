"""Content-free detection of provider prompt-prefix rewrites.

Provider prompt caches only reuse an unchanged request prefix. In an agent
loop every request should extend the previous request of the same session.
This module remembers per-item fingerprints of the last provider-facing
payload per session and reports the first item that was rewritten, so cache
misses caused by Cognis can be attributed without logging prompt content.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from prometheus_client import Counter

from cognis import json_codec as json

logger = logging.getLogger(__name__)

PROMPT_PREFIX_DIVERGENCE_TOTAL = Counter(
    "cognis_llm_prompt_prefix_divergence_total",
    "Provider requests whose payload rewrote the previous request prefix of the same session.",
    ["provider_id", "channel", "item_kind"],
)
PROMPT_PREFIX_CHECKS_TOTAL = Counter(
    "cognis_llm_prompt_prefix_checks_total",
    "Provider requests compared against the previous request of the same session.",
    ["provider_id", "channel", "outcome"],
)

# Each snapshot keeps references to the last payload items of one session, so
# keep the bound small: only recently active sessions are useful to compare.
_MAX_TRACKED = 128
_MAX_PATH_DEPTH = 8


@dataclass(frozen=True, slots=True)
class _Snapshot:
    hashes: tuple[str, ...]
    items: tuple[Any, ...]
    sizes: tuple[int, ...]


def _stable_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8", errors="replace")


def _digest(value: Any) -> tuple[str, int]:
    try:
        payload = _stable_bytes(value)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()[:16], len(payload)


# Field names that are protocol structure, not content. Any other dictionary key
# (for example tool-call argument names inside native envelopes) can carry user
# content and is reported only as ``<key>``.
_STRUCTURAL_KEYS = frozenset(
    {
        "role",
        "type",
        "content",
        "text",
        "name",
        "id",
        "call_id",
        "tool_call_id",
        "tool_calls",
        "function",
        "arguments",
        "output",
        "summary",
        "encrypted_content",
        "reasoning_content",
        "thinking",
        "signature",
        "cache_control",
        "ttl",
        "image_url",
        "url",
        "detail",
        "source",
        "media_type",
        "data",
        "file_id",
        "filename",
        "file_data",
        "status",
        "input",
        "annotations",
        "phase",
    }
)
_ROLES = frozenset({"system", "developer", "user", "assistant", "tool", "function"})
_ITEM_TYPES = frozenset(
    {
        "message",
        "function_call",
        "function_call_output",
        "custom_tool_call",
        "custom_tool_call_output",
        "apply_patch_call",
        "apply_patch_call_output",
        "local_shell_call",
        "local_shell_call_output",
        "reasoning",
        "web_search_call",
        "compaction",
        "input_text",
        "output_text",
        "input_image",
        "input_file",
        "text",
        "image",
        "image_url",
        "document",
        "tool_use",
        "tool_result",
        "thinking",
        "redacted_thinking",
    }
)
_CONTROLLER_KEY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def _safe_key(key: Any, depth: int) -> str:
    if isinstance(key, str) and key in _STRUCTURAL_KEYS:
        return key
    # Only top-level message fields are controller-defined markers; nested
    # underscore keys can be arbitrary tool-input keys inside native envelopes.
    if (
        depth == 0
        and isinstance(key, str)
        and key.startswith("_")
        and len(key) <= 48
        and set(key) <= _CONTROLLER_KEY_CHARS
    ):
        return key
    return "<key>"


def item_kind(item: Any) -> str:
    """Return a bounded, content-free label for a provider input item."""

    if not isinstance(item, dict):
        return type(item).__name__
    raw_role = item.get("role")
    role = raw_role if isinstance(raw_role, str) and raw_role in _ROLES else None
    raw_type = item.get("type")
    item_type = raw_type if raw_type in _ITEM_TYPES else ("other" if raw_type is not None else None)
    if role and item_type and item_type != "message":
        return f"{item_type}:{role}"
    if role:
        return role
    if item_type:
        return item_type
    return "dict"


def first_difference_path(before: Any, after: Any, *, _depth: int = 0) -> str:
    """Return a content-free path to the first structural or value difference."""

    if _depth >= _MAX_PATH_DEPTH:
        return "<depth>"
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after), key=str)
        for key in keys:
            label = _safe_key(key, _depth)
            if key not in before:
                return f".{label}<added>"
            if key not in after:
                return f".{label}<removed>"
            if before[key] != after[key]:
                return f".{label}" + first_difference_path(
                    before[key], after[key], _depth=_depth + 1
                )
        return "<equal>"
    if isinstance(before, list) and isinstance(after, list):
        for index, (left, right) in enumerate(zip(before, after, strict=False)):
            if left != right:
                return f"[{index}]" + first_difference_path(left, right, _depth=_depth + 1)
        if len(before) != len(after):
            return f"<len {len(before)}->{len(after)}>"
        return "<equal>"
    if isinstance(before, str) and isinstance(after, str):
        offset = next(
            (i for i, (a, b) in enumerate(zip(before, after, strict=False)) if a != b),
            min(len(before), len(after)),
        )
        return f"<str@{offset} len {len(before)}->{len(after)}>"
    if type(before) is not type(after):
        return f"<type {type(before).__name__}->{type(after).__name__}>"
    return "<value>"


class PromptPrefixTracker:
    """Remember the last provider payload per (session, channel) and report rewrites."""

    def __init__(self, max_tracked: int = _MAX_TRACKED) -> None:
        self._max_tracked = max_tracked
        self._snapshots: OrderedDict[tuple[str, str, str, str, str | None], _Snapshot] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def observe(
        self,
        *,
        session_id: str | None,
        channel: str,
        provider_id: str,
        model: str,
        llm_request_id: str | None,
        head: Any,
        items: list[Any],
    ) -> dict[str, Any] | None:
        """Record ``items`` and return divergence diagnostics when the prefix was rewritten.

        ``head`` covers request parts that precede the item list (instructions,
        tools). It is part of the comparison key together with the model, so
        auxiliary requests that share a session but use another model or tool
        set never become the baseline of the main loop, and head changes (which
        rewrite the whole prefix by construction) are measured elsewhere.
        """

        if not session_id:
            return None
        try:
            return self._observe(
                session_id=session_id,
                channel=channel,
                provider_id=provider_id,
                model=model,
                llm_request_id=llm_request_id,
                head=head,
                items=items,
            )
        except Exception:
            # Diagnostics must never affect generation.
            logger.debug("prompt prefix divergence check failed", exc_info=True)
            return None

    def _observe(
        self,
        *,
        session_id: str,
        channel: str,
        provider_id: str,
        model: str,
        llm_request_id: str | None,
        head: Any,
        items: list[Any],
    ) -> dict[str, Any] | None:
        head_hash = _digest(head)[0] if head is not None else None
        digests = [_digest(item) for item in items]
        snapshot = _Snapshot(
            hashes=tuple(d[0] for d in digests),
            items=tuple(items),
            sizes=tuple(d[1] for d in digests),
        )
        key = (session_id, channel, provider_id, model, head_hash)
        with self._lock:
            previous = self._snapshots.pop(key, None)
            self._snapshots[key] = snapshot
            while len(self._snapshots) > self._max_tracked:
                self._snapshots.popitem(last=False)
        if previous is None:
            PROMPT_PREFIX_CHECKS_TOTAL.labels(provider_id, channel, "first").inc()
            return None
        divergence = next(
            (
                index
                for index, (left, right) in enumerate(
                    zip(previous.hashes, snapshot.hashes, strict=False)
                )
                if left != right
            ),
            None,
        )
        if divergence is None:
            if len(snapshot.hashes) >= len(previous.hashes):
                PROMPT_PREFIX_CHECKS_TOTAL.labels(provider_id, channel, "extended").inc()
                return None
            divergence = len(snapshot.hashes)
        PROMPT_PREFIX_CHECKS_TOTAL.labels(provider_id, channel, "diverged").inc()
        before = previous.items[divergence] if divergence < len(previous.items) else None
        after = snapshot.items[divergence] if divergence < len(snapshot.items) else None
        kind = item_kind(before if before is not None else after)
        PROMPT_PREFIX_DIVERGENCE_TOTAL.labels(provider_id, channel, kind).inc()
        diagnostics: dict[str, Any] = {
            "session_id": session_id,
            "channel": channel,
            "provider_id": provider_id,
            "model": model,
            "llm_request_id": llm_request_id,
            "divergence_index": divergence,
            "previous_item_count": len(previous.hashes),
            "item_count": len(snapshot.hashes),
            "stable_prefix_bytes": sum(snapshot.sizes[:divergence]),
            "previous_total_bytes": sum(previous.sizes),
            "previous_item_kind": item_kind(before) if before is not None else None,
            "item_kind": item_kind(after) if after is not None else None,
            "difference_path": (
                first_difference_path(before, after)
                if before is not None and after is not None
                else None
            ),
            "previous_neighbors": [
                item_kind(previous.items[i])
                for i in range(max(0, divergence - 2), min(len(previous.items), divergence + 3))
            ],
            "neighbors": [
                item_kind(snapshot.items[i])
                for i in range(max(0, divergence - 2), min(len(snapshot.items), divergence + 3))
            ],
        }
        if after is not None and before is not None:
            matches = [
                index
                for index, digest in enumerate(previous.hashes)
                if digest == snapshot.hashes[divergence]
            ]
            diagnostics["item_found_in_previous_at"] = matches[:3]
        logger.info("LLM prompt prefix diverged", extra={"extra_data": diagnostics})
        return diagnostics


PROMPT_PREFIX_TRACKER = PromptPrefixTracker()
