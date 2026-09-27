# Controller memory profiling

Disabled by default. To trace one StatefulSet replica, configure:

```text
COGNIS_MEMORY_PROFILING=true
COGNIS_MEMORY_PROFILE_POD=cognis-1
COGNIS_MEMORY_PROFILE_INTERVAL_SECONDS=60
```

The pod selector matches its hostname. Other replicas do not start tracing.
Changing environment variables requires a restart. Remove the enabling variable
to disable profiling. This patch does not enable profiling automatically.

Tracing starts at application lifespan entry, before service startup, not before
Python imports. Samples report current RSS, cgroup v2 usage/limit, Python traced
memory and peak, and tracer overhead. Missing
Linux counters are reported as null. No object contents or source lines are
logged. By default no snapshots are captured, aggregated, or retained. When
snapshots are enabled, counters start immediately but snapshot capture waits
until application startup completes so profiling cannot block the startup probe.
Allocation tracing itself still adds CPU and memory overhead.
Profiling is diagnostic overhead, not an OOM
guard. Sampling interval is clamped to 10–3600 seconds and traceback depth to
1–10. Counters-only mode defaults to depth 1. Full snapshot mode defaults to
depth 10 so allocation reports include useful application callers. Setting
`COGNIS_MEMORY_PROFILE_TRACEBACK_DEPTH` overrides either default. Invalid
numbers fall back to 60 seconds/depth 1.

`COGNIS_MEMORY_PROFILE_SNAPSHOTS=true` separately opts into expensive allocation
location summaries and deltas. It retains a compact per-trace aggregate baseline,
not the previous per-allocation snapshot. Do not enable
this on memory-constrained production replicas: a synthetic 200,000-event
experiment added approximately 215 MiB RSS on the first sample alone, with
essentially unchanged traced application allocations. Snapshot creation and
aggregation can also contend for the GIL despite running in a worker thread.
The tracer bookkeeping counter does not include all snapshot-processing costs.
Leave this variable absent for production counters-only monitoring.

Snapshot `top` entries contain `(traceback_frames, bytes, allocation_count)`.
`delta` entries contain `(traceback_frames, byte_delta, allocation_count_delta)`.
They are grouped by the complete captured traceback rather than only the final
allocation line, allowing generic sites such as `json/decoder.py` to be traced
back to the Cognis caller. Frames contain file names and line numbers only; no
object contents or source text are logged.

Sampling runs in a worker thread and stops with application shutdown, including
startup failure. A tracer started externally is not stopped by this service.
Python allocation growth points to retained Python state. RSS growth without
similar traced growth warrants native allocator/tokenizer/image investigation.

## Image decode containment

Direct Codex image normalization now rejects images above 16,777,216 source
pixels before decoding. Rejected images use the existing attachment-degradation
notice; the stored artifact remains untouched. JPEG decoding uses decoder-side
downsampling. A process-wide native-worker lock serializes normalization,
including after cancellation of an async waiter. Concurrent cache misses recheck
the cache under its lock, avoiding duplicate normal decodes. These limits bound
active decoding, not total queued request memory. They do not prove or resolve
the previously observed production OOM cause.
