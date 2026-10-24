/** Save original attachment bytes without navigating the PWA. */
export function isAppleMobile(): boolean {
  return /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

export async function prepareAttachmentFile(
  url: string,
  filename: string,
  signal: AbortSignal,
): Promise<File> {
  const response = await fetch(url, { signal, credentials: 'omit', referrerPolicy: 'no-referrer' });
  if (!response.ok) throw new Error('The file could not be loaded. Please try again.');
  const blob = await response.blob();
  return new File([blob], filename, { type: blob.type || 'application/octet-stream' });
}

export function canShareFile(file: File): boolean {
  return typeof navigator.share === 'function'
    && typeof navigator.canShare === 'function'
    && navigator.canShare({ files: [file] });
}

export function downloadFile(file: File): void {
  const url = URL.createObjectURL(file);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = file.name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Safari may consume the blob asynchronously after the click.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
