# Attachment persistence validation

## Ownership

`IndexedDbChatV2Outbox` detaches the complete persisted metadata graph for both
put and update, preserving transaction IDs, message IDs, optional attachment
metadata and admission receipts. `scopedTransaction.guard` owns callback
exceptions: abort explicitly and return the original cause.

`AttachmentBlobStore` owns bytes. `AttachmentUploadManager.prepare` establishes
that bytes or an authenticated upload/server-artifact receipt have committed.
Existing library attachments do not require local bytes: an authenticated
signed-URL response establishes availability, and only the artifact reference
(not the returned signed URL) is saved in the account-scoped store.

`ComposerSubmission` owns preparation and consumption for full and compact chat.
A preparation failure does not clear input or create an admissible outbox row.
The component may consume only the submitted revision in the original view and
account lease. Existing upload/admission locks, receipts and identities remain
unchanged.

## Fast checks

From `ui`:

```sh
npx vitest run src/lib/chat-v2/outbox-clone.test.ts src/lib/chat-v2/attachment-uploads.test.ts src/lib/chat-v2/composer-submission.test.ts src/lib/components/chat-v2/CompactConversationChat.submission.test.ts --maxWorkers=1
```

The clone test uses actual compiled Svelte state and the runtime structured-clone
algorithm through fake-indexeddb. It is not evidence of Safari/WKWebView behavior.
The original unguarded request callback reproduces a transaction abort when
reactive attachment metadata is passed to `put`.

## Compiled browser / native diagnostic

The separate `e2e/fixtures/attachment-idb` app has no production route, API
transport, credentials, or user images. It creates two-pixel PNG/JPEG images with
canvas and uses uniquely named synthetic databases. It checks:

- The original unguarded callback with reactive metadata (negative control).
- Fixed outbox put/update with the same reactive metadata.
- File and Blob round trips through the production byte-storage owner.
- Reopened storage and revoked-lease rejection.

After the browser resource slot is allocated:

```sh
cd ui
npx playwright test --config playwright.attachment-idb.config.ts --project chromium
npx playwright test --config playwright.attachment-idb.config.ts --project webkit
```

The report records the browser user agent, negative-control transaction error,
global callback errors, byte comparisons and fixed-path results. Playwright
WebKit is not the installed application's WKWebView. On an explicitly allocated
Mac slot, load the built isolated fixture in a separately authorized WKWebView
harness and record OS/WebKit/app source versions. Never point this diagnostic
at the user's app profile or import real images. Do not change application
installation, data, services or permissions.

## Remaining integration gates

### Composite draft rollout gate

The local composite v3 draft format does not fence old writer scripts. Activation
requires a quiescent upgrade: all old native windows sharing the website data
store must stop, and all old web/PWA writer documents must close or reload.
The current application lifecycle does not establish this across all clients.
Integrated deployment is therefore blocked pending an explicit rollout
procedure; mixed-version writers are unsupported. Legacy input must be
preserved and requires explicit “Send as new” confirmation, never text matching
against historical outbox entries.

Binding retention depends on the local outbox database. Local database loss or
expiry of the backend's existing idempotency guarantee is not permanent
exactly-once delivery. No new journal, index, cleanup mechanism or server schema
is introduced.

`composer-hydration.ts` is the shared read-only discovery owner for both chat
surfaces. A valid composite restores its complete input, including semantic
mode and input revision. `null` inherits backend settings; explicit `default`,
`plan` and `build` are distinct one-shot overrides. A profile/conversation
setting change must not rewrite an existing input's semantic mode.

Before initializing a composite, discovery inspects both concrete legacy text
keys and the compact attachment list. Multiple legacy sources remain separate,
even with equal text. The recovery selector escapes text and requires the user
to select an input and a mode for a new intent. Legacy records are not deleted.
Malformed legacy attachments fail closed without creating a canonical empty
record. A newer valid composite takes precedence unchanged.

Run UI check, build and standalone build with unchanged budgets. Changes to send
preparation/consumption ordering require the repository Chat v2 E2E, canonical
replay and browser gates. A blocked resource slot is a missing validation gate,
not a passing result. Native-specific claims require actual native evidence.

## Native diagnostic evidence (candidate, not acceptance)

On macOS 27.0.1 (26A434), the compiled fixture ran in a real WKWebView with a
fresh UUID-isolated `WKWebsiteDataStore`. No installed app profile was opened.
The negative control returned `AbortError` with the exact message
`IDBTransaction will abort due to uncaught exception in an event handler`;
the originating callback raised `DataCloneError`.

The fixed production outbox put/update committed reactive metadata. Four
PNG/JPEG File/Blob writes committed and round-tripped byte-for-byte; metadata
and both images survived page reload and database reopening. Production
submission preparation/consumption, injected staging failure retaining input,
stale-view consumption refusal and owner revocation checks returned true.
Repeated puts under the same transaction ID left one row.

This does **not** verify duplicate admission after retained input is sent with
new IDs. Independent review found that compact cleanup failure/close during
preparation can leave committed input available for a second submission; that
finding remains blocking. No installed-app end-to-end or process-restart
durability claim is made.

An initial nonpersistent WK data-store probe could commit metadata but all four
Blob/File writes returned false. Switching the diagnostic to a fresh isolated
persistent namespace allowed all four writes. No byte representation change or
production fallback was introduced.

Native commands (in the isolated Mac worktree's `ui` directory):

```sh
./node_modules/.bin/svelte-kit sync
./node_modules/.bin/vite build --config vite.attachment-idb.config.ts
swiftc e2e/fixtures/attachment-idb/NativeProbe.swift -o /private/tmp/cognis-image-idb-native-probe
python3 -m http.server 4187 --bind 127.0.0.1 --directory e2e/fixtures/attachment-idb/dist
/private/tmp/cognis-image-idb-native-probe http://127.0.0.1:4187
```

The test-owned HTTP server and probe exited after validation. Existing Mac
dependencies were reused; no packages or app updates were installed.
