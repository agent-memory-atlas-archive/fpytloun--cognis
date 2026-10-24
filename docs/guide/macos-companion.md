# macOS Companion

The companion is a small AppKit host for the **bundled Cognis web UI**, not a
second chat client. Requires macOS 15+, Xcode/Swift 6 and Node/npm for builds.
The initial public distribution is an **ad-hoc-signed prerelease**, not an Apple
Developer ID-signed or notarized application. macOS or managed-device policy may
restrict installation. GUI/browser acceptance remains unqualified for the initial
0.18.2 prerelease; skipping it is not a passing result.

Use the [macOS release](https://github.com/fpytloun/cognis/releases/tag/macos-v0.18.2)
for Apple Silicon and Intel disk images. Once the matching release and cask are
published, install with:

```sh
brew install --cask fpytloun/tap/cognis
```

Follow normal user-controlled macOS Privacy & Security / Open Anyway steps only
where the operating system permits them. Do not disable Gatekeeper or remove
quarantine to bypass policy. Ad-hoc builds use the standard app icon for
notifications, not communication avatars. Intel packaging does not establish
physical Intel runtime coverage.

An operator may explicitly waive packaging unit/contract reruns for an ad-hoc
prerelease with `skip_unit_tests: true` when dispatching the release workflow.
The default remains to run them; trusted releases reject this waiver. Record it
in the release qualification notes rather than treating skipped checks as passed.

The companion includes optional existing-executor controls, resident native
notifications and opt-in login/background restore. Build identity and signing
configuration are owned by [`package_info.py`](../../apps/apple/package_info.py)
and [`sign_bundle.py`](../../apps/apple/sign_bundle.py).

## Build and run

From the same source checkout on a Mac:

```sh
bash apps/apple/build.sh
open apps/apple/.build/Cognis.app
swift test --package-path apps/apple --filter CompanionContractTests
```

The script uses the locked npm dependencies, builds the current UI with
`COGNIS_APPLE_BUNDLE=1`, compiles Swift, and copies the export into the generated
`.app`. Build output stays under ignored paths. About / Diagnostics shows native
version/build, web version, source commit, bridge version
and connection state. Different web/server release numbers are not by themselves
an incompatibility.

For a Linux-built web export copied to a task-owned Mac checkout, run
`python3 apps/apple/package_info.py stamp-web` immediately after export.
Transfer the exact source plus `ui/build-apple` and `ui/build-apple-manifest.json`,
then run `COGNIS_WEB_PREBUILT=1 bash apps/apple/build.sh`. Mismatched source/build
inputs or changed assets are rejected. Never restamp an untrusted/stale export.

## Connect and use

Choose an HTTPS **origin**, without a path, credentials, query or fragment.
Loopback HTTP (`localhost`, `127.0.0.1`, `::1`) is allowed for development only.
There is no production server default. Login and onboarding use the normal UI.
“Change Server…” closes the previous native projection and replaces its web
runtime with an isolated persistent WebKit data store. Returning to a server
restores that server's cookies, localStorage and IndexedDB.

Use the existing conversation Pin button. Resolved conversations appear as
agent-initial icons on the desktop. Multiple pins for one agent share an icon
and a conversation menu. Drag the icon rim to move it. Membership is owned by
the existing web pin store; Safari/PWA pins are a separate device-local collection.
Unresolved agent shortcuts do not silently create a conversation.

The menu-bar item starts with **New conversation**, every available non-system,
enabled agent, then **Settings…**. Agent selection opens or focuses the compact
tray chat through the canonical agent-direct resolver, even with no pins or open
windows. It does not pin the conversation. New conversation opens the existing
picker without sending a message. App management, server selection, diagnostics
and Quit remain available below Settings.

Settings is native and client-local (also **Cmd+,**). It groups desktop rail,
display placement, notification previews/macOS controls and startup options.
Half-hide defaults on only when unset; an explicit stored off value is preserved.
The main authenticated web workspace remains the half-hide persistence owner.
There is no server-side Desktop preference page or window-management preference.

The main authenticated web document remains resident. Native surfaces receive
typed, account-fenced projections and use the same chat implementation. Existing
draft/offline persistence is unchanged. Escape dismisses compact chat; explicit
Quit terminates the web runtime and native panels.

Notifications show bounded plain text, agent name and conversation/task title.
Exact reply previews require the controller's `completed_reply` sidebar metadata;
older controllers keep metadata-only alerts, never a fetched later "latest" reply.
Code, links and credential-bearing lines are omitted. Preview display is controlled
locally and remains subject to macOS notification/lock-screen settings.

Ad-hoc builds (including development Preview) use standard notifications with
agent name, conversation/task title, text and existing review/approval actions.
Communication-style avatars are unavailable; diagnostics report
`unavailable-standard-notifications`. No communication intent update or donation
is attempted. The app icon is the supported fallback.

Every ad-hoc signing target, including nested apps and XPC services, receives
explicitly empty entitlements. Final signatures are inspected to reject the
restricted communication entitlement. A strict resource seal is necessary but
does not prove kernel launch acceptance: actual macOS launch is a separate gate.
Future communication capability requires explicit supported Apple provisioning;
it must not be enabled merely by selecting a signing mode.

Simple tool approvals can offer **Approve / Deny** (unlock required); an ordinary
click is **Review**. The resident authenticated client revalidates account, scope,
action, expiry, revision and server permission, then submits through the normal
attention API with a unique submission ID. No approval is queued offline or
replayed after sign-in. Credentials, MFA and questions requiring input remain
Review-only. Success is shown only after server acknowledgment.

## Isolated local acceptance stack

Use a fresh checkout/worktree, not an existing production, alpha or M1 stack.
M2 owns project `cognis-macos-platform-m2` and loopback port **18763**:

```sh
docker compose -p cognis-macos-platform-m2 \
  -f compose.local.yml -f compose.e2e.yml -f apps/apple/compose.platform-acceptance.yml \
  up -d --build cognis mock-llm qdrant
uv run --all-packages --extra dev python apps/apple/tests/platform_smoke.py
cd ui && npx vite-node scripts/check-native-replay.ts
```

The overlay uses an explicitly **test-only** seeded account:
`mac-companion@cognis-e2e.localdev.me` / `mac-companion-local-acceptance`.
Never use this password or overlay for a real server. No executor is started.
The smoke checks real discovery/cookie auth, one owner-wide WebSocket row,
inbox/logout and revoked-cookie rejection. Its separate terminal-state replay
is **injected**, not evidence of an LLM completion or OS notification delivery.

On a separate Mac, establish a loopback-only SSH tunnel to that machine using
your already configured SSH identity:

```sh
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18763:127.0.0.1:18763 YOUR_DEVELOPMENT_HOST
```

Acceptance packages are pinned to `http://127.0.0.1:18763`, rejecting M1's port.
For actual packaged resource/cold-storage WebKit checks:

```sh
COGNIS_TEST_WEB_ROOT="$PWD/ui/build-apple" \
swift test --package-path apps/apple --filter 'testPackaged'
```

This opt-in test clears **only that task loopback profile's** WebKit data at its
start. Do not run it against a profile whose manual draft/pin state you need.
It does not inject auth cookies or local auth state. The retained opt-in
full-send M1 test additionally needs its deterministic agent/executor fixtures;
it is not exercised by the M2 no-executor smoke. Standard contract and injected
platform tests do not require Docker or network.

Cleanup only this project and its task-owned tunnel:

```sh
docker compose -p cognis-macos-platform-m2 \
  -f compose.local.yml -f compose.e2e.yml -f apps/apple/compose.platform-acceptance.yml down
```

Volumes intentionally remain for restart acceptance. Remove them only after
explicitly deciding to discard this task's test data. Never run broad Docker
cleanup or stop other projects.

## Acceptance checklist (record actual results separately)

- Real login → create conversation with deterministic E2E agent → send → streamed
  response → pin → desktop icon → close main → icon → compact send once → answer.
- Open main and verify the same conversation; dismiss/reopen compact with an
  unsent draft; quit/relaunch and verify server, pins, cookies and draft persist.
- Disconnect only the task tunnel; verify cached chat and draft, queue a send,
  reconnect and verify a single admitted message/answer and catch-up.
- Hide, minimize and fully occlude main/compact: no read receipt while hidden or
  unfocused. New unread/attention changes only the appropriate icon/menu summary.
- Repeated icon taps reuse one surface. Multiple conversations for one agent
  remain distinct menu items. Sign out/server change clears old panels.
- Move icons and compact chat across displays; disconnect a monitor and verify
  clamping. Change Spaces, enter another app's fullscreen Space, and check
  `.canJoinAllSpaces` / `.fullScreenAuxiliary` behavior permitted by macOS.
- Type and select a file in compact chat; Escape closes without submitting.
  Verify external HTTPS links open in the default browser, not inside the host.
- Capture main/menu-bar and normal desktop/another-app + compact/icon screenshots.
  Never substitute a browser preview for OS integration evidence.

`apps/apple/scripts/ax.swift` is a developer-only AX inspection helper for this
task app. It uses only already granted Accessibility access and never requests
permission. An unlocked console is needed for meaningful interactive acceptance.
The app itself does not require Accessibility or Screen Recording. If desktop
capture is not already permitted, have the user capture screenshots manually;
do not grant permissions as a workaround. Mark untested OS cases honestly.

## Deferred

iOS/iPadOS, true APNs while quit/asleep, sharing extensions, widgets/Live
Activities, App Intents, global configurable hotkeys, cross-device pins, voice
platform changes remain deferred. Developer ID signing/notarization, physical
login/reboot, locked delivery and full GUI acceptance are not claimed for the
initial ad-hoc prerelease. No unattended permission/login registration is performed.
