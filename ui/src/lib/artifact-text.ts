import { previewKind } from './attachments/preview';

/** Source/preview policy shared by readers, editing and upload forms. */
export function textFormat(mime: string, filename = ''): 'json' | 'markdown' | 'html' | 'text' {
  const base = mime.split(';')[0].toLowerCase();
  if (base === 'application/json' || base.endsWith('+json') || /\.json$/i.test(filename)) return 'json';
  if (base === 'text/html' || /\.html?$/i.test(filename)) return 'html';
  if (/markdown/.test(base) || /\.(md|markdown)$/i.test(filename)) return 'markdown';
  return 'text';
}
export function textEligible(mime: string, filename = ''): boolean {
  return mime.startsWith('text/') || /(?:json|yaml|javascript|typescript|xml|toml|sql)/.test(mime)
    || /\.(json|ya?ml|md|txt|csv|html?|py|js|ts|xml|toml|sql|sh|css)$/i.test(filename);
}
export function viewEligible(mime: string, filename = ''): boolean {
  if (mime === 'image/svg+xml' || /\.svg$/i.test(filename)) return false;
  return previewKind({ filename, mime_type: mime }) !== null
    || textEligible(mime, filename) || mime.startsWith('image/');
}
export function syntaxError(text: string, mime: string, filename = ''): string {
  if (textFormat(mime, filename) !== 'json') return '';
  try { JSON.parse(text); return ''; }
  catch (error) { return error instanceof Error ? error.message : 'Invalid JSON'; }
}
