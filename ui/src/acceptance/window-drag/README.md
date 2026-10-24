# Native dashboard gesture acceptance — test only

This is a separate test delta, not a change to the frozen Chromium fixture.
It requires the receiving integration tree's qualified Window/Manager and current
canonical chat/controller implementation. Do not transplant old sync production
files from the acceptance tree.

## Qualified export

After an explicit primary build slot and locked project dependency setup:

```sh
cd ui
node scripts/build-window-drag-native.mjs
```

The builder temporarily copies only this route to
`src/routes/dashboard-drag-acceptance/+page.svelte`, refuses an existing route,
and removes its temporary route in `finally`. It uses the existing full-app
Apple build configuration (`COGNIS_APPLE_BUNDLE=1`, canonical inline graph),
not the Chromium Vite fixture, standalone viewer, or another worker's bundle.
Local locked executables only; no `npx` installation fallback.

`build-apple/WINDOW_DRAG_ACCEPTANCE_ONLY` marks the export as **never install**.
`window-drag-services.js` is a separate document-start test service shim; it
mocks only fetch/WebSocket and observes physical `Storage.setItem` invocations.
The production BundleWebView creates immutable native/main identity itself.
The test must not inject native flags, platform branches, ready callbacks,
workspace state, pointer events, or altered policy.

## Allocated Mac execution (not yet run)

Transfer the newly built complete `build-apple` from the qualified integration
tree into an isolated test root. Compile the new test source with that same
integration source revision. Never borrow HTML/Find exports or mutate an
installed app. After the parent grants the Mac test slot:

```sh
cd apps/apple
COGNIS_WINDOW_DRAG_WEB_ROOT="$PWD/../../ui/build-apple" \
  swift test --filter DashboardWindowDragTests
```

Two cases: one populated chat, and five populated chats with stream progress.
Each has 120 canonical messages and one schema-checked completed tool detail.
The tests attach an actual BundleWebView to a finite retained NSWindow on a
fresh reserved `.invalid` profile. Actual application root native bootstrap,
workspace owner/provider and chat sources run. No production seam is needed.

The fixture route exposes seed/prepare/reset/observe buttons and JSON snapshots
only as test UI. Seed uses public canonical pin commands and binding. Prepare
sets public composer input/selection and nonzero non-bottom scroll positions;
it fails if focus or scroll was not established. Tool disclosure is clicked
with AppKit mouse events. Group disclosure uses existing public buttons.

The driver converts DOM coordinates to native view/window coordinates and
delivers NSEvent down/dragged/up to the actual WK hit-test target, following
CanonicalRailTests. This is native-to-WK input in a test-owned attached window,
not physical desktop/titlebar/focus acceptance.

## Assertions and counters

- After real auth/owner bootstrap, unchanged five-second message-119 readiness
  for every chat; no invented ready signal or extended message budget.
- Real viewport identity, public expanded disclosure, draft, selection, focus
  and scroll survive focus/start, moves 12/24, and final commit.
- Actual DOM rectangle moves during motion and agrees with final manager rect.
- Fifth-chat stream token exists before pointerdown and increases during motion.
- Motion: zero manager publications, zero mirrored dashboard-layout write
  attempts, zero physical workspace `Storage.setItem` calls.
- Completion: one manager publication, one mirrored layout write attempt,
  two physical workspace writes (layout and retained-owner persistence).
- Focus/start deltas are recorded separately before resetting gesture counters.

The layout subscription intentionally mirrors ControlCenter's consumer because
this route does not mount ControlCenter. Its counter is **derived write attempts**,
not physical storage. The shim separately counts actual Storage calls filtered
to fixture layout/retained workspace keys. This proves invocation counts, not
disk durability, frame latency, native smoothness, or OS window dragging.

The XCTest JSON attachment retains prepared/start/motion/final snapshots.
No runtime acceptance exists yet. Primary static TypeScript/schema/Svelte checks
passed; Swift/AppKit compile and execution require the later allocated Mac slot.
Outer-window resizing, independent windows and close-to-tray remain unchanged
and outside this test's geometry scope.
