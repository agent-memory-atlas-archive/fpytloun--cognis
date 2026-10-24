# Dashboard window geometry acceptance

This compiled fixture mounts actual `CompactConversationChat` components with
120 synthetic markdown messages per chat. All API and WebSocket traffic is mocked.
It exercises the real manager and retained-layout persistence consumers without
connecting to a backend.

## Two separate evidence boundaries

- Default: stable explicit timeline scopes. This is **geometry-isolation evidence
  only**, not acceptance of production chat acquisition or scroll preservation.
- `DRAG_ORIGINAL_SCOPE=1`: original prop path
  `<CompactConversationChat conversationId={windowState.entityId} embedded />`.
  The same test retains its scroll assertion; a failure must not be skipped or
  treated as accepted geometry-only preservation.

After building, use:

```sh
./node_modules/.bin/playwright test --config playwright.window-drag.config.ts --workers=1
DRAG_ORIGINAL_SCOPE=1 ./node_modules/.bin/playwright test --config playwright.window-drag.config.ts --workers=1 -g '1 mounted'
```

Use `DRAG_BASELINE=1` only with an actual baseline compiled bundle, never with
the fixed source. It checks the original event-rate publication/write counts.
Preserve result directories before reruns: Playwright clears its output directory.

## Original failing reproduction

1. Mount one chat using the original prop path and wait for all 120 messages.
2. Enter a draft, select characters 2–7, focus its composer, and set the timeline
   viewport to its midpoint.
3. Press the window drag header, then perform 24 pointer moves.
4. Check viewport identity, content extent, scroll position, draft and selection.

Observed on both the untouched baseline bundle and initial geometry fix:
at pointerdown the same connected viewport changed from content height 54,966 px
and scrollTop 27,138 px to content height 639 px and scrollTop 0.
The baseline eventually refilled and jumped to scrollTop 54,276.
The geometry fix produced one final publication and two writes but failed scroll
preservation. These observations are not waived by stable-scope success.

Source leads, **not a proven root cause**:
`CompactConversationChat.svelte:144` derives a scope object;
`ScopedChatV2Timeline.svelte:552–573` acquires its controller in a reactive effect
and resets loading and scroll-follow state. The sync owner must determine which
tracked dependency/identity causes reacquisition on manager publication and own
any canonical correction. No chat/controller production changes belong here.

## Recorded stage evidence

- `.window-drag-baseline-results/`: clean original compiled baseline, 1/3/5 chats,
  zero browser errors; 24 publications and 48 writes per 24-move gesture.
- `.window-drag-provisional-results/`: earlier failed mock run, not clean evidence.
- `.window-drag-geometry-results/`: stable-scope geometry-only pass, 1/3/5 chats and
  five-chat streaming; zero motion publications/writes and one final publication,
  two writes. Draft/selection/focus/scroll and connected panel/composer identities
  held in this isolation fixture.

The failed original-path runs and commands are also retained in the conversation
tool evidence. Original compiled baseline and first fixed bundles are retained
in `.window-drag-baseline-build/` and `.window-drag-fixed-build/`.
Neither Chromium traces nor these structural counts prove native WebKit speedup.

## Next initialization diagnostic (requires an allocated slot)

No timeout, readiness expectation, preservation assertion, or retry policy is
changed. Build-time probes are opt-in and confined to this fixture configuration;
canonical scope/acquisition source files on disk are not edited. Probe anchors
fail closed if the canonical source changes. The probes record view acquisition
effect/scope identity, canonical acquire/controller identity, controller
create/retain/release/invalidate/load/ready and view detach.

```sh
DRAG_DIAGNOSTIC=1 ./node_modules/.bin/vite build --config vite.window-drag.config.ts
DRAG_DIAGNOSTIC=1 ./node_modules/.bin/playwright test --config playwright.window-drag.config.ts --workers=1 -g '^3 mounted synthetic chats: durable drag fanout$'
```

The diagnostic writes `.window-drag-diagnostic-results/`, not any historical
measurement directory. Playwright starts tracing before navigation and retains
the trace on failure. An after-test JSON attachment is saved even when navigation
or initial readiness fails before pointerdown. Request metadata records only
fixture path/method, counts, status and timing; no headers, query strings, request
bodies, or user data. Browser lifecycle and runner event lists are each capped at
200 entries with dropped-event counts. Scope keys are synthetic; no account owner
identity is logged. External HTTP traffic is blocked, service workers are disabled,
and API/WebSocket traffic remains synthetic. Trace size is bounded by the existing
single-case 60-second test budget and finite local fixture, not a new soak workload.

This diagnostic's Playwright tracing/probes add overhead. Do not compare its
timings with performance traces or infer a resource cause from the previous failed
run. After the actual cause is established, explicitly rebuild without
`DRAG_DIAGNOSTIC` and run baseline/fixed measurements in a separately allocated
slot; never use a diagnostic bundle as clean performance evidence.

## Combined static-five follow-up (prepared, not executed)

The original-scope combined run passed one/three chats and five-chat streaming,
but static five failed message-119 readiness (expected 5, observed 3 in 5 seconds).
The later error snapshot had four completed timelines and one loading timeline.
It has no request/controller timings and cannot distinguish hydration, transport,
projection scheduling, rendering, or acquisition churn. Streaming success does
not establish that the static failure is harmless.

The mock route fulfils snapshots directly without a programmed queue or delay.
Canonical controller flights are per scope/controller, with a resident limit of
20, not a shared five-scope flight. `performLoad` hydrates before snapshot dispatch
and yields before projection. These source facts do not prove the pending stage.
No source correction is proposed yet.

Next allocated single-case diagnostic uses the original scope path and unchanged
120-message workload. JSON is saved even if readiness fails. Counters include
per-chat requested/fulfilled/finished/failed/pending snapshots, per-scope phase and
acquisition/reference counts, and owner-memory-clear counts without owner identity.
Probes bracket hydrate, snapshot and projection. Prior results stay untouched.

```sh
DRAG_DIAGNOSTIC=1 ./node_modules/.bin/vite build --config vite.window-drag.config.ts
DRAG_DIAGNOSTIC=1 DRAG_ORIGINAL_SCOPE=1 ./node_modules/.bin/playwright test --config playwright.window-drag.config.ts --workers=1 -g '5 mounted synthetic chats: durable drag fanout$'
```

Collection confirms one static-five Chromium case, excluding streaming.
Output: `.window-drag-static5-diagnostic-results/`. No blind matrix rerun.

## Viewport/disclosure acceptance (prepared, not executed)

The actual original viewport is compared with the panel's current viewport after
composer focus, pointerdown, moves 12/24 and commit. Existing panel/input, draft,
selection, focus, scroll and publication assertions remain.

`DRAG_EXPANSION=1` appends one schema-checked completed tool row per chat after all
120 original messages. The test clicks rendered group disclosures and the public
ToolCallBlock `aria-controls`/`aria-expanded` button, and checks the same control
remains connected and expanded across those phases. No internal expansion state
is assigned. Streaming order moves after this extra tool row.

This adds one tool-render workload per chat. Historical message-only baselines
remain comparable only with expansion disabled; report expansion results
separately, not as historical red/green. After cause resolution and allocation:

```sh
./node_modules/.bin/vite build --config vite.window-drag.config.ts
DRAG_EXPANSION=1 DRAG_ORIGINAL_SCOPE=1 ./node_modules/.bin/playwright test --config playwright.window-drag.config.ts --workers=1
```

Output: `.window-drag-expansion-results/`. Five-second message-119 readiness,
existing waits and all original assertions remain unchanged. New assertions have
only static/schema/collection validation, not runtime acceptance.
