// Executed by the real BundleWebView tests, with production child CSP supplied as an argument.
const child = async function (font, bridgeBody, origin) {
  const out = { heading: document.querySelector('h1').textContent === 'Synthetic preview',
    css: getComputedStyle(document.querySelector('h1')).color === 'rgb(1, 2, 3)',
    script: true, nativeIdentityAbsent: typeof window.__cognisNative === 'undefined' };
  const blocked = fn => { try { fn(); return false; } catch { return true; } };
  out.parentBlocked = blocked(() => parent.document.body);
  out.storageBlocked = blocked(() => localStorage.getItem('synthetic'));
  try {
    out.cookieIsolated = !document.cookie.includes('htmlPreview=parent');
    document.cookie = 'htmlPreview=child; Path=/';
    out.cookieIsolated &&= !document.cookie.includes('htmlPreview=child');
  } catch { out.cookieIsolated = true; }
  try { webkit.messageHandlers.cognis.postMessage(bridgeBody); out.bridgeAttempt = true; }
  catch { out.bridgeAttempt = false; }
  const bytes = new Uint8Array(1644), dv = new DataView(bytes.buffer);
  const str = (offset, s) => [...s].forEach((c, i) => bytes[offset + i] = c.charCodeAt(0));
  str(0, 'RIFF'); dv.setUint32(4, 1636, true); str(8, 'WAVE'); str(12, 'fmt ');
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, 8000, true); dv.setUint32(28, 16000, true); dv.setUint16(32, 2, true);
  dv.setUint16(34, 16, true); str(36, 'data'); dv.setUint32(40, 1600, true);
  const audioBlob = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>';
  const imageBlob = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
  const load = (tag, src) => new Promise(resolve => {
    const element = document.createElement(tag);
    const done = value => { element.remove(); resolve(value); };
    element.onload = () => done(true); element.onloadedmetadata = () => done(true);
    element.onerror = () => done(false);
    element.src = src; if (tag === 'audio') element.preload = 'metadata';
    document.body.append(element);
    setTimeout(() => done('timeout'), 1500);
  });
  [out.dataImage, out.blobImage, out.dataMedia, out.blobMedia] = await Promise.all([
    load('img', 'data:image/svg+xml,' + encodeURIComponent(svg)), load('img', imageBlob),
    load('audio', 'data:audio/wav;base64,' + btoa(String.fromCharCode(...bytes))), load('audio', audioBlob),
  ]);
  try { await new FontFace('PreviewFont', `url(data:font/ttf;base64,${font})`).load(); out.dataFont = true; }
  catch { out.dataFont = false; }
  out.connectBlocked = await fetch(origin + '/probe', { credentials: 'omit' }).then(() => false, () => true);
  out.topBlocked = blocked(() => top.location.href = origin + '/escape-top');
  out.popupBlocked = window.open(origin + '/escape-popup') === null;
  parent.postMessage({ measurement: out }, '*');
  const link = document.createElement('a'); document.body.append(link);
  link.href = origin + '/escape-link'; link.click();
  link.download = 'untrusted.html'; link.click(); link.removeAttribute('download');
  link.target = '_blank'; link.click(); link.target = '_self';
  const input = document.createElement('input'); input.type = 'file'; document.body.append(input); input.click();
  const attack = URL.createObjectURL(new Blob(['<script>parent.postMessage({escaped:true},"*")<\/script>'], { type: 'text/html' }));
  link.href = attack; link.click();
  const nested = document.createElement('iframe'); nested.src = attack; document.body.append(nested);
  // A live script heartbeat proves that removing the frame, rather than revoking alone, stops it.
  setInterval(() => parent.postMessage({ heartbeat: true }, '*'), 20);
  URL.revokeObjectURL(audioBlob); URL.revokeObjectURL(imageBlob);
};
document.cookie = 'htmlPreview=parent; Path=/; SameSite=Strict';
window.previewReport = null; window.previewEscaped = false; window.previewTicks = 0;
const frame = document.createElement('iframe');
frame.sandbox = 'allow-scripts'; frame.referrerPolicy = 'no-referrer';
window.addEventListener('message', event => {
  if (event.data?.escaped) window.previewEscaped = true;
  if (event.source !== frame.contentWindow) return;
  if (event.data?.measurement) window.previewReport = { ...event.data.measurement, opaque: event.origin === 'null' };
  if (event.data?.heartbeat) window.previewTicks++;
});
const html = '<meta http-equiv="Content-Security-Policy" content="' + policy +
  '"><style>h1{color:rgb(1,2,3)}</style><h1>Synthetic preview</h1><script>(' +
  child.toString() + ')(' + JSON.stringify(font) + ',' + JSON.stringify(bridgeBody) + ',' +
  JSON.stringify(origin) + ')<\/script>';
const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
frame.src = url; document.body.append(frame);
window.closePreview = () => { frame.remove(); URL.revokeObjectURL(url); };
return true;
