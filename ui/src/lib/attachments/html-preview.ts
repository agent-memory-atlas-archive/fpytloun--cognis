import { apiUrl } from '$lib/config';
import { documentCoordination, type DocumentLease } from '$lib/document-coordination';
import { api } from '$lib/api/client';

export const INLINE_HTML_POLICY = "default-src 'none'; img-src data: https:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'";
export const SIGNED_HTML_POLICY = "default-src 'none'; connect-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; media-src data: blob:";
// Match the artifact store's default maximum; never buffer an unbounded body.
export const HTML_PREVIEW_MAX_BYTES = 50 * 1024 * 1024;
export type SignedHtmlPreview = { url: string; lease: DocumentLease };
export type HtmlPreviewSource = { text: string; lease: DocumentLease } | SignedHtmlPreview;

/** Authorize via the canonical API, fencing the response against account replacement. */
export async function resolveHtmlPreviewUrl(id: string, signal?: AbortSignal): Promise<SignedHtmlPreview> {
  const lease = documentCoordination().capture();
  await lease.validate();
  const combined = signal ? AbortSignal.any([signal, lease.signal]) : lease.signal;
  combined.throwIfAborted();
  const result = await api.artifacts.signedUrl(id, 3600, 'view', combined);
  await lease.validate();
  combined.throwIfAborted();
  let url = signedHtmlUrl(result.url);
  if (new URL(url).pathname.startsWith('/api/v1/artifacts/virtual/deliverables/view/')) {
    // Virtual views are 307 redirects to the canonical viewer, not HTML bytes.
    // Request its existing authorized export rather than following any redirect.
    const exported = await api.artifacts.signedUrl(id, 3600, 'download', combined);
    await lease.validate();
    combined.throwIfAborted();
    const exportUrl = signedHtmlUrl(exported.url);
    const expected = new URL(url).pathname.replace('/virtual/deliverables/view/', '/virtual/deliverables/');
    if (new URL(exportUrl).pathname !== expected) throw new Error('The HTML export URL is not valid.');
    url = exportUrl;
  }
  return { url, lease };
}

export function signedHtmlUrl(value: string): string {
  const base = new URL(apiUrl('/') || '/', window.location.origin);
  const url = new URL(value, base);
  if (!['https:', 'http:'].includes(url.protocol) || url.origin !== base.origin
    || url.username || url.password || url.hash
    || !/^\/api\/v1\/artifacts\/(?:view\/[^/]+\/[^/]+\/.+|virtual\/deliverables\/(?:view\/)?dlv_[a-zA-Z0-9]+\/.+)$/.test(url.pathname)
    || [...url.searchParams.keys()].sort().join(',') !== 'exp,sig'
    || !/^\d+$/.test(url.searchParams.get('exp') ?? '')
    || !/^[a-f0-9]{64}$/.test(url.searchParams.get('sig') ?? '')) {
    throw new Error('The HTML preview URL is not valid.');
  }
  return url.href;
}

async function readHtml(url: string, signal: AbortSignal): Promise<string> {
  const response = await fetch(signedHtmlUrl(url), {
    signal, credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer', cache: 'no-store',
  });
  if (!response.ok) throw new Error('The HTML preview could not be loaded. Reopen it to try again.');
  const type = response.headers.get('content-type') ?? '';
  if (type.split(';')[0].trim().toLowerCase() !== 'text/html') throw new Error('The preview response is not HTML.');
  if (Number(response.headers.get('content-length')) > HTML_PREVIEW_MAX_BYTES) throw new Error('The HTML preview exceeds the 50 MB limit.');
  if (!response.body) throw new Error('The HTML preview is empty.');
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      signal.throwIfAborted();
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > HTML_PREVIEW_MAX_BYTES) throw new Error('The HTML preview exceeds the 50 MB limit.');
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const charset = /charset\s*=\s*["']?([^;"'\s]+)/i.exec(type)?.[1] ?? 'utf-8';
    return new TextDecoder(charset).decode(bytes);
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

/** Teardown removes the browsing context before revocation; revocation alone cannot stop scripts. */
export function mountHtmlPreview(
  container: HTMLElement, source: HtmlPreviewSource, lease: DocumentLease,
  report: (message: string | null) => void,
): () => void {
  const controller = new AbortController();
  let frame: HTMLIFrameElement | undefined;
  let objectUrl: string | undefined;
  let stopped = false;
  const timeout = setTimeout(() => {
    stop();
    report('The HTML preview timed out. Reopen it to try again.');
  }, 30_000);
  const stop = () => {
    stopped = true;
    clearTimeout(timeout);
    controller.abort();
    frame?.remove();
    frame = undefined;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = undefined;
    lease.signal.removeEventListener('abort', invalidated);
  };
  const invalidated = () => { stop(); report('This preview is no longer available. Reopen it after signing in.'); };
  lease.signal.addEventListener('abort', invalidated, { once: true });
  report(null);
  void (async () => {
    try {
      await lease.validate();
      if (stopped) return;
      const text = 'text' in source ? source.text : await readHtml(source.url, controller.signal);
      await lease.validate();
      if (stopped) return;
      if (new TextEncoder().encode(text).byteLength > HTML_PREVIEW_MAX_BYTES) throw new Error('The HTML preview exceeds the 50 MB limit.');
      const policy = 'text' in source ? INLINE_HTML_POLICY : SIGNED_HTML_POLICY;
      objectUrl = URL.createObjectURL(new Blob([
        `<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}">`, text,
      ], { type: 'text/html;charset=utf-8' }));
      frame = document.createElement('iframe');
      frame.title = 'Artifact preview';
      frame.setAttribute('sandbox', 'allow-scripts');
      frame.setAttribute('referrerpolicy', 'no-referrer');
      frame.className = 'h-full min-h-96 w-full border-0 bg-white';
      frame.src = objectUrl;
      frame.onload = () => { if (!stopped) { clearTimeout(timeout); report(''); } };
      frame.onerror = () => { stop(); report('The HTML preview could not be displayed.'); };
      container.replaceChildren(frame);
    } catch {
      if (stopped) return;
      stop();
      report('The HTML preview could not be loaded safely. Reopen it to try again.');
    }
  })();
  return stop;
}
