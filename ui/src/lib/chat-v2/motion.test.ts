import { afterEach, describe, expect, it, vi } from 'vitest';
import { CHAT_MOTION, ChatArrivalRegistry, messageArrival, chatDisclosure } from './motion';
import { streamReveal } from './stream-reveal';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('selected chat motion', () => {
  it('uses the selected recipe', () => {
    expect(CHAT_MOTION).toEqual({ activity: 1600, message: 280, stream: 320, disclosure: 180, state: 240 });
  });

  it('claims live arrivals once and never replays restored or folded history', () => {
    const registry = new ChatArrivalRegistry(['history']);
    expect(registry.claim('history', true)).toBe(false);
    expect(registry.claim('live', true)).toBe(true);
    expect(registry.claim('live', true)).toBe(false);
    registry.remember(['folded']);
    expect(registry.claim('folded', true)).toBe(false);
    expect(registry.claim('pagination', false)).toBe(false);
    expect(registry.claim('pagination', true)).toBe(false);
    registry.reset(['new-conversation']);
    expect(registry.claim('new-conversation', true)).toBe(false);
  });

  it('animates one live entry for 280ms and cancels on removal', () => {
    const node = document.createElement('div');
    const cancel = vi.fn();
    node.animate = vi.fn().mockReturnValue({ cancel });
    const registry = new ChatArrivalRegistry([]);
    const action = messageArrival(node, { id: 'live', eligible: true, registry });
    expect(node.animate).toHaveBeenCalledWith(
      [{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'translateY(0)' }],
      { duration: 280, easing: 'cubic-bezier(.16,1,.3,1)' },
    );
    messageArrival(node, { id: 'live', eligible: true, registry });
    expect(node.animate).toHaveBeenCalledTimes(1);
    action.destroy();
    expect(cancel).toHaveBeenCalledOnce();
  });

  it('does not animate restored live messages or reduced motion', () => {
    const node = document.createElement('div');
    node.animate = vi.fn();
    const registry = new ChatArrivalRegistry(['restored']);
    messageArrival(node, { id: 'restored', eligible: true, registry });
    vi.stubGlobal('matchMedia', () => ({ matches: true } as MediaQueryList));
    messageArrival(node, { id: 'new', eligible: true, registry });
    expect(node.animate).not.toHaveBeenCalled();
  });

  it('discloses immediately when Web Animations are unavailable', () => {
    const node = document.createElement('div');
    expect(chatDisclosure(node)).toEqual({ duration: 0 });
  });

  it('soft-reveals only new words, preserves code and does not replay after a pause', () => {
    const node = document.createElement('div');
    node.innerHTML = '<p>Hello world</p><pre><code>literal_code</code></pre>';
    const action = streamReveal(node, { html: node.innerHTML, streaming: true });
    expect([...node.querySelectorAll('.stream-reveal')].map(span => span.textContent)).toEqual(['Hello ', 'world']);
    expect(node.querySelector('code .stream-reveal')).toBeNull();
    const text = node.textContent;
    action.update({ html: node.innerHTML, streaming: false });
    expect(node.querySelectorAll('.stream-reveal')).toHaveLength(0);
    node.innerHTML = '<p>Hello world more words</p><pre><code>literal_code</code></pre>';
    action.update({ html: node.innerHTML, streaming: true });
    expect([...node.querySelectorAll('.stream-reveal')].map(span => span.textContent)).toEqual(['more ', 'words']);
    action.destroy();
    expect(node.textContent).toBe('Hello world more wordsliteral_code');
    expect(text).toBe('Hello worldliteral_code');
  });
});
