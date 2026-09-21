import type { AttachmentRef } from '$lib/types/api';

const TEXT_EXTENSIONS = new Set([
  'bash', 'c', 'conf', 'cpp', 'cs', 'css', 'go', 'h', 'hpp', 'htm', 'ini', 'java',
  'js', 'json', 'jsonl', 'jsx', 'kt', 'log', 'php', 'py', 'rb', 'rs', 'rst',
  'scss', 'sh', 'sql', 'srt', 'svelte', 'toml', 'ts', 'tsx', 'txt', 'vtt',
  'vue', 'xml', 'yaml', 'yml',
]);
const MARKDOWN_EXTENSIONS = new Set(['md', 'markdown', 'mdown']);
const TABLE_EXTENSIONS = new Set(['csv', 'tsv']);
const MERMAID_EXTENSIONS = new Set(['mmd', 'mermaid']);

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  bash: 'bash', c: 'c', cpp: 'cpp', cs: 'csharp', css: 'css', go: 'go', h: 'c',
  hpp: 'cpp', htm: 'xml', html: 'xml', java: 'java', js: 'javascript',
  json: 'json', jsonl: 'json', jsx: 'javascript', kt: 'kotlin', md: 'markdown',
  php: 'php', py: 'python', rb: 'ruby', rs: 'rust', scss: 'scss', sh: 'bash',
  sql: 'sql', svelte: 'xml', toml: 'ini', ts: 'typescript', tsx: 'typescript',
  vue: 'xml', xml: 'xml', yaml: 'yaml', yml: 'yaml',
};

function extension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? '';
}

export type AttachmentPreviewKind = 'csv' | 'html' | 'markdown' | 'mermaid' | 'pdf' | 'text' | 'video';

export function previewKind(attachment: AttachmentRef): AttachmentPreviewKind | null {
  const mimeType = attachment.mime_type?.split(';', 1)[0]?.trim().toLowerCase() ?? '';
  const ext = extension(attachment.filename);
  if (['text/html', 'application/xhtml+xml'].includes(mimeType) || ['html', 'htm'].includes(ext)) return 'html';
  if (mimeType === 'application/pdf' || ext === 'pdf') return 'pdf';
  if (mimeType.startsWith('video/')) return 'video';
  if (['text/markdown', 'text/x-markdown'].includes(mimeType) || MARKDOWN_EXTENSIONS.has(ext)) return 'markdown';
  if (['text/vnd.mermaid', 'application/vnd.mermaid'].includes(mimeType) || MERMAID_EXTENSIONS.has(ext)) return 'mermaid';
  if (['text/csv', 'application/csv', 'text/tab-separated-values'].includes(mimeType) || TABLE_EXTENSIONS.has(ext)) return 'csv';
  if (
    mimeType.startsWith('text/')
    || ['application/json', 'application/xml', 'application/yaml', 'application/x-yaml', 'application/toml', 'application/javascript', 'application/typescript', 'application/sql', 'application/x-ndjson', 'application/x-sh', 'application/x-subrip'].includes(mimeType)
    || TEXT_EXTENSIONS.has(ext)
  ) return 'text';
  return null;
}

export function previewLanguage(filename: string, mimeType: string | null | undefined): string | null {
  const ext = extension(filename);
  if (LANGUAGE_BY_EXTENSION[ext]) return LANGUAGE_BY_EXTENSION[ext];
  const normalized = mimeType?.split(';', 1)[0]?.trim().toLowerCase();
  if (normalized === 'application/json') return 'json';
  if (normalized === 'application/xml') return 'xml';
  if (normalized === 'application/yaml') return 'yaml';
  if (normalized === 'application/sql') return 'sql';
  if (normalized === 'application/x-sh') return 'bash';
  return null;
}
