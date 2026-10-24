import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import FindHarness from './FindHarness.svelte';
import { resetOverlayState } from '$lib/stores/overlays';

vi.mock('svelte/transition', () => ({ fade: () => ({ duration: 0 }), fly: () => ({ duration: 0 }) }));
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(function () {
    return [{ width: 100, height: 30, top: 0, left: 0, right: 100, bottom: 30 }] as unknown as DOMRectList;
  });
});
afterEach(() => { cleanup(); resetOverlayState(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function find(target: HTMLElement, metaKey = false) {
  const event = new KeyboardEvent('keydown', { key: 'f', ctrlKey: !metaKey, metaKey, bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event;
}

it('opens real ChatSearchBar, focuses/selects query and leaves composer and submission untouched', async () => {
  const submit = vi.fn();
  render(FindHarness, { submit });
  const composer = screen.getByRole('textbox', { name: 'Composer' }) as HTMLTextAreaElement;
  composer.focus();
  expect(find(composer).defaultPrevented).toBe(true);
  await tick();
  await Promise.resolve();
  const search = screen.getByPlaceholderText('Search this conversation') as HTMLInputElement;
  await waitFor(() => expect(document.activeElement).toBe(search));
  expect([search.selectionStart, search.selectionEnd]).toEqual([0, search.value.length]);
  expect(search.value).toBe('retained query');
  expect(composer.value).toBe('draft retained');
  expect(submit).not.toHaveBeenCalled();
  search.setSelectionRange(2, 3);
  find(search, true);
  await tick();
  await waitFor(() => expect(search.selectionStart).toBe(0));
});

it('does not fall through a searchless Sheet; finds its search when present and preserves Escape', async () => {
  render(FindHarness, { submit: vi.fn() });
  await fireEvent.click(screen.getByText('Open modal'));
  expect(find(document.body).defaultPrevented).toBe(false);
  await fireEvent.click(screen.getByText('Toggle modal search'));
  expect(find(document.body).defaultPrevented).toBe(true);
  expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Modal search' }));
  await fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

it('unmount removes registrations and listener', () => {
  const view = render(FindHarness, { submit: vi.fn() });
  view.unmount();
  expect(find(document.body).defaultPrevented).toBe(false);
});

it('finds only the top of two real portalled dialogs', async () => {
  render(FindHarness, { submit: vi.fn() });
  await fireEvent.click(screen.getByText('Open lower dialog'));
  await fireEvent.click(screen.getByText('Open upper dialog'));
  expect(screen.getAllByRole('dialog')).toHaveLength(2);
  expect(find(document.body).defaultPrevented).toBe(true);
  expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Upper search' }));
  await fireEvent.keyDown(window, { key: 'Escape' });
  expect(find(document.body).defaultPrevented).toBe(true);
  expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Lower search' }));
});
