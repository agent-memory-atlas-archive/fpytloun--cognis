import asyncio
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from cognis.core.tool_output_store import FilesystemToolOutputBackend, S3ToolOutputBackend


def backend():
    store = S3ToolOutputBackend.__new__(S3ToolOutputBackend)
    store._bucket = "outputs"
    store._client = Mock()
    now = datetime.now(UTC)
    objects = []
    for call_id, age in (("expired", 7200), ("old", 100), ("recent", 0)):
        for suffix in (".txt", ".anchors.json"):
            objects.append(
                {
                    "Key": f"tool-outputs/{call_id}{suffix}",
                    "LastModified": now - timedelta(seconds=age),
                    "Size": 10,
                }
            )
    store._client.get_paginator.return_value.paginate.return_value = [{"Contents": objects}]
    return store


@pytest.mark.asyncio
async def test_s3_single_inventory_ttl_then_size_cap():
    store = backend()
    result = await store.maintain(ttl_seconds=3600, max_size_bytes=20)
    assert result.expired_deleted == 1
    assert result.size_cap_deleted == 1
    assert not result.cleanup_failed and not result.size_cap_failed
    store._client.get_paginator.assert_called_once_with("list_objects_v2")
    assert [call.kwargs["Key"] for call in store._client.delete_object.call_args_list] == [
        "tool-outputs/expired.txt",
        "tool-outputs/expired.anchors.json",
        "tool-outputs/old.txt",
        "tool-outputs/old.anchors.json",
    ]


@pytest.mark.asyncio
async def test_s3_pair_failure_is_reported_and_other_pairs_continue():
    store = backend()

    def delete(**kwargs):
        if kwargs["Key"] == "tool-outputs/expired.txt":
            raise OSError("offline")

    store._client.delete_object.side_effect = delete
    result = await store.maintain(ttl_seconds=3600, max_size_bytes=20)
    assert result.cleanup_failed
    assert result.expired_deleted == 0
    assert result.size_cap_deleted == 2


@pytest.mark.asyncio
async def test_anchor_failure_does_not_overcount_deleted_text():
    store = backend()

    def delete(**kwargs):
        if kwargs["Key"] == "tool-outputs/expired.anchors.json":
            raise OSError("anchor deletion failed")

    store._client.delete_object.side_effect = delete
    result = await store.maintain(ttl_seconds=3600, max_size_bytes=30)
    assert result.cleanup_failed and result.size_cap_deleted == 1
    assert not any(
        "recent" in call.kwargs["Key"] for call in store._client.delete_object.call_args_list
    )


@pytest.mark.asyncio
async def test_filesystem_failures_are_reported(tmp_path, monkeypatch):
    from pathlib import Path

    store = FilesystemToolOutputBackend(tmp_path)

    def failed(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "iterdir", failed)
    result = await store.maintain(ttl_seconds=1, max_size_bytes=1)
    assert result.cleanup_failed and result.size_cap_failed


@pytest.mark.asyncio
async def test_cancellation_stops_thread_before_next_delete():
    store = backend()
    started = threading.Event()
    release = threading.Event()
    done = threading.Event()

    def delete(**kwargs):
        started.set()
        release.wait(2)
        done.set()

    store._client.delete_object.side_effect = delete
    task = asyncio.create_task(store.maintain(ttl_seconds=3600, max_size_bytes=0))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert await asyncio.to_thread(done.wait, 2)
        await asyncio.sleep(0.05)
        assert store._client.delete_object.call_count == 1
    finally:
        release.set()
