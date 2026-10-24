import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import TextDocument from './TextDocument.svelte';
import { syntaxError, viewEligible } from '$lib/artifact-text';

describe('Shared artifact source surface', () => {
  it.each([
    ['application/octet-stream', 'flow.mmd'],
    ['application/vnd.mermaid', 'flow'],
    ['application/octet-stream', 'data.tsv'],
    ['application/octet-stream', 'report.pdf'],
    ['application/octet-stream', 'report.mdown'],
  ])('offers view links for every supported preview: %s / %s', (mime, filename) => {
    expect(viewEligible(mime, filename)).toBe(true);
  });
  it.each([
    ['text/markdown', 'report.txt'],
    ['text/plain', 'report.md'],
  ])('renders Markdown immediately for %s / %s', (mime, filename) => {
    const text = '# Report\n\n**Ready**\n\n- First item\n\n| Name | Status |\n| --- | --- |\n| Release | Ready |\n\n<script>alert(1)</script><img src=x onerror=alert(1)>';
    const { container } = render(TextDocument, { text, mime, filename });
    expect(screen.getByRole('heading', { name: 'Report' })).toBeVisible();
    expect(container.querySelector('strong')).toHaveTextContent('Ready');
    expect(screen.getByRole('listitem')).toHaveTextContent('First item');
    expect(screen.getByRole('table')).toHaveTextContent('Release');
    expect(container.querySelector('pre')).toHaveClass('hidden');
    expect(container.querySelector('script, [onerror]')).toBeNull();
  });
  it('switches rendered Markdown to exact source for editing and back without replacing the source element', async () => {
    const text = '# Report\n\n**Ready**';
    const view = render(TextDocument, { text, mime: 'text/markdown' });
    const source = screen.getByLabelText('Artifact content');
    await view.rerender({ text, mime: 'text/markdown', editing: true });
    expect(screen.getByRole('textbox')).toBe(source);
    expect(source).not.toHaveClass('hidden');
    expect(source.textContent).toBe(text);
    expect(screen.queryByRole('heading')).toBeNull();
    await view.rerender({ text, mime: 'text/markdown', editing: true, preview: true });
    expect(source).toHaveClass('hidden');
    expect(screen.getByRole('heading', { name: 'Report' })).toBeVisible();
    await view.rerender({ text, mime: 'text/markdown', editing: false, preview: false });
    expect(screen.getByRole('heading', { name: 'Report' })).toBeVisible();
  });
  it('keeps plain text literal in read-only mode', () => {
    render(TextDocument, { text: '# Not a heading', mime: 'text/plain', filename: 'notes.txt' });
    expect(screen.queryByRole('heading')).toBeNull();
    expect(screen.getByText('# Not a heading')).toBeVisible();
  });
  it('pretty prints JSON and escapes source without executable markup', () => {
    const { container } = render(TextDocument, { text: '{"safe":"<img src=x onerror=alert(1)>","ok":true}', mime: 'application/json' });
    expect(container.querySelector('.json-key')).toBeTruthy();
    expect(container.querySelector('code.hljs')?.textContent).toContain('\n  "safe":');
    expect(container.querySelector('img')).toBeNull();
  });
  it('retains the same source element on edit and does not pretty print editable bytes', async () => {
    const source = '{"a":1}';
    const view = render(TextDocument, { text: source, mime: 'application/json' });
    const node = screen.getByLabelText('Artifact content');
    await view.rerender({ text: source, mime: 'application/json', editing: true });
    expect(screen.getByRole('textbox', { name: 'Artifact content' })).toBe(node);
    expect(node.textContent).toBe(source);
    node.innerText = '{"a":2}';
    await fireEvent.input(node);
    expect(node.innerText).toBe('{"a":2}');
    await view.rerender({ text: '{"a":2}', mime: 'application/json', editing: true, preview: true });
    expect(node).toHaveClass('hidden');
    await view.rerender({ text: '{"a":2}', mime: 'application/json', editing: true, preview: false });
    expect(screen.getByRole('textbox')).toBe(node);
  });
  it('does not reinterpret truncated or invalid JSON', () => {
    const { container } = render(TextDocument, { text: '{"unfinished":', mime: 'application/json', truncated: true });
    expect(container.querySelector('code.hljs')?.textContent).toBe('{"unfinished":');
    expect(container.querySelector('.json-key')).toBeNull();
    expect(syntaxError('{"unfinished":', 'application/json')).not.toBe('');
    expect(syntaxError('{"done":true}', 'application/json')).toBe('');
    expect(viewEligible('image/svg+xml', 'plot.svg')).toBe(false);
  });
  it('sandboxes HTML preview and keeps source mounted', async () => {
    const create = vi.fn(() => 'blob:http://localhost/6b3a438a-2580-491f-a51e-d7e0bbdc8fd5');
    URL.createObjectURL = create; URL.revokeObjectURL = vi.fn();
    const htmlLease = { owner: 'reader', epoch: '1', signal: new AbortController().signal, assertCurrent() {}, async validate() {} };
    const { container, unmount } = render(TextDocument, { text: '<h1>Preview</h1>', mime: 'text/html', editing: true, preview: true, htmlLease });
    expect(container.querySelector('pre')).toBeTruthy();
    const frame = await screen.findByTitle('Artifact preview');
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
    expect(frame.getAttribute('src')).toMatch(/^blob:/);
    expect(create).toHaveBeenCalledOnce();
    unmount();
  });
});
