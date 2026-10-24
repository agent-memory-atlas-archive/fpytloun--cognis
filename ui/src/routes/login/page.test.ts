import { cleanup, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import Login from './+page.svelte';

const mocks = vi.hoisted(() => ({
  bootstrap: vi.fn(),
  getSnapshot: vi.fn(),
  goto: vi.fn()
}));
vi.mock('$app/navigation', () => ({ goto: mocks.goto }));
vi.mock('$app/stores', () => ({
  page: writable({ url: new URL('http://localhost/login?returnTo=%2Fchat') })
}));
vi.mock('$lib/stores/auth', () => ({ auth: mocks }));

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.getSnapshot.mockReturnValue({ status: 'anonymous' });
});
afterEach(cleanup);

describe('login session restoration', () => {
  it('hides sign-in until session verification confirms anonymous access', async () => {
    const bootstrap = deferred();
    mocks.bootstrap.mockReturnValue(bootstrap.promise);
    render(Login);
    await waitFor(() => expect(mocks.bootstrap).toHaveBeenCalledOnce());
    expect(screen.getByText('Loading workspace')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument();
    bootstrap.resolve();
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(mocks.goto).not.toHaveBeenCalled();
  });

  it('keeps the loader through the authenticated redirect', async () => {
    const bootstrap = deferred();
    const navigation = deferred();
    mocks.bootstrap.mockReturnValue(bootstrap.promise);
    mocks.getSnapshot.mockReturnValue({ status: 'authenticated' });
    mocks.goto.mockReturnValue(navigation.promise);
    render(Login);
    bootstrap.resolve();
    await waitFor(() => expect(mocks.goto).toHaveBeenCalledWith('/chat', { replaceState: true }));
    expect(screen.getByText('Loading workspace')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument();
    navigation.resolve();
  });

  it('shows a usable sign-in form if bootstrap rejects', async () => {
    mocks.bootstrap.mockRejectedValue(new Error('Unable to restore session'));
    render(Login);
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByText('Unable to restore session')).toBeInTheDocument();
    expect(screen.queryByText('Loading workspace')).not.toBeInTheDocument();
  });
});
