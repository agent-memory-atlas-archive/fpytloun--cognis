import gc
import tracemalloc
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from cognis.core.retention_inventory import retention_inventory
from cognis.core.tool_output_store import S3ToolOutputBackend


def test_inventory_pairs_and_stable_order():
    with retention_inventory() as inventory:
        inventory.add("first", text=False, size=3, modified=1)
        inventory.add("first", text=True, size=7, modified=10)
        inventory.add("second", text=True, size=11, modified=10)
        inventory.add("orphan", text=False, size=13, modified=0)
        assert inventory.finish() == 34
        assert [p.key for p in inventory.candidates()] == ["orphan", "first", "second"]
        assert list(inventory.candidates(expired_before=10)) == []
        assert [p.key for p in inventory.candidates(expired_before=11)] == ["first", "second"]
        inventory.skip("first")
        assert [p.key for p in inventory.candidates()] == ["orphan", "second"]


def test_inventory_heap_does_not_retain_all_keys():
    gc.collect()
    tracemalloc.start()
    try:
        with retention_inventory() as inventory:
            for i in range(30000):
                inventory.add(f"key-{i:08}-" + "x" * 200, text=True, size=10, modified=i)
            assert inventory.finish() == 300000
            _, peak = tracemalloc.get_traced_memory()
            # Keys alone exceed 6 MiB if retained; allow ample scratch overhead.
            assert peak < 2 * 1024 * 1024
    finally:
        tracemalloc.stop()


def store_with_pages(pages):
    store = S3ToolOutputBackend.__new__(S3ToolOutputBackend)
    store._bucket = "outputs"
    store._client = Mock()
    store._client.get_paginator.return_value.paginate.return_value = pages
    return store


@pytest.mark.asyncio
async def test_incomplete_inventory_never_deletes(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))

    def pages():
        yield {
            "Contents": [
                {
                    "Key": "tool-outputs/old.txt",
                    "Size": 1,
                    "LastModified": datetime(2000, 1, 1, tzinfo=UTC),
                }
            ]
        }
        raise OSError("listing interrupted")

    store = store_with_pages(pages())
    result = await store.maintain(1, 0)
    assert result.cleanup_failed and result.size_cap_failed
    store._client.delete_object.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_cross_page_pair_orphan_and_text_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    old = datetime(2000, 1, 1, tzinfo=UTC)
    future = datetime(2100, 1, 1, tzinfo=UTC)
    store = store_with_pages(
        [
            {
                "Contents": [
                    {"Key": "tool-outputs/pair.anchors.json", "Size": 10, "LastModified": old}
                ]
            },
            {
                "Contents": [
                    {"Key": "tool-outputs/pair.txt", "Size": 10, "LastModified": future},
                    {"Key": "tool-outputs/orphan.anchors.json", "Size": 10, "LastModified": old},
                ]
            },
        ]
    )
    result = await store.maintain(1, 20)
    assert result.expired_deleted == 0 and result.size_cap_deleted == 1
    assert [c.kwargs["Key"] for c in store._client.delete_object.call_args_list] == [
        "tool-outputs/orphan.txt",
        "tool-outputs/orphan.anchors.json",
    ]
    assert list(tmp_path.iterdir()) == []
