import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import CognisLogo from './CognisLogo.svelte';
import mono from '../../../static/brand/cognis-mark.svg?raw';

afterEach(cleanup);

describe('CognisLogo', () => {
  it('renders canonical geometry, scoped gradients, and decorative semantics', () => {
    const first = render(CognisLogo, { class: 'h-10 w-10' });
    const second = render(CognisLogo);
    const svg = first.container.querySelector('svg')!;
    expect(first.container.querySelector('.cognis-logo')?.getAttribute('aria-hidden')).toBe('true');
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    expect(svg.getAttribute('focusable')).toBe('false');
    expect(svg.querySelectorAll('path')).toHaveLength(4);
    const master = new DOMParser().parseFromString(mono, 'image/svg+xml');
    expect([...svg.querySelectorAll('path')].map((p) => p.getAttribute('d')))
      .toEqual([...master.querySelectorAll('path')].map((p) => p.getAttribute('d')));
    const gradient = svg.querySelector('linearGradient')!.id;
    expect(svg.getAttribute('fill')).toBe(`url(#${gradient})`);
    expect(second.container.querySelector('linearGradient')!.id).not.toBe(gradient);
    const ids = [...document.querySelectorAll('.cognis-logo [id]')].map((node) => node.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(svg.querySelector('image, script, foreignObject, rect')).toBeNull();
  });

  it('exposes one accessible name and supports inherited monochrome color', async () => {
    const view = render(CognisLogo, { variant: 'mono', label: 'Cognis' });
    expect(view.getByRole('img', { name: 'Cognis' })).toBeTruthy();
    expect(view.container.querySelector('svg')!.getAttribute('fill')).toBe('currentColor');
    expect(view.container.querySelector('linearGradient')).toBeNull();
    expect(view.container.querySelector('circle')!.getAttribute('fill')).toBeNull();
    await view.rerender({ variant: 'color', label: '' });
    expect(view.queryByRole('img')).toBeNull();
    expect(view.container.querySelector('linearGradient')).not.toBeNull();
  });
});
