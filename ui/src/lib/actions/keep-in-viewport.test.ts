import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { keepInViewport } from './keep-in-viewport';

function stubRect(node: HTMLElement, rect: () => { left: number; width: number }) {
  node.getBoundingClientRect = () => {
    const { left, width } = rect();
    return { left, right: left + width, width, top: 0, bottom: 10, height: 10, x: left, y: 0, toJSON: () => ({}) } as DOMRect;
  };
}

describe('keepInViewport', () => {
  beforeEach(() => {
    Object.defineProperty(document.documentElement, 'clientWidth', { configurable: true, value: 390 });
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('shifts a popup that overflows the left edge back inside', () => {
    const node = document.createElement('div');
    document.body.appendChild(node);
    stubRect(node, () => ({ left: -120, width: 288 }));
    const action = keepInViewport(node);
    expect(node.style.translate).toBe('128px 0');
    action.destroy();
  });

  it('shifts a popup that overflows the right edge back inside', () => {
    const node = document.createElement('div');
    document.body.appendChild(node);
    stubRect(node, () => ({ left: 200, width: 288 }));
    const action = keepInViewport(node);
    expect(node.style.translate).toBe('-106px 0');
    action.destroy();
  });

  it('leaves a popup that fits untouched and caps one wider than the viewport', () => {
    const fits = document.createElement('div');
    document.body.appendChild(fits);
    stubRect(fits, () => ({ left: 20, width: 200 }));
    keepInViewport(fits).destroy();
    expect(fits.style.translate).toBe('');

    const wide = document.createElement('div');
    document.body.appendChild(wide);
    let width = 600;
    stubRect(wide, () => ({ left: 0, width }));
    const action = keepInViewport(wide);
    expect(wide.style.maxWidth).toBe('374px');
    // Simulate the browser applying the cap on the next measurement.
    width = 374;
    action.update();
    expect(wide.style.translate).toBe('8px 0');
    action.destroy();
  });
});
