import { describe, expect, it } from 'vitest';

import { previewKind, previewLanguage } from './preview';

function attachment(filename: string, mimeType: string) {
  return {
    artifact_id: 'att_preview',
    kind: 'file',
    mime_type: mimeType,
    filename,
    size_bytes: 12,
  };
}

describe('attachment previews', () => {
  it('recognizes text from MIME type and filename extension', () => {
    expect(previewKind(attachment('report.txt', 'text/plain'))).toBe('text');
    expect(previewKind(attachment('backup.json', 'application/octet-stream'))).toBe('text');
    expect(previewKind(attachment('query', 'application/sql'))).toBe('text');
    expect(previewKind(attachment('script', 'application/x-sh'))).toBe('text');
    expect(previewKind(attachment('archive.zip', 'application/zip'))).toBeNull();
  });

  it('keeps HTML and video on their specialized preview paths', () => {
    expect(previewKind(attachment('report.html', 'text/html'))).toBe('html');
    expect(previewKind(attachment('clip.mp4', 'video/mp4'))).toBe('video');
  });

  it('classifies rich document preview types before generic text', () => {
    expect(previewKind(attachment('report.markdown', 'application/octet-stream'))).toBe('markdown');
    expect(previewKind(attachment('data.tsv', 'application/octet-stream'))).toBe('csv');
    expect(previewKind(attachment('flow.mmd', 'text/plain'))).toBe('mermaid');
    expect(previewKind(attachment('report.pdf', 'application/octet-stream'))).toBe('pdf');
  });

  it('recognizes added textual extensions and MIME aliases', () => {
    expect(previewKind(attachment('component.jsx', 'application/octet-stream'))).toBe('text');
    expect(previewKind(attachment('captions.srt', 'application/octet-stream'))).toBe('text');
    expect(previewKind(attachment('config', 'application/x-yaml'))).toBe('text');
  });

  it('maps common textual files to highlight.js languages', () => {
    expect(previewLanguage('backup.json', 'application/octet-stream')).toBe('json');
    expect(previewLanguage('config.yml', 'text/plain')).toBe('yaml');
    expect(previewLanguage('query', 'application/sql')).toBe('sql');
    expect(previewLanguage('notes.txt', 'text/plain')).toBeNull();
  });
});
