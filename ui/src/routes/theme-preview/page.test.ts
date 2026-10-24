import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ThemePreview from './+page.svelte';
import { get, writable } from 'svelte/store';
import { DEFAULT_USER_PREFERENCES } from '$lib/user-preferences';
import { userPreferences } from '$lib/stores/userPreferences';
import { startUserPreferences } from '$lib/stores/userPreferences';
import { startAppearance } from '$lib/theme/appearance';

beforeEach(() => {
  document.head.innerHTML = `<style>
    :root { --app-chrome-bg: #f0f2f3; }
    :root[data-resolved-theme="dark"] { --app-chrome-bg: #1c2220; }
    :root[data-theme-family="paper"][data-resolved-theme="light"] { --app-chrome-bg: #f3f3f0; }
    :root[data-theme-family="paper"][data-resolved-theme="dark"] { --app-chrome-bg: #1f1e1d; }
  </style>`;
});

function expectProjection(family: string, mode: 'light' | 'dark', chrome: string) {
  const root = document.documentElement;
  expect(root.dataset.themeFamily).toBe(family);
  expect(root.dataset.resolvedTheme).toBe(mode);
  expect(root.classList.contains('dark')).toBe(mode === 'dark');
  expect(root.style.colorScheme).toBe(mode);
  expect(document.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe(chrome);
  expect(document.querySelector('meta[name="color-scheme"]')?.getAttribute('content')).toBe(mode);
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState({}, '', '/');
});

it('preserves explicit family/mode through startup writes without changing account preferences', async () => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn()
  })));
  window.history.replaceState({}, '', '/theme-preview?theme=light&family=gruvbox');
  const view = render(ThemePreview);
  // Root layout mounts after its child and publishes the account default first.
  const stopAppearance = startAppearance();
  const stopPreferences = startUserPreferences();
  await waitFor(() => expect(document.documentElement.dataset.themeFamily).toBe('gruvbox'));
  expect(document.documentElement.dataset.resolvedTheme).toBe('light');
  await fireEvent.change(screen.getByRole('combobox', { name: 'Family' }), { target: { value: 'paper' } });
  expectProjection('paper', 'light', '#f3f3f0');
  expect(get(userPreferences).display.theme_family).toBe('classic');
  view.unmount();
  expectProjection('classic', 'dark', '#1c2220');
  stopPreferences();
  stopAppearance();
});

it('switches real shared controls between light, dark and system without account persistence', async () => {
  const media = {
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  vi.stubGlobal('matchMedia', vi.fn(() => media));
  window.history.replaceState({}, '', '/theme-preview?theme=light');
  render(ThemePreview);
  const appearance = screen.getByRole('combobox', { name: 'Appearance' });
  await waitFor(() => expect(screen.getByTestId('theme-preview')).toHaveAttribute('data-theme', 'light'));
  expect(screen.getByRole('button', { name: 'Approve' })).toHaveClass('bg-accent', 'text-on-accent');
  await fireEvent.change(appearance, { target: { value: 'dark' } });
  expectProjection('classic', 'dark', '#1c2220');
  await fireEvent.change(appearance, { target: { value: 'light' } });
  expect(document.documentElement.dataset.resolvedTheme).toBe('light');
  await fireEvent.change(appearance, { target: { value: 'system' } });
  expect(document.documentElement.dataset.resolvedTheme).toBe('dark');
  await fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(screen.getByRole('status')).toHaveTextContent('No deployment was started.');
  await fireEvent.click(screen.getByRole('button', { name: 'Review task' }));
  expect(screen.getByRole('dialog', { name: 'Deployment review' })).toBeInTheDocument();
});

it('keeps preview metadata after account notifications and restores current System/account state on exit', async () => {
  const account = writable(structuredClone(DEFAULT_USER_PREFERENCES));
  vi.spyOn(userPreferences, 'subscribe').mockImplementation(account.subscribe);
  const media = Object.assign(new EventTarget(), { matches: false });
  vi.stubGlobal('matchMedia', vi.fn(() => media));
  window.history.replaceState({}, '', '/theme-preview?theme=dark&family=paper');
  const view = render(ThemePreview);
  const stopAppearance = startAppearance();
  try {
    await waitFor(() => expectProjection('paper', 'dark', '#1f1e1d'));
    const current = structuredClone(DEFAULT_USER_PREFERENCES);
    current.display.theme_family = 'classic';
    current.display.theme = 'light';
    account.set(current);
    await waitFor(() => expectProjection('paper', 'dark', '#1f1e1d'));
    expect(get(userPreferences)).toEqual(current);

    await fireEvent.change(screen.getByRole('combobox', { name: 'Appearance' }), { target: { value: 'system' } });
    expectProjection('paper', 'light', '#f3f3f0');
    media.matches = true;
    media.dispatchEvent(new Event('change'));
    await waitFor(() => expectProjection('paper', 'dark', '#1f1e1d'));

    // Leave with a newer account choice while its preview callback is queued.
    // Cleanup must restore current preferences and cancel that queued repaint.
    current.display.theme_family = 'classic';
    current.display.theme = 'system';
    account.set(current);
    view.unmount();
    await Promise.resolve();
    expectProjection('classic', 'dark', '#1c2220');
    expect(get(userPreferences)).toEqual(current);
  } finally {
    stopAppearance();
  }
});

it.each(['light', 'dark'] as const)('retains explicit %s preview after OS listeners and cancels queued OS projection on exit', async (mode) => {
  const current = structuredClone(DEFAULT_USER_PREFERENCES);
  current.display.theme_family = 'classic';
  current.display.theme = 'system';
  const account = writable(current);
  vi.spyOn(userPreferences, 'subscribe').mockImplementation(account.subscribe);
  const media = Object.assign(new EventTarget(), { matches: false });
  vi.stubGlobal('matchMedia', vi.fn(() => media));
  window.history.replaceState({}, '', `/theme-preview?theme=${mode}&family=paper`);
  const view = render(ThemePreview);
  // Match child-before-parent mount order, including the competing OS listener.
  const stopAppearance = startAppearance();
  const chrome = mode === 'dark' ? '#1f1e1d' : '#f3f3f0';
  try {
    await waitFor(() => expectProjection('paper', mode, chrome));
    for (const systemDark of [true, false, true]) {
      media.matches = systemDark;
      media.dispatchEvent(new Event('change'));
      await waitFor(() => expectProjection('paper', mode, chrome));
      expect(get(userPreferences)).toEqual(current);
    }

    const latest = structuredClone(current);
    latest.display.theme_family = 'gruvbox';
    latest.display.theme = 'light';
    account.set(latest);
    media.matches = false;
    media.dispatchEvent(new Event('change'));
    view.unmount();
    await Promise.resolve();
    expectProjection('gruvbox', 'light', '#f0f2f3');
    expect(get(userPreferences)).toEqual(latest);
  } finally {
    stopAppearance();
  }
});
