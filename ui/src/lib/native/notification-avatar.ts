import { apiUrl } from '$lib/config';

/** Only the controller image endpoint; no native URL fetch or redirect credentials. */
export async function notificationAvatar(path: string | null | undefined): Promise<string | null> {
  if (!path || !/^\/api\/v1\/images\/[A-Za-z0-9_-]+$/.test(path)) return null;
  try {
    const response = await fetch(apiUrl(path), {
      credentials: 'include', redirect: 'error', signal: AbortSignal.timeout(3000),
    });
    if (!response.ok || !['image/png', 'image/jpeg', 'image/webp'].includes(response.headers.get('Content-Type')?.split(';')[0] ?? '')) return null;
    const reader = response.body?.getReader();
    if (!reader) return null;
    const chunks: Uint8Array<ArrayBuffer>[] = [];
    let length = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 1_048_576) { await reader.cancel(); return null; }
      chunks.push(new Uint8Array(value));
    }
    const image = await createImageBitmap(new Blob(chunks));
    try {
      if (image.width > 4096 || image.height > 4096) return null;
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 64;
      canvas.getContext('2d')?.drawImage(image, 0, 0, 64, 64);
      const png = canvas.toDataURL('image/png').split(',')[1];
      return png.length <= 24000 ? png : null;
    } finally { image.close(); }
  } catch { return null; }
}
