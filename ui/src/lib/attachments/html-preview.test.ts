import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DocumentLease } from '$lib/document-coordination';
import { HTML_PREVIEW_MAX_BYTES, INLINE_HTML_POLICY, SIGNED_HTML_POLICY, mountHtmlPreview, resolveHtmlPreviewUrl, signedHtmlUrl } from './html-preview';

const mocks = vi.hoisted(() => ({ capture: vi.fn(), signedUrl: vi.fn() }));
vi.mock('$lib/document-coordination', () => ({ documentCoordination: () => ({ capture: mocks.capture }) }));
vi.mock('$lib/api/client', () => ({ api: { artifacts: { signedUrl: mocks.signedUrl } } }));
vi.mock('$lib/config', () => ({ apiUrl: (path: string) => `https://cognis.test${path}` }));

const url = `https://cognis.test/api/v1/artifacts/view/attachments/att_html/page.html?exp=9999999999&sig=${'a'.repeat(64)}`;
const flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
function owner() {
  const controller = new AbortController();
  const lease: DocumentLease = {
    owner: 'https://cognis.test\nreader@test.invalid', epoch: 'initial', signal: controller.signal,
    assertCurrent() { controller.signal.throwIfAborted(); },
    async validate() { controller.signal.throwIfAborted(); },
  };
  return { controller, lease };
}
function response(content = '<h1>Preview</h1>', headers: Record<string, string> = {}) {
  return new Response(content, { headers: { 'content-type': 'text/html;charset=utf-8', ...headers } });
}

describe('HTML preview trust and resource lifetime', () => {
  let node: HTMLDivElement;
  let dispose: (() => void) | undefined;
  let create: ReturnType<typeof vi.fn>;
  let revoke: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    node = document.createElement('div'); document.body.append(node);
    create = vi.fn(() => 'blob:https://cognis.test/6b3a438a-2580-491f-a51e-d7e0bbdc8fd5');
    revoke = vi.fn(() => { expect(node.querySelector('iframe')).toBeNull(); });
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response()));
    mocks.capture.mockReturnValue(owner().lease);
    mocks.signedUrl.mockResolvedValue({ url });
  });
  afterEach(() => { dispose?.(); dispose = undefined; node.remove(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('resolves through the authorized API and carries the original lease', async () => {
    const source = await resolveHtmlPreviewUrl('att_html');
    expect(source.lease).toBe(mocks.capture.mock.results[0].value);
    expect(mocks.signedUrl).toHaveBeenCalledWith('att_html', 3600, 'view', source.lease.signal);
  });
  it('rejects late signed capabilities after account invalidation', async () => {
    const { controller, lease } = owner(); mocks.capture.mockReturnValue(lease);
    let finish!: (value: { url: string }) => void;
    mocks.signedUrl.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const pending = resolveHtmlPreviewUrl('att_html');
    await flush(); controller.abort(); finish({ url });
    await expect(pending).rejects.toThrow();
  });
  it('uses canonical virtual HTML export bytes instead of the 307 viewer route', async () => {
    const view = url.replace('/view/attachments/att_html/', '/virtual/deliverables/view/dlv_html/');
    const exported = view.replace('/deliverables/view/', '/deliverables/');
    mocks.signedUrl.mockImplementation(async (_id, _ttl, mode) => ({ url: mode === 'view' ? view : exported }));
    // Model the real endpoint contract: views redirect; exports return HTML.
    vi.mocked(fetch).mockImplementation(async input => String(input) === view
      ? new Response(null, { status: 307, headers: { location: '/api/v1/deliverables/dlv_html/view' } })
      : response());
    const source = await resolveHtmlPreviewUrl('dlv_html');
    expect(source.url).toBe(exported);
    dispose = mountHtmlPreview(node, source, source.lease, vi.fn()); await flush();
    expect(node.querySelector('iframe')).not.toBeNull();
    expect(fetch).toHaveBeenCalledWith(exported, expect.objectContaining({ redirect: 'error', credentials: 'omit' }));
    expect(fetch).not.toHaveBeenCalledWith(view, expect.anything());
  });
  it('fences virtual export resolution against account changes', async () => {
    const { controller, lease } = owner(); mocks.capture.mockReturnValue(lease);
    const view = url.replace('/view/attachments/att_html/', '/virtual/deliverables/view/dlv_html/');
    mocks.signedUrl.mockImplementation(async (_id, _ttl, mode) => {
      if (mode === 'view') return { url: view };
      controller.abort();
      return { url: view.replace('/deliverables/view/', '/deliverables/') };
    });
    await expect(resolveHtmlPreviewUrl('dlv_html')).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('does not follow even an unexpected same-origin redirect', async () => {
    const { lease } = owner(); const report = vi.fn();
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 307, headers: { location: '/login' } }));
    dispose = mountHtmlPreview(node, { url, lease }, lease, report); await flush();
    expect(create).not.toHaveBeenCalled();
    expect(report).toHaveBeenLastCalledWith(expect.stringContaining('could not be loaded safely'));
  });
  it.each([
    url.replace('cognis.test', 'foreign.test'), url.replace('cognis.test', 'cognis.test.evil'),
    url.replace('https://', 'https://user@'), url.replace('/view/', '/content/'),
    url.replace('/api/v1/artifacts/', '/login/'), `${url}&exp=1`, `${url}#fragment`,
    url.replace('https://', 'file://'), url.replace('sig=', 'other='),
  ])('rejects untrusted signed URL %s', value => { expect(() => signedHtmlUrl(value)).toThrow(); });

  it('fetches signed bytes without credentials, redirects, referrers or caching', async () => {
    const { lease } = owner();
    dispose = mountHtmlPreview(node, { url, lease }, lease, vi.fn()); await flush();
    expect(fetch).toHaveBeenCalledWith(url, expect.objectContaining({
      credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer', cache: 'no-store',
    }));
    expect(node.querySelector('iframe')).toHaveAttribute('sandbox', 'allow-scripts');
    expect(node.querySelector('iframe')).toHaveAttribute('referrerpolicy', 'no-referrer');
    const blob = create.mock.calls[0][0] as Blob;
    const text = await new Promise<string>(resolve => { const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.readAsText(blob); });
    expect(text).toContain(SIGNED_HTML_POLICY);
  });
  it('uses the distinct inline policy and no fetch', async () => {
    const { lease } = owner();
    dispose = mountHtmlPreview(node, { text: '<script>1</script>', lease }, lease, vi.fn()); await flush();
    expect(fetch).not.toHaveBeenCalled();
    const text = await new Promise<string>(resolve => { const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.readAsText(create.mock.calls[0][0]); });
    expect(text).toContain(INLINE_HTML_POLICY); expect(text).not.toContain('font-src data:');
  });
  it('removes the running context synchronously before revoking on logout', async () => {
    const { controller, lease } = owner();
    dispose = mountHtmlPreview(node, { text: '<script>1</script>', lease }, lease, vi.fn()); await flush();
    expect(node.querySelector('iframe')).not.toBeNull();
    controller.abort();
    expect(node.querySelector('iframe')).toBeNull(); expect(revoke).toHaveBeenCalledOnce();
  });
  it('does not mount a resolved capability whose lease expired while its parent was loading', async () => {
    const { controller, lease } = owner(); controller.abort();
    dispose = mountHtmlPreview(node, { url, lease }, lease, vi.fn()); await flush();
    expect(fetch).not.toHaveBeenCalled(); expect(create).not.toHaveBeenCalled();
  });
  it('aborts on close and ignores a late body even when transport ignores cancellation', async () => {
    const { lease } = owner(); let finish!: (value: Response) => void;
    vi.mocked(fetch).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    dispose = mountHtmlPreview(node, { url, lease }, lease, vi.fn()); await flush();
    const signal = vi.mocked(fetch).mock.calls[0][1]!.signal!;
    dispose(); expect(signal.aborted).toBe(true); finish(response()); await flush();
    expect(create).not.toHaveBeenCalled();
  });
  it.each([
    () => new Response('denied', { status: 403 }),
    () => response('not html', { 'content-type': 'text/plain' }),
    () => response('', { 'content-length': String(HTML_PREVIEW_MAX_BYTES + 1) }),
    () => new Response(new ReadableStream({ start(c) { c.enqueue(new Uint8Array(HTML_PREVIEW_MAX_BYTES + 1)); c.close(); } }), { headers: { 'content-type': 'text/html' } }),
  ])('fails visibly and creates no blob for invalid or excessive responses', async makeResponse => {
    const { lease } = owner(); const report = vi.fn();
    vi.mocked(fetch).mockResolvedValue(makeResponse());
    dispose = mountHtmlPreview(node, { url, lease }, lease, report); await flush();
    expect(create).not.toHaveBeenCalled(); expect(report).toHaveBeenLastCalledWith(expect.stringContaining('could not be loaded safely'));
  });
  it('times out a blocked frame visibly and releases its resource', async () => {
    vi.useFakeTimers(); const { lease } = owner(); const report = vi.fn();
    dispose = mountHtmlPreview(node, { text: 'preview', lease }, lease, report); await flush();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(node.querySelector('iframe')).toBeNull();
    expect(report).toHaveBeenLastCalledWith(expect.stringContaining('timed out'));
  });
});
