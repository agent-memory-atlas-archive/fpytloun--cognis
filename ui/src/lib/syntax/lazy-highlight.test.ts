import hljs from 'highlight.js/lib/common';
import { describe, expect, it } from 'vitest';

import { renderMarkdown } from '$lib/markdown';
import { highlightToolOutput } from './tool-output';
import { HIGHLIGHT_ATTR, highlightElement } from './lazy-highlight';

function mount(html: string): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host;
}

describe('deferred highlighting', () => {
  it('highlights a rendered markdown code block in place', () => {
    const host = mount(renderMarkdown(['```python', 'def hello():', '    return "<x>"', '```'].join('\n')));
    const code = host.querySelector(`[${HIGHLIGHT_ATTR}]`)!;
    highlightElement(code, hljs);
    expect(code.classList.contains('hljs')).toBe(true);
    expect(code.innerHTML).toContain('hljs-keyword');
    expect(code.hasAttribute(HIGHLIGHT_ATTR)).toBe(false);
    expect(code.textContent).toContain('return "<x>"');
    expect(code.querySelector('x')).toBeNull();
  });

  it('highlights tool output and leaves unknown languages as plain text', () => {
    const host = mount(highlightToolOutput('const value = "<script>";', 'typescript'));
    const span = host.querySelector(`[${HIGHLIGHT_ATTR}]`)!;
    highlightElement(span, hljs);
    expect(span.innerHTML).toContain('hljs-');
    expect(host.querySelector('script')).toBeNull();

    const unknown = mount('<code data-cognis-highlight="not-a-language">a &lt; b</code>').firstElementChild!;
    highlightElement(unknown, hljs);
    expect(unknown.innerHTML).toBe('a &lt; b');
  });
});
