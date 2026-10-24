# Video model tools

Cognis can run provider-native video generation, editing and extension as durable jobs.
Deterministic processing remains ordinary Bash/FFmpeg work: there is no video-process tool,
timeline compiler, local transcoder, frame extractor or FFmpeg dependency.

## Setup

1. Configure an active API-key provider using the **Gemini** or **OpenRouter** preset.
   ChatGPT/Codex subscriptions do not provide these API entitlements.
2. Use **Discover models** on your existing native Gemini provider to import the Veo models
   returned by its catalog. Discovery sets their mode to `video` automatically, keeping them
   out of chat defaults. Models not returned by the account's catalog can still be added
   manually with mode `video`; discovery does not grant account access or certify an adapter.
   Set the `video_generation` route in Settings → Routing. Optionally set `video_editing`;
   otherwise it inherits the generation route. Named routes select their first active target;
   video submissions never automatically fail over or retry on another target.
3. Video tools work without a spending-policy setup. Optional limits are **off by default**,
   under Settings → Account → **Advanced: video spending limits**. To opt in, set per-video
   and daily limits and choose each model with a conservative per-render estimate. These
   estimates reserve budget; they are not provider-enforced price caps. Only an authenticated
   UI session can change policy. Concurrency and artifact-size safeguards always apply.
4. Call `video_models` for the selected route/model before generating. Unsupported combinations
   are rejected rather than silently dropping parameters.
5. Start with `dry_run=true`. Real generation requires a separate explicit instruction or
   an applicable user-authorized policy. Normal tool authorization remains in effect;
   optional spending limits are not a separate video enablement switch.

Executor-placed providers require an updated executor with `llm.video`. The configured
executor must reach the controller artifact origin and `/api/v1/videos/transfer`.
Provider calls remain on the configured runtime; there is no controller fallback.
Inputs use short-lived authorized artifact links. Outputs stream via single-result,
job/attempt-scoped HTTP tickets; credentials and movie bytes never appear in tool results.

## Implemented provider contracts

| Provider/model | Operations | Important constraints |
|---|---|---|
| Gemini `veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview` | Generate, extend | Text, first/last frame, reference images, seed, negative prompt and person policy. High resolution/references require eight seconds. Extension uses a retained same-provider/model output, 720p, and returns the combined video. Native audio is inherent, not a toggle. |
| Gemini `gemini-omni-1.1-flash` | Generate, conversational edit/extend | Stored interaction chaining and URI delivery. Duration/audio are prompt-controlled, not guaranteed numeric parameters. Arbitrary uploaded-video editing is not enabled. Confirm availability/region and pricing with the account before use. |
| OpenRouter native videos API | Generate | Capabilities come from `/videos/models`; image roles, audio and seed are exposed only when the catalog advertises their parameters. Source-video edits/extension are not inferred from generation support. |

Generated outputs are preserved as original MP4 bytes with a bounded container-signature check.
No decoding or visual-quality guarantee is implied. Google output URLs must remain on the
native Google API origin and OpenRouter downloads use its authenticated content endpoint.
Unexpected redirects fail closed; a different provider output transport needs a reviewed adapter change.

Bedrock Nova Reel, arbitrary OpenAI-compatible/proxy video transports, webhooks and arbitrary
uploaded-video edits are **not enabled**. They need distinct verified contracts, not a
chat-endpoint compatibility guess. This is the initial native Google/OpenRouter release;
the later providers described in the design remain separate extensions.

## Agent tools

- `video_generate`, `video_edit`, `video_extend`: `request` plus an idempotency key,
  optional dry run and bounded wait. Inputs are persisted artifact IDs. Specify the matching
  `request.operation` for edit/extend. Outputs are immutable new artifacts.
- `video_models`: executable controls for a configured route/model/provider.
- `video_analyze`: native Gemini video input. Enable **Native video input** on an
  account-verified analysis model and choose `video_analysis` (or `attachment_analysis`).
  Uses ordinary inference/accounting and provider placement, not a render job or frame extraction.
  Provider sampling is not frame-exact review.
- `video_job_get`: status, costs, artifact IDs and available recovery actions; optional
  `wait_seconds` up to 60. Waiting does not cancel or resubmit.
- `video_job_list`: current conversation's jobs, with a `before` cursor.
- `video_job_cancel`: current job version plus idempotency key. Unsupported remote
  cancellation is reported honestly: computation/billing may continue; late output is not delivered.
- `video_job_recover`: only the actions offered by the current state: resume, reconcile,
  retry collection or abandon. These never start another paid render.

Use a new idempotency key only for a deliberately new request. Repeating the same key and
same request returns the existing job; different request contents conflict. Cancellation and
recovery keys are also idempotent and use version checks.

## Lifecycle, costs and recovery

The controller persists the executable request privately as an artifact, not session history
in its metadata database. A durable attempt is marked dispatched **before** the provider call.
If the response may have been lost, the job becomes `needs_reconciliation`; it never resubmits.
Late results can populate the original attempt mailbox without overwriting a newer job state.
Database versions arbitrate cancellation/publication. One logical follow-up is admitted through
the existing turn scheduler after terminal completion.

State: queued → preparing → submitting → running → ingesting → succeeded.
Blocked, needs_reconciliation, cancelled, failed and abandoned states remain inspectable.
Success means output artifacts are persisted and authorized, not visually validated.
Use the conversation's job tools for cancellation/recovery and artifact tools for fresh
playback/download links. Routing settings contain model selection, not a job administration panel.
Artifact serving supports bounded streaming and byte ranges.

Failed downloads retry collection, never generation. Access, provider configuration and budget
policy are rechecked before dispatch. Removing grants or changing the provider binding blocks
continuation. Restore the original authority/configuration before resuming.

Known charges settle independently of delivery; unknown charges retain their reservation,
including cancellation or abandonment. When a provider does not report cost, the UI explicitly
shows unknown—not zero. The daily policy is an admission limit, not a hard provider billing cap.
Without a configured estimate, costs remain unknown rather than being represented as free.
Enabling budgets while unknown charges remain unresolved blocks further admission until those
charges are reconciled. `request.max_cost_usd` is optional; supplying it explicitly requires a
known model estimate and enforces that cap even if account limits are off.
Do not reset reservations merely to make an uncertain job disappear.

No `retry_paid` action is exposed until a separately approved duplicate-charge workflow exists.
If a provider has no lookup for a lost submission response, reconciliation cannot invent its handle.
An operator must inspect the provider account and make the new-payment decision explicitly.

## Production workflow

Generate clips → wait for completed artifact IDs → analyze with a native model if available →
edit/extend using supported provider operations → optionally download authorized artifacts and
run Bash/FFmpeg → publish the result through existing artifact tools. No automatic external
send, public sharing or compression takes place.

For a task requiring a finished video, a job ID is not the deliverable: wait for the output
artifact and attach/write the canonical deliverable. Large channel attachments retain the
channel's existing limits; use an authorized link or explicitly compress via Bash.

## Validation and rollout

Offline tests cover paid-submission uncertainty, restart recovery, version races, idempotency,
cost exposure, permission scoping, native provider request/response fixtures, executor transfer
tickets, bounded storage, original-byte publication and range semantics. SQLite migration
graph and affected image/artifact regression tests are part of validation.

No paid render is required to install, build or test the code. Before enabling a model for
production, separately authorize a bounded live test for each advertised operation, its account
pricing, output retention, runtime placement and browser playback. Account entitlement, temporal
quality, exact billing and provider-specific redirects cannot be certified by mocks.
