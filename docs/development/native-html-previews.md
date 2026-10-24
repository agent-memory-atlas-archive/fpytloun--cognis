# Native HTML preview boundary

`HtmlPreview` mounts one sandboxed blob frame. `html-preview.ts` owns bounded
fetching, the frame, its object URL, timeout, and teardown. Removing the frame
precedes object URL revocation: revocation alone does not stop a running script.

Signed access is resolved by the existing artifact API under a
`DocumentCoordination` lease. That same lease travels with the URL through chat,
project, and library loading. A delayed component cannot recapture ownership
under a newer account. Inline source retains its original document lease across
source/preview toggles. Invalidating a lease aborts fetching and removes the frame.

The existing policies stay distinct:

| Capability | Inline source | Signed HTML |
| --- | --- | --- |
| Inline scripts and styles | Allowed | Allowed |
| Data images | Allowed | Allowed |
| HTTPS images | Allowed | Denied |
| Blob images | Denied | Allowed |
| Data fonts; data/blob media | Denied | Allowed |
| Connections and same-origin access | Denied | Denied |

The native application retains its script/connect directives. It permits only
blob frames and adds `data:` to media sources to avoid reducing the signed HTML
policy through CSP inheritance. Native navigation also requires the current
trusted main frame as source, a child target, and a canonical blob URL containing
the exact profile origin and UUID. Artifact-origin navigation cannot open external
applications, popups, downloads, or the native file chooser. Native bridge guards
remain main-frame and generation scoped.

Preview body fetches omit credentials/referrers, disallow redirects, require HTML,
and cap the streamed bytes at 50 MiB (the artifact store default). Larger
configured artifacts remain downloadable; they do not receive an unlimited HTML
preview allocation. Fetch and frame loading time out after 30 seconds.

## Focused validation

```sh
cd ui
npx vitest run --maxWorkers=1 src/lib/attachments/html-preview.test.ts \
  src/lib/components/HtmlPreview.test.ts src/lib/components/TextDocument.test.ts \
  src/lib/components/ArtifactPreviewContent.test.ts \
  src/lib/components/MessageAttachments.test.ts
```

On an isolated Mac checkout, without an installed application or user data:

```sh
COGNIS_HTML_TEST_REPO="$PWD" swift test --package-path apps/apple --jobs 1 \
  --filter 'HTMLPreviewTests|HTMLPreviewPolicyTests'
```

The native test uses the production `BundleWebView`, synthetic profile storage,
and policy strings read from the UI source. It covers rendering, opaque origin,
bridge rejection, child navigation, and script cessation on removal. This is not
the compiled Svelte application gate; that gate and standard check/build/budget
commands remain required before final acceptance.

## Compiled component gate

Dependencies: this checkout's locked `ui/node_modules` (Vite, Svelte and the
existing Vite Svelte plugin), Node, and the Mac checkout's locked Swift packages,
Xcode/WebKit. No additional package, installed application, user account, or
network service is required. The fixture compiles actual chat, library and
inline components and uses the real auth/document coordination owners; only
transport responses and SvelteKit navigation hooks are synthetic.

After the primary bundle slot is allocated:

```sh
cd ui
HTML_FIXTURE="$(mktemp -d /tmp/cognis-html-components.XXXXXX)"
node node_modules/@sveltejs/kit/svelte-kit.js sync
node scripts/build-html-preview-fixture.mjs "$HTML_FIXTURE"
printf '%s\n' "$HTML_FIXTURE"
```

Transfer that directory and the task-owned source/test revision to an isolated
Mac checkout. After the Mac slot is allocated, set `HTML_FIXTURE` to its copied
absolute directory and run from the Mac checkout:

```sh
COGNIS_HTML_COMPONENT_FIXTURE="$HTML_FIXTURE" \
  swift test --package-path apps/apple --jobs 1 \
  --filter HTMLPreviewTests.testCompiledComponents
```

The XCTest starts the production bundle host at `https://html-preview.invalid`
with a unique test storage namespace. There is no server startup command:
the fixture supplies synthetic fetch responses and rejects unexpected endpoints.
Required output is `HTML_COMPONENT_PASS` for chat, library, inline and project,
plus `HTML_COMPONENT_LOGOUT_PASS`, with zero failures or skips. The gate checks
source toggles, stale pending project-body replacement, account replacement,
logout and heartbeat cessation after removal. An account switch uses the real
login boundary; session refresh intentionally rejects a different identity.

The native policy test also observes native action sinks and rejected child
navigation callbacks. The injected external opener replaces only the OS action,
after all production guards; a trusted-main link is the positive control.
Download callbacks are observed and cancelled, and the file panel entry is
observed before constructing a panel. The child attempts file selection, but
WebKit may reject a synthetic non-user-gesture click before calling its delegate.
