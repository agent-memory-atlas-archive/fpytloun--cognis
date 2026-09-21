"""Bounded artifact preview classification and payload construction."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Literal

from cognis.api.common import api_exception

PreviewKind = Literal[
    "audio",
    "csv",
    "html",
    "image",
    "markdown",
    "mermaid",
    "pdf",
    "text",
    "video",
]

TEXT_PREVIEW_MAX_BYTES = 512 * 1024
CSV_PREVIEW_MAX_ROWS = 500
CSV_PREVIEW_MAX_COLUMNS = 100
CSV_PREVIEW_MAX_CELL_CHARS = 16 * 1024
MERMAID_PREVIEW_MAX_DIAGRAMS = 20
MERMAID_PREVIEW_MAX_SOURCE_BYTES = 64 * 1024

# The parser's process-wide default is commonly 128 KiB, below our bounded
# preview budget. Raising it once lets valid large fields reach our explicit
# per-cell truncation policy without permitting input beyond TEXT_PREVIEW_MAX_BYTES.
csv.field_size_limit(max(csv.field_size_limit(), TEXT_PREVIEW_MAX_BYTES))

_MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}
_MERMAID_EXTENSIONS = {".mmd", ".mermaid"}
_CSV_EXTENSIONS = {".csv", ".tsv"}
_TEXT_EXTENSIONS = {
    ".bash",
    ".c",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".htm",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".kt",
    ".log",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".scss",
    ".sh",
    ".sql",
    ".srt",
    ".svelte",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vtt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}
_TEXT_MIME_TYPES = {
    "application/javascript",
    "application/json",
    "application/sql",
    "application/toml",
    "application/typescript",
    "application/xml",
    "application/x-ndjson",
    "application/x-sh",
    "application/x-subrip",
    "application/x-yaml",
    "application/yaml",
}
_MARKDOWN_MIME_TYPES = {"text/markdown", "text/x-markdown"}
_MERMAID_MIME_TYPES = {"application/vnd.mermaid", "text/vnd.mermaid"}
_CSV_MIME_TYPES = {"application/csv", "text/csv", "text/tab-separated-values"}


def normalized_media_type(content_type: str | None) -> str:
    """Return a lower-case media type without parameters."""

    return (content_type or "").split(";", 1)[0].strip().lower()


def classify_artifact_preview(filename: str, content_type: str | None) -> PreviewKind | None:
    """Resolve the best safe preview renderer for an artifact."""

    media_type = normalized_media_type(content_type)
    suffix = Path(filename).suffix.lower()
    if media_type in {"text/html", "application/xhtml+xml"} or suffix in {".html", ".htm"}:
        return "html"
    if media_type == "application/pdf" or suffix == ".pdf":
        return "pdf"
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("video/"):
        return "video"
    if media_type.startswith("audio/"):
        return "audio"
    if media_type in _MARKDOWN_MIME_TYPES or suffix in _MARKDOWN_EXTENSIONS:
        return "markdown"
    if media_type in _MERMAID_MIME_TYPES or suffix in _MERMAID_EXTENSIONS:
        return "mermaid"
    if media_type in _CSV_MIME_TYPES or suffix in _CSV_EXTENSIONS:
        return "csv"
    if (
        media_type.startswith("text/")
        or media_type in _TEXT_MIME_TYPES
        or suffix in _TEXT_EXTENSIONS
    ):
        return "text"
    return None


def supports_artifact_view(filename: str, content_type: str | None) -> bool:
    """Return whether signed view mode can safely serve or render the artifact."""

    kind = classify_artifact_preview(filename, content_type)
    if kind != "image":
        return kind is not None
    return normalized_media_type(content_type) in {
        "image/avif",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/x-icon",
    }


def _decode_bounded_text(content: bytes) -> tuple[str, bool]:
    preview_bytes = content[:TEXT_PREVIEW_MAX_BYTES]
    if b"\x00" in preview_bytes:
        raise api_exception(415, "unsupported_media_type", "Artifact cannot be previewed as text")
    try:
        text = preview_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        if len(content) > TEXT_PREVIEW_MAX_BYTES and exc.reason == "unexpected end of data":
            text = preview_bytes[: exc.start].decode("utf-8-sig")
        else:
            raise api_exception(
                415, "unsupported_media_type", "Artifact is not valid UTF-8 text"
            ) from exc
    return text, len(content) > TEXT_PREVIEW_MAX_BYTES


def _csv_payload(text: str, *, filename: str) -> tuple[list[str], list[list[str]], bool]:
    sample = text[: 64 * 1024]
    delimiter = "\t" if Path(filename).suffix.lower() == ".tsv" else None
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows: list[list[str]] = []
    truncated = False
    try:
        for index, raw_row in enumerate(reader):
            if index > CSV_PREVIEW_MAX_ROWS:
                truncated = True
                break
            row = [cell[:CSV_PREVIEW_MAX_CELL_CHARS] for cell in raw_row[:CSV_PREVIEW_MAX_COLUMNS]]
            if len(raw_row) > CSV_PREVIEW_MAX_COLUMNS:
                truncated = True
            if any(len(cell) > CSV_PREVIEW_MAX_CELL_CHARS for cell in raw_row):
                truncated = True
            rows.append(row)
    except csv.Error as exc:
        raise api_exception(415, "invalid_csv", "Artifact is not valid delimited text") from exc
    if not rows:
        return [], [], truncated
    width = max(len(row) for row in rows)
    headers = rows[0] + [f"Column {index + 1}" for index in range(len(rows[0]), width)]
    body = [row + [""] * (width - len(row)) for row in rows[1:]]
    return headers, body, truncated


def artifact_preview_payload(
    *, filename: str, content_type: str, content: bytes
) -> dict[str, object]:
    """Build a bounded JSON preview payload for text-backed artifact kinds."""

    kind = classify_artifact_preview(filename, content_type)
    if kind not in {"csv", "markdown", "mermaid", "text"}:
        raise api_exception(415, "unsupported_media_type", "Artifact cannot be previewed as text")
    text, truncated = _decode_bounded_text(content)
    payload: dict[str, object] = {
        "filename": filename,
        "mime_type": content_type,
        "size_bytes": len(content),
        "content": text,
        "truncated": truncated,
        "preview_kind": kind,
    }
    if kind == "csv":
        headers, rows, table_truncated = _csv_payload(text, filename=filename)
        payload["table"] = {"headers": headers, "rows": rows}
        payload["truncated"] = truncated or table_truncated
    payload["rich_payload"] = artifact_preview_rich_payload(payload)
    return payload


def artifact_preview_rich_payload(payload: dict[str, object]) -> dict[str, object]:
    """Adapt one bounded preview payload to the standalone rich viewer."""

    kind = str(payload["preview_kind"])
    content = str(payload.get("content") or "")
    if kind == "markdown":
        blocks: list[dict[str, object]] = []
        cursor = 0
        rendered_diagrams = 0
        for match in re.finditer(
            r"^```mermaid[^\n]*\n(?P<source>.*?)^```[ \t]*$",
            content,
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        ):
            if match.start() > cursor:
                blocks.append({"type": "markdown", "content": content[cursor : match.start()]})
            source = match.group("source").rstrip()
            if (
                rendered_diagrams < MERMAID_PREVIEW_MAX_DIAGRAMS
                and len(source.encode("utf-8")) <= MERMAID_PREVIEW_MAX_SOURCE_BYTES
            ):
                blocks.append({"type": "mermaid", "source": source})
                rendered_diagrams += 1
            else:
                blocks.append({"type": "code", "language": "mermaid", "content": source})
            cursor = match.end()
        if cursor < len(content):
            blocks.append({"type": "markdown", "content": content[cursor:]})
        if not blocks:
            blocks.append({"type": "markdown", "content": content})
        return {"metadata": {}, "blocks": blocks}
    block: dict[str, object]
    if kind == "mermaid":
        block = (
            {"type": "mermaid", "source": content}
            if len(content.encode("utf-8")) <= MERMAID_PREVIEW_MAX_SOURCE_BYTES
            else {"type": "code", "language": "mermaid", "content": content}
        )
    elif kind == "csv":
        table = payload.get("table")
        table_data = table if isinstance(table, dict) else {}
        headers = table_data.get("headers", [])
        raw_rows = table_data.get("rows", [])
        columns = [
            {
                "key": f"column_{index}",
                "label": re.sub(r"([\\`*_{}\[\]()#+\-.!|>])", r"\\\1", str(label)),
            }
            for index, label in enumerate(headers if isinstance(headers, list) else [])
        ]
        rows = [
            {f"column_{index}": {"type": "code", "value": value} for index, value in enumerate(row)}
            for row in (raw_rows if isinstance(raw_rows, list) else [])
            if isinstance(row, list)
        ]
        block = {
            "type": "table",
            "columns": columns,
            "rows": rows,
        }
    else:
        block = {"type": "code", "content": content, "language": "plaintext"}
    return {"metadata": {}, "blocks": [block]}
