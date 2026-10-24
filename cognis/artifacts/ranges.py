"""Single-range media delivery shared by generic artifact routes."""

from __future__ import annotations

import re


def parse_byte_range(header: str | None, size: int) -> tuple[int, int, bool]:
    """Return an inclusive interval, rejecting malformed/unsatisfiable ranges."""
    if header is None:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError("Unsatisfiable byte range")
    first, last = match.groups()
    if not first:
        count = int(last)
        if not count:
            raise ValueError("Unsatisfiable byte range")
        return max(0, size - count), size - 1, True
    start, end = int(first), min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable byte range")
    return start, end, True
