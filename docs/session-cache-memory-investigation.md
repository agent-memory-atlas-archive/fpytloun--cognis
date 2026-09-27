# Session cache allocation investigation

## Evidence and scope

The September 21 controller incident included repeated `OOMKilled` exits under
a 2 GiB pod limit. A surviving controller reported approximately 1.6 GiB resident
memory with 12 L1 session entries. The affected session's latest Redis checkpoint
was approximately 995 KB, plus 55 KB of metadata. These observations do not
establish that the session history caused the OOM.

The cache codec did unnecessarily duplicate decoded histories and serialize
checkpoints twice. This change removes those allocations, not the full incident
root cause. Production heap/native allocation attribution remains outstanding.

## Change and invariants

`SessionCache` continues to own reconstructable L1 event state and Redis L2
generations. Hydration now constructs events directly from decoded chunks and
metadata without a second whole-history JSON round trip. Checkpoint writes
construct shallow wire dictionaries, encode once, and hash those exact bytes.
Encoding completes synchronously before the first Redis await, preserving the
detached wire snapshot even if L1 events change during I/O.

Redis keys, JSON representation, generation/head CAS, TTLs, chain validation,
legacy v2 reads, and canonical fallback are unchanged. The Redis lock still
serializes writes; existing caller/hydration-task cancellation ownership is
unchanged. No history is truncated, no cache invalidation policy is changed, and
no persistent data is deleted.

## Reproduction

The benchmark uses synthetic Unicode tool results and an in-memory Redis fake.
It neither accesses production content nor connects to external services.

```sh
git show v0.16.0:cognis/core/session_cache.py \
  > /tmp/cognis-session-cache-baseline.py
PYTHONPATH=. uv run python scripts/benchmark_session_cache_memory.py \
  /tmp/cognis-session-cache-baseline.py
PYTHONPATH=. uv run python scripts/benchmark_session_cache_memory.py
```

Measured with identical 9,181,679-byte serialized values:

| Operation | Before peak Python allocations | After | Reduction |
|---|---:|---:|---:|
| Checkpoint | 27,851,617 bytes | 18,377,075 bytes | 34% |
| Hydration | 37,623,307 bytes | 18,669,227 bytes | 50% |

These are incremental `tracemalloc` peaks, not a prediction of total pod RSS.
Retained state is essentially unchanged. Exact timing and RSS depend on the
runtime, allocator, and workload.

## Remaining investigation

1. Reproduce a representative full turn offline, instrumenting hydration,
   projection, image preparation, native tokenization, and provider serialization.
   Compare first-run, concurrent-turn, and repeated-turn allocation profiles.
2. Distinguish live Python objects, native allocations, and allocator-retained
   pages before prescribing an eviction policy or a higher memory limit.
3. Consider byte-accounted L1 eviction and bounded hydration concurrency.
   Preserve active-entry locks and canonical recovery; reject or defer oversized
   hydration rather than silently dropping history.
4. Bound compaction formatting before materializing the whole input.
5. Do not replace detached snapshots with shallow copies without an immutable
   event ownership contract.

No deployment or user-facing configuration changes are required by this patch.
