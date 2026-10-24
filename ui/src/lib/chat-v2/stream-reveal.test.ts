import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamReveal } from './stream-reveal';

describe('streamReveal', () => {
  afterEach(() => vi.unstubAllGlobals());

  function setup(reduced = false) {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: reduced })));
    const node = document.createElement('div');
    node.innerHTML = '<p>Hello</p>\n';
    return { node, action: streamReveal(node, { html: node.innerHTML, streaming: true }) };
  }

  it('fades only appended text chunks, without splitting letters or changing content', () => {
    const { node, action } = setup();
    expect(node.querySelectorAll('.stream-reveal')).toHaveLength(1);
    node.innerHTML = '<p>Hello <strong>new text</strong> with a <a href="/guide">link</a></p>';
    action.update({ html: node.innerHTML, streaming: true });
    expect(node.textContent).toBe('Hello new text with a link');
    const animated = [...node.querySelectorAll('.stream-reveal')];
    expect(animated.every((span) => Boolean(span.textContent?.trim()))).toBe(true);
    expect(animated.map((span) => span.textContent).join('').replace(/\s/g, '')).toBe('newtextwithalink');
    expect(node.querySelector('a')?.getAttribute('href')).toBe('/guide');
    action.destroy();
    expect(node.querySelectorAll('.stream-reveal')).toHaveLength(0);
    expect(node.textContent).toBe('Hello new text with a link');
  });

  it('does not replay animation for unchanged content or Markdown reinterpretation', () => {
    const { node, action } = setup();
    node.innerHTML = '<h2>Hello</h2>';
    action.update({ html: node.innerHTML, streaming: true });
    expect(node.querySelectorAll('.stream-reveal')).toHaveLength(0);
    node.innerHTML = '<p>Corrected</p>';
    action.update({ html: node.innerHTML, streaming: true });
    expect(node.querySelectorAll('.stream-reveal')).toHaveLength(0);
  });

  it('skips code and controls and clears wrappers at completion', () => {
    const { node, action } = setup();
    node.innerHTML = '<p>Hello again</p><pre><code>const x = 1;</code></pre><button>Copy</button>';
    action.update({ html: node.innerHTML, streaming: true });
    expect(node.querySelector('pre .stream-reveal')).toBeNull();
    expect(node.querySelector('button .stream-reveal')).toBeNull();
    action.update({ html: node.innerHTML, streaming: false });
    expect(node.querySelectorAll('.stream-reveal')).toHaveLength(0);
  });

  it('does no text wrapping in reduced-motion mode', () => {
    const { node } = setup(true);
    expect(node.innerHTML).toBe('<p>Hello</p>\n');
  });
});
