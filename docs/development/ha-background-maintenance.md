# HA background maintenance

## Best-effort auto-remember

Auto-remember is event-driven. Startup resumes already-enqueued work, including
expired processing leases; it does not scan historical Intaris sessions, replay
old admission markers, or rebuild work from terminal evidence ledgers.

Transient provider failures retain bounded queue retries. Ordinary provider 4xx
responses other than 408 and 429 settle as failed immediately. Identity and
trusted-evidence validation remain strict. Missing historical work is acceptable:
do not reset failed rows or invent replacement identities to force delivery.
Capacity-limited work is best effort; a later explicit producer handoff may
retry admission, but no background history sweep fills gaps.

## Storage maintenance

Artifact and tool-output jobs hold separate renewable `DatabaseLeaseStore`
leases across their periodic passes. The database clock and fencing token
govern ownership. Renewal failure cancels the active pass. Tool-output worker
threads check cancellation before subsequent deletes; an in-flight storage
request cannot be fenced by a database lease.

Artifact cleanup commits the existing `deleted` status before storage I/O.
Attachment updates cannot revive that status. Chat transports associate
attachments before turn submission and reject an association that lost the
cleanup race. Storage failure leaves a tombstone for the next bounded pass.
No database transaction spans storage I/O.

TTS cache lookup still uses `(message, voice, model)`, but each newly synthesized
physical artifact has a fresh ID. Cleanup of an old generation therefore cannot
erase a replacement generation. Cache references are removed conditionally by
artifact ID after successful deletion. Unreferenced TTS generations expire under
the same retention policy.

During deployment, drain old controllers before enabling the new artifact
cleanup behavior: old code can still revive deleted records and write to
deterministic TTS object IDs. Retain the normal rollback window before deleting
old derived Work data.

S3 tool-output maintenance uses one inventory for both TTL and size-cap passes.
Failures are reported, successful partial deletion is accounted for, and output
and anchor objects remain paired.

## Explicit retired Work cleanup

No new periodic cleanup job is installed. From the repository environment:

```sh
uv run python -m scripts.cleanup_work_projections --version work-v7
uv run python -m scripts.cleanup_work_projections --version work-v7 \
  --apply --confirm-inactive --batch-size 100
```

The default is read-only. The write form requires explicit confirmation that no
running or rollback controller needs the selected versions. Each invocation
deletes at most the selected batch size per derived table; repeat deliberately
after inspecting the output. The current version is protected. Work record files
are deleted before their parent records to avoid unbounded cascades. Canonical
Intaris events, sessions, conversations, and unrelated versions are untouched.

## Deferred optimizations

Redis raw-page caching remains disabled; shared snapshot/watermark caching is
unchanged. The generic cache still contains its separately tested optional Redis
value capability; this change does not re-enable it or conflate it with HA signal
health. Relay throttling requires workload-level CPU, frame-rate, byte-rate and
event-loop measurements rather than cumulative counters.
