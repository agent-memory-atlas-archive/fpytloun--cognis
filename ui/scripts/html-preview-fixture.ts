import { mount, unmount } from 'svelte';
import MessageAttachments from '../src/lib/components/MessageAttachments.svelte';
import ResourceReader from '../src/lib/components/library/ResourceReader.svelte';
import HtmlPreviewFixtureEditor from './HtmlPreviewFixtureEditor.svelte';
import ProjectAssetModal from '../src/lib/components/projects/ProjectAssetModal.svelte';
import { auth } from '../src/lib/stores/auth';
import { documentCoordination } from '../src/lib/document-coordination';

if (location.origin !== 'https://html-preview.invalid') throw new Error('Synthetic profile required');
const target = document.getElementById('fixture')!;
let mounted: ReturnType<typeof mount> | undefined;
let email = 'reader@html-preview.invalid';
let releaseBody: (() => void) | undefined;
let heldBody: Promise<void> | undefined;
const html = `<style>h1{color:rgb(1,2,3)}</style><h1>Compiled component</h1>
<script>
parent.postMessage({compiledPreview:true, css:getComputedStyle(document.querySelector('h1')).color,
nativeIdentityAbsent:typeof window.__cognisNative==='undefined'},'*');
setInterval(()=>parent.postMessage({compiledHeartbeat:true},'*'),20);
</script>`;
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } });
// Only the transport is synthetic. Components, authorization API and document leases are real.
globalThis.fetch = async input => {
  const url = new URL(String(input), location.origin);
  if (url.pathname.endsWith('/signed-url')) return json({
    url: `${location.origin}/api/v1/artifacts/view/attachments/att_html/component.html?exp=9999999999&sig=${'a'.repeat(64)}`,
  });
  if (url.pathname.startsWith('/api/v1/artifacts/view/')) {
    await heldBody;
    return new Response(html, { headers: { 'content-type': 'text/html;charset=utf-8' } });
  }
  if (url.pathname.endsWith('/revisions')) return json({ revisions: [] });
  if (url.pathname.endsWith('/me')) return json({ email, role: 'user' });
  if (/\/(?:refresh|login|logout)$/.test(url.pathname)) return json({
    status: 'authenticated', user: { email, role: 'user' }, expires_at: '2030-01-01T00:00:00Z',
  });
  throw new Error('Unexpected fixture endpoint');
};
const state = { report: null as unknown, ticks: 0, allTicks: 0 };
window.addEventListener('message', event => {
  if (event.data?.compiledHeartbeat) state.allTicks++;
  const frame = document.querySelector('iframe');
  if (!frame || event.source !== frame.contentWindow) return;
  if (event.data?.compiledPreview) state.report = { ...event.data, opaque: event.origin === 'null' };
  if (event.data?.compiledHeartbeat) state.ticks++;
});
const close = async () => { if (mounted) await unmount(mounted); mounted = undefined; };
Object.assign(window, { htmlPreviewFixture: {
  state,
  async bootstrap() { await auth.bootstrap(); return auth.getSnapshot().status; },
  async open(surface: string) {
    await close(); state.report = null; state.ticks = 0;
    if (surface === 'chat') {
      mounted = mount(MessageAttachments, { target, props: { attachments: [{
        artifact_id: 'att_html', kind: 'file', mime_type: 'text/html', filename: 'component.html', size_bytes: html.length,
      }] } });
      await new Promise(resolve => setTimeout(resolve, 0));
      (target.querySelector('[aria-label="Preview component.html"]') as HTMLButtonElement).click();
    } else if (surface === 'project') {
      mounted = mount(ProjectAssetModal, { target, props: { artifact: {
        artifact_id: 'att_html', kind: 'file', mime_type: 'text/html', filename: 'component.html', size_bytes: html.length,
      }, onClose: () => { void close(); } } });
    } else if (surface === 'library') {
      mounted = mount(ResourceReader, { target, props: { item: {
        kind: 'artifact', id: 'att_html', title: 'component.html', format: 'text/html', is_readonly: true,
      } as never } });
    } else {
      mounted = mount(HtmlPreviewFixtureEditor, { target, props: {
        text: html, lease: documentCoordination().capture(),
      } });
    }
    return true;
  },
  close: async () => { await close(); return true; },
  toggle() { (mounted as unknown as { toggle(): void }).toggle(); return true; },
  holdBody() { heldBody = new Promise(resolve => { releaseBody = resolve; }); return true; },
  releaseBody() { releaseBody?.(); releaseBody = undefined; heldBody = undefined; return true; },
  async logout() { await auth.logout(); return true; },
  async switchAccount() {
    email = 'second@html-preview.invalid';
    // Refresh deliberately refuses a different identity. Exercise the actual login boundary.
    await auth.login(email, 'synthetic-test-only');
    return true;
  },
} });
