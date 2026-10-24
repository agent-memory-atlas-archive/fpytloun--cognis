import { describe, expect, it } from 'vitest';

import { createMarkdownStreamer, renderMarkdown } from './markdown';

describe('createMarkdownStreamer', () => {
  const preCount = (html: string) => html.match(/<pre\b/g)?.length ?? 0;

  it.each([
    '- first\n\n- second\n\nTail',
    '> first\n\n> second\n\nTail',
    '[guide][ref]\n\n[ref]: https://example.com\n\nTail',
    '1. first\n\n   continuation\n\n2. second\n\nTail',
    '[ref]: https://example.com\n\nRead [guide][ref]',
    '[guide]: https://example.com\n\nRead [guide][]',
    '[guide]: https://example.com\n\nRead [guide]',
    '[photo]: https://example.com/photo.png\n\n![Photo][photo]',
  ])('preserves Markdown block structure while streaming %s', (content) => {
    expect(createMarkdownStreamer().render(content)).toBe(renderMarkdown(content));
  });

  it.each(['![', '![Photo', '![Photo]', '![Photo](', '![Photo](https://example.com/photo'])(
    'withholds an incomplete image without hiding earlier text: %s', (partial) => {
      const s = createMarkdownStreamer();
      expect(s.render(`## Photo\n\n${partial}`)).toBe(renderMarkdown('## Photo\n\n'));
      const complete = '## Photo\n\n![Photo](https://example.com/photo.png)';
      expect(s.render(complete)).toBe(renderMarkdown(complete));
      expect(s.finalize(`## Photo\n\n${partial}`)).toBe(renderMarkdown(`## Photo\n\n${partial}`));
    }
  );

  it('keeps incomplete link labels readable without exposing partial destinations', () => {
    const s = createMarkdownStreamer();
    expect(s.render('Read [the guide](https://example.com/gu')).toBe(renderMarkdown('Read the guide'));
    expect(s.render('Read [the gui')).toBe(renderMarkdown('Read the gui'));
  });

  it.each(['`![`', '```\n![\n', '    ![', '\\![', '[literal]\n\nNext paragraph'])(
    'does not hide code, escapes, or earlier bracketed text: %s', (content) => {
      expect(createMarkdownStreamer().render(content)).toBe(renderMarkdown(content));
    }
  );

  it.each([
    ['**Yes—that is a', '**Yes—that is a**'],
    ['**Yes—that is a*', '**Yes—that is a**'],
    ['An _unfinished phrase', 'An _unfinished phrase_'],
    ['Use `snake_case', 'Use `snake_case`'],
    ['Use `data[', 'Use `data[`'],
    ['Use `![literal', 'Use `![literal`'],
    ['~~obsolete answer', '~~obsolete answer~~'],
    ['**Bold and _nested', '**Bold and _nested_**'],
    ['**𝑥 is a variable', '**𝑥 is a variable**'],
    ['Ready **', 'Ready '],
    ['**', ''],
  ])('hides incomplete syntax and previews known formatting for %s', (partial, preview) => {
    const streamer = createMarkdownStreamer();
    expect(streamer.render(partial)).toBe(renderMarkdown(preview));
    expect(streamer.finalize(partial)).toBe(renderMarkdown(partial));
  });

  it.each([
    'a * b', 'snake_case', 'glob **/*.py', '\\**literal', '`**literal**`',
    '```python\nvalue = "**literal"\n', 'Price: $5.00', '[**label**](https://example.com)',
    '```md\n**do not bold** and `do not toggle`\n![literal]\n',
    '~~~md\n**do not bold** and `do not toggle`\n![literal]\n',
    '    **literal** and `literal`\n',
    '> ~~~js\n> **literal and `tick`\n',
    '- Code:\n\n  ```md\n  **literal and `tick`\n',
  ])('preserves literal syntax and complete constructs: %s', (content) => {
    expect(createMarkdownStreamer().render(content)).toBe(renderMarkdown(content));
  });

  it('continues rendering every prefix before completion without exposing bold delimiters', () => {
    const streamer = createMarkdownStreamer();
    for (const chunk of ['**Yes', '**Yes—that', '**Yes—that is a', '**Yes—that is a good case**.']) {
      const html = streamer.render(chunk);
      expect(html).not.toContain('**');
      const preview = document.createElement('div');
      preview.innerHTML = html;
      expect(preview.textContent?.trim()).toBe(chunk.replaceAll('**', ''));
    }
    const complete = '**Yes—that is a good case**.';
    expect(streamer.finalize(complete)).toBe(renderMarkdown(complete));
  });

  it('processes repeated code spans without quadratic duplicate protection', () => {
    const source = ('`x` '.repeat(3000)) + '**Preview';
    expect(createMarkdownStreamer().render(source)).toBe(renderMarkdown(source + '**'));
  });

  it('renders empty string for empty input', () => {
    const s = createMarkdownStreamer();
    expect(s.render('')).toBe('');
  });

  it('produces the same final HTML as a direct parse', () => {
    const content = `# Title\n\nParagraph one.\n\nParagraph two with **bold**.\n\n- a\n- b\n`;
    const s = createMarkdownStreamer();
    const finalHtml = s.finalize(content);
    expect(finalHtml).toContain('<h1');
    expect(finalHtml).toContain('Paragraph one');
    expect(finalHtml).toContain('Paragraph two');
    expect(finalHtml.toLowerCase()).toContain('<strong>bold</strong>');
    expect(finalHtml).toContain('<li>a</li>');
    expect(finalHtml).toContain('<li>b</li>');
  });

  it('reuses cached blocks on incremental render', () => {
    const s = createMarkdownStreamer();
    // Stream a message token-by-token building up 3 blocks.
    const chunks = ['# Hi\n\n', 'First.\n\n', 'Second block.'];
    let content = '';
    for (const chunk of chunks) {
      content += chunk;
      const html = s.render(content);
      expect(html).toContain('<h1');
    }
    // Final pass includes both paragraphs.
    const finalHtml = s.finalize(content);
    expect(finalHtml).toContain('First.');
    expect(finalHtml).toContain('Second block.');
  });

  it('keeps fenced code blocks intact while streaming', () => {
    const s = createMarkdownStreamer();
    const intermediate = '```ts\nlet x = 1;\n';
    // Tail is an unclosed fence - should not be split.
    const html1 = s.render(intermediate);
    expect(html1).toContain('data-cognis-highlight="ts"');
    expect(html1).toContain('x =');

    const closed = intermediate + '```\n\nFollow-up.';
    const html2 = s.finalize(closed);
    expect(html2).toContain('Follow-up.');
  });

  it('does not close an outer streaming fence on an inner language fence opener', () => {
    const s = createMarkdownStreamer();
    const html = s.render(
      [
        '```text',
        'Task: Keep all following content inside this block.',
        '',
        '```json',
        '{"value": 1}',
        '```',
        '',
        'Still part of the outer text block.',
      ].join('\n')
    );

    expect(preCount(html)).toBe(1);
    expect(html).toContain('Still part of the outer text block.');
    expect(html).not.toContain('<p>Still part of the outer text block.</p>');
  });

  it('reset() drops the cache so next render parses fresh', () => {
    const s = createMarkdownStreamer();
    const content = 'A paragraph.\n\nAnother.';
    s.finalize(content);
    s.reset();
    const html = s.render(content);
    expect(html).toContain('paragraph');
  });

  it('handles empty tail without crashing', () => {
    const s = createMarkdownStreamer();
    // Content ending with trailing whitespace should not produce garbage.
    const html = s.render('Block one.\n\n   ');
    expect(html).toContain('Block one');
  });

  it('treats tilde-fenced code blocks identically to backtick fences', () => {
    const backtickContent = '```\nhello\n```\n\nAfter.';
    const tildeContent = '~~~\nhello\n~~~\n\nAfter.';
    const backtickHtml = createMarkdownStreamer().finalize(backtickContent);
    const tildeHtml = createMarkdownStreamer().finalize(tildeContent);
    // Both should produce equivalent block structure: a fenced code block
    // followed by a paragraph. The number of <pre>/<p> tags must match; the
    // cached block boundary behavior must be identical between fence styles.
    const preCount = (s: string) => (s.match(/<pre\b/g) ?? []).length;
    const pCount = (s: string) => (s.match(/<p\b/g) ?? []).length;
    expect(preCount(backtickHtml)).toBe(preCount(tildeHtml));
    expect(pCount(backtickHtml)).toBe(pCount(tildeHtml));
    expect(backtickHtml).toContain('hello');
    expect(tildeHtml).toContain('hello');
    expect(backtickHtml).toContain('After');
    expect(tildeHtml).toContain('After');
  });

  it('does not activate a split iframe until the complete token arrives', () => {
    const s = createMarkdownStreamer();
    const first = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"';
    const complete = `${first}></iframe>`;

    expect(s.render(first)).not.toContain('<iframe');
    expect(s.render(first)).not.toContain('markdown-youtube-embed');
    expect(s.render(complete)).toContain('markdown-youtube-embed');
    expect(s.finalize(complete)).toBe(renderMarkdown(complete));
  });

  it('does not stabilize an incomplete iframe block before a later closing tag', () => {
    const s = createMarkdownStreamer();
    const partial = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ">\n\n';
    const complete = `${partial}</iframe>`;

    expect(s.render(partial)).not.toContain('markdown-youtube-embed');
    expect(s.finalize(complete)).toBe(renderMarkdown(complete));
  });

  it('does not treat inline code that mentions iframe as an incomplete HTML token', () => {
    const s = createMarkdownStreamer();
    const content = '`<iframe` is inert.\n\nA stable following block.';

    expect(s.render(content)).toContain('A stable following block.');
    expect(s.finalize(content)).toBe(renderMarkdown(content));
  });

  it('does not treat indented iframe code as an incomplete HTML token', () => {
    const s = createMarkdownStreamer();
    const content = '    <iframe\n\nA stable following block.';

    expect(s.render(content)).toContain('A stable following block.');
    expect(s.finalize(content)).toBe(renderMarkdown(content));
  });

  it('does not cache resolver results when hooks have no cache key', () => {
    let prefix = '/first/';
    const content = '[document](./guide.md)\n\nTail';
    const s = createMarkdownStreamer({
      resolveLink: (href) => `${prefix}${href}`,
    });

    expect(s.render(content)).toContain('/first/./guide.md');
    prefix = '/second/';
    expect(s.render(content)).toContain('/second/./guide.md');
  });
});
