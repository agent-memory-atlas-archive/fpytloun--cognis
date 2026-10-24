interface StreamRevealState {
  html: string;
  streaming: boolean;
}

/** Fade newly arrived prose without a typing queue or per-letter work. */
export function streamReveal(node: HTMLElement, initial: StreamRevealState) {
  let previous = '';
  let wrappers: HTMLSpanElement[] = [];

  function clear(): void {
    for (const wrapper of wrappers) {
      if (wrapper.parentNode) wrapper.replaceWith(...wrapper.childNodes);
    }
    wrappers = [];
  }

  function update(state: StreamRevealState): void {
    clear();
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, {
      acceptNode: (text) => text.parentElement?.closest('pre, code, button, [data-copy-exclude]')
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
    });
    const texts: Text[] = [];
    while (walker.nextNode()) texts.push(walker.currentNode as Text);
    const content = texts.map((text) => text.data).join('');
    if (!state.streaming || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      previous = content.trimEnd();
      return;
    }
    // Delimiters can reinterpret Markdown; do not fade existing text again.
    let prefix = 0;
    while (prefix < previous.length && prefix < content.length && previous[prefix] === content[prefix]) prefix++;
    const appendOnly = prefix === previous.length;
    // Markdown renderers append block newlines. They are not part of the
    // visible prefix when more text arrives inside the last paragraph.
    previous = content.trimEnd();
    if (!appendOnly) return;

    let offset = 0;
    for (const text of texts) {
      const end = offset + text.length;
      if (end > prefix && text.data.trim()) {
        const added = prefix > offset ? text.splitText(prefix - offset) : text;
        const fragment = document.createDocumentFragment();
        // Fade words together as received, never stagger or queue delivery.
        for (const part of added.data.match(/\S+\s*|\s+/gu) ?? []) {
          if (!part.trim()) {
            fragment.append(document.createTextNode(part));
            continue;
          }
          const span = document.createElement('span');
          span.className = 'stream-reveal';
          span.textContent = part;
          fragment.append(span);
          wrappers.push(span);
        }
        added.replaceWith(fragment);
      }
      offset = end;
    }
  }

  update(initial);
  return { update, destroy: clear };
}
