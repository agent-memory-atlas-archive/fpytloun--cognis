"""Shared projection policy for delegate results and fork-hook outcomes.

This formats the result presented to a consumer, not the canonical response.
Callers retain original responses in their existing content store.
"""

from typing import Any

from cognis.core.anchored_output import markdown_heading_anchors

RESULT_MAX_CHARS = 120_000
RESULT_TRUNCATION_TEMPLATE = "\n\n[Output truncated: original length {original_length} chars, stored first {max_chars} chars.]"


def project_result_content(
    content: str,
    anchors: list[dict[str, Any]],
    *,
    max_chars: int = RESULT_MAX_CHARS,
) -> tuple[str, list[dict[str, Any]], bool, int | None]:
    """Use the delegate result contract, preserving anchor line ranges."""
    if len(content) <= max_chars:
        anchors = [*anchors, *markdown_heading_anchors(content, existing_anchors=anchors)]
        return content, anchors, False, None
    original_length = len(content)
    notice = RESULT_TRUNCATION_TEMPLATE.format(
        original_length=original_length,
        max_chars=max_chars,
    )
    truncated = content[: max(0, max_chars - len(notice))] + notice
    retained_lines = truncated.count("\n") + 1
    bounded_anchors = []
    for anchor in anchors:
        start_line = int(anchor.get("start_line") or 0)
        if start_line > retained_lines:
            continue
        bounded = dict(anchor)
        end_line = int(bounded.get("end_line") or retained_lines)
        if end_line > retained_lines:
            bounded["end_line"] = retained_lines
        bounded_anchors.append(bounded)
    bounded_anchors.extend(markdown_heading_anchors(truncated, existing_anchors=bounded_anchors))
    return truncated, bounded_anchors, True, original_length
