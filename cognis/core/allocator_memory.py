"""Read-only allocator accounting for explicitly requested resource captures."""

from __future__ import annotations

import ctypes
import os
import sys
from functools import lru_cache
from typing import Any


class _Mallinfo2(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_size_t)
        for name in (
            "arena",
            "ordblks",
            "smblks",
            "hblks",
            "hblkhd",
            "usmblks",
            "fsmblks",
            "uordblks",
            "fordblks",
            "keepcost",
        )
    ]


@lru_cache(maxsize=1)
def _glibc_mallinfo2() -> Any:
    """Resolve the public zero-argument ABI only on a supported libc."""
    try:
        version = os.confstr("CS_GNU_LIBC_VERSION")
    except (AttributeError, OSError, ValueError):
        return None
    if not version or not version.startswith("glibc "):
        return None
    try:
        library = ctypes.CDLL(None)
        function = library.mallinfo2
    except (OSError, AttributeError):
        return None
    function.argtypes = []
    function.restype = _Mallinfo2
    return function


def allocator_memory() -> dict[str, int]:
    """Report counters without collecting, trimming, traversing or tracing.

    Arena allocated bytes include Python allocator pools, native allocations and
    tcache-held blocks. Arena free bytes exclude those blocks. Neither value is
    Python live-object size; these counters complement RSS, not replace it.
    """
    result = {"python_allocated_blocks": sys.getallocatedblocks()}
    function = _glibc_mallinfo2()
    if function is None:
        return result
    info = function()
    result.update(
        allocator_arena_bytes=int(info.arena),
        allocator_arena_allocated_bytes=int(info.uordblks),
        allocator_arena_free_bytes=int(info.fordblks),
        allocator_mmap_bytes=int(info.hblkhd),
        allocator_mmap_regions=int(info.hblks),
        allocator_free_chunks=int(info.ordblks),
        allocator_fastbin_free_bytes=int(info.fsmblks),
        allocator_main_top_releasable_bytes=int(info.keepcost),
    )
    return result
