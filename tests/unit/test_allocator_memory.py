from __future__ import annotations

import ctypes
from unittest.mock import Mock

from cognis.core import allocator_memory as allocator


def test_read_only_accounting_maps_native_fields(monkeypatch):
    values = allocator._Mallinfo2(
        arena=1000,
        uordblks=600,
        fordblks=400,
        hblkhd=200,
        hblks=2,
        ordblks=5,
        fsmblks=30,
        keepcost=80,
    )
    read = Mock(return_value=values)
    monkeypatch.setattr(allocator, "_glibc_mallinfo2", lambda: read)
    monkeypatch.setattr(allocator.sys, "getallocatedblocks", lambda: 123)
    assert allocator.allocator_memory() == {
        "python_allocated_blocks": 123,
        "allocator_arena_bytes": 1000,
        "allocator_arena_allocated_bytes": 600,
        "allocator_arena_free_bytes": 400,
        "allocator_mmap_bytes": 200,
        "allocator_mmap_regions": 2,
        "allocator_free_chunks": 5,
        "allocator_fastbin_free_bytes": 30,
        "allocator_main_top_releasable_bytes": 80,
    }
    read.assert_called_once_with()


def test_unsupported_libc_has_no_native_call(monkeypatch):
    allocator._glibc_mallinfo2.cache_clear()
    monkeypatch.setattr(allocator.os, "confstr", lambda _: None)
    load = Mock()
    monkeypatch.setattr(allocator.ctypes, "CDLL", load)
    assert allocator._glibc_mallinfo2() is None
    load.assert_not_called()
    allocator._glibc_mallinfo2.cache_clear()


def test_missing_symbol_fails_open_without_changing_allocator(monkeypatch):
    allocator._glibc_mallinfo2.cache_clear()
    monkeypatch.setattr(allocator.os, "confstr", lambda _: "glibc 2.31")
    monkeypatch.setattr(allocator.ctypes, "CDLL", lambda _: object())
    assert allocator._glibc_mallinfo2() is None
    allocator._glibc_mallinfo2.cache_clear()


def test_real_native_abi_and_nonnegative_accounting():
    allocator._glibc_mallinfo2.cache_clear()
    result = allocator.allocator_memory()
    assert all(isinstance(value, int) and value >= 0 for value in result.values())
    assert ctypes.sizeof(allocator._Mallinfo2) == 10 * ctypes.sizeof(ctypes.c_size_t)
    if "allocator_arena_bytes" in result:
        assert result["allocator_arena_allocated_bytes"] <= result["allocator_arena_bytes"]
        assert result["allocator_arena_free_bytes"] <= result["allocator_arena_bytes"]
    allocator._glibc_mallinfo2.cache_clear()
