import { COMMON_HIGHLIGHT_LANGUAGES, deferredHighlightSpan, escapeCodeHtml } from './lazy-highlight';

const extensionLanguages: Record<string, string> = {
  bash: 'bash',
  cjs: 'javascript',
  css: 'css',
  html: 'xml',
  js: 'javascript',
  json: 'json',
  jsx: 'javascript',
  md: 'markdown',
  mjs: 'javascript',
  py: 'python',
  rs: 'rust',
  sh: 'bash',
  svelte: 'xml',
  toml: 'ini',
  ts: 'typescript',
  tsx: 'typescript',
  txt: 'plaintext',
  yaml: 'yaml',
  yml: 'yaml',
};

const filenameLanguages: Record<string, string> = {
  dockerfile: 'dockerfile',
  makefile: 'makefile',
};

const filenameFallbackLanguages: Record<string, string> = {
  dockerfile: 'bash',
  makefile: 'bash',
};

function availableLanguage(language: string | null): string | null {
  if (!language) return null;
  return COMMON_HIGHLIGHT_LANGUAGES.has(language) ? language : null;
}

export function pathFromToolArguments(args: Record<string, unknown> | null | undefined): string | null {
  if (!args) return null;
  for (const key of ['file_path', 'filePath', 'path']) {
    const value = args[key];
    if (typeof value === 'string' && value.trim().length > 0) return value;
  }
  return null;
}

export function inferLanguageFromPath(path: string | null | undefined): string | null {
  if (!path) return null;
  const filename = path.split(/[\\/]/).pop()?.toLowerCase() ?? '';
  if (!filename) return null;
  const byName = availableLanguage(filenameLanguages[filename]) ?? availableLanguage(filenameFallbackLanguages[filename]);
  if (byName) return byName;
  const ext = filename.includes('.') ? filename.split('.').pop() ?? '' : '';
  return availableLanguage(extensionLanguages[ext] ?? null);
}

/** Escaped output; known languages are highlighted lazily when visible. */
export function highlightToolOutput(text: string, language: string | null | undefined): string {
  const available = availableLanguage(language ?? null);
  if (!available || available === 'plaintext') return escapeCodeHtml(text);
  return deferredHighlightSpan(text, available);
}

export function isReadToolName(toolName: string): boolean {
  const normalized = toolName.toLowerCase().replace(/[:/]+/g, '.');
  const segments = normalized.split(/[._]+/).filter(Boolean);
  const last = segments.at(-1);
  return last === 'read' || (last === 'file' && segments.at(-2) === 'read');
}
