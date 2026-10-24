import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SidebarRefreshController, RefreshCooldown } from './sidebar-refresh';
import { SidebarRefreshLifecycle } from './sidebar-refresh-lifecycle';
import { receiveNativeVisibility } from './native/host';

const mocks = vi.hoisted(() => ({
  state: { status: 'authenticated', user: { email: 'owner@cognis.test' }, offline: false },
  capture: vi.fn(),
  invalidated: new Set<() => void>(),
}));
vi.mock('./stores/auth', () => ({
  auth: {
    getSnapshot: () => mocks.state,
    subscribe: (listener: () => void) => { listener(); return () => {}; },
  },
}));
vi.mock('./document-coordination', async importOriginal => ({
  ...await importOriginal<typeof import('./document-coordination')>(),
  documentCoordination: () => ({
    capture: mocks.capture,
    onInvalidated: (listener: () => void) => {
      mocks.invalidated.add(listener);
      return () => { mocks.invalidated.delete(listener); };
    },
  }),
}));

let stop: (() => void) | undefined;
beforeEach(() => {
  vi.useFakeTimers();
  mocks.state = { status: 'authenticated', user: { email: 'owner@cognis.test' }, offline: false };
  mocks.capture.mockReturnValue({ owner: 'https://cognis.test\nowner@cognis.test', signal: new AbortController().signal });
});
afterEach(() => {
  stop?.(); stop = undefined;
  delete window.__cognisNative;
  receiveNativeVisibility(false, false);
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function setup() {
  const run = vi.fn().mockRejectedValue({ status: 503 });
  const controller = new SidebarRefreshController(run, new RefreshCooldown());
  let scope = 'owner/web';
  const lifecycle = new SidebarRefreshLifecycle([controller], () => scope);
  stop = lifecycle.start();
  return { run, controller, lifecycle, setScope: (next: string) => { scope = next; lifecycle.sync(); } };
}

describe('sidebar lifecycle integration', () => {
  it('suspends offline probes and resumes one due probe despite foreground storms', async () => {
    const f = setup();
    await f.controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(8_000);
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    window.dispatchEvent(new Event('offline'));
    await vi.advanceTimersByTimeAsync(180_000);
    expect(f.run).toHaveBeenCalledTimes(3);
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
    for (let i = 0; i < 100; i++) {
      window.dispatchEvent(new Event('online'));
      window.dispatchEvent(new Event('focus'));
    }
    await vi.advanceTimersByTimeAsync(0);
    expect(f.run).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(59_999);
    expect(f.run).toHaveBeenCalledTimes(4);
  });

  it('uses native visibility, not focused observation, and excludes replicas', async () => {
    window.__cognisNative = {
      version: 1, generation: '8d6feafb-2aac-4b41-ac82-42b2314563bb', server: window.location.origin,
      surface: 'main',
    };
    receiveNativeVisibility(false, false);
    const f = setup();
    await f.controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(180_000);
    expect(f.run).not.toHaveBeenCalled();
    receiveNativeVisibility(true, false);
    await vi.advanceTimersByTimeAsync(0);
    expect(f.run).toHaveBeenCalledTimes(1);
    window.__cognisNative.surface = 'conversation';
    f.lifecycle.sync();
    window.dispatchEvent(new Event('focus'));
    await vi.advanceTimersByTimeAsync(180_000);
    expect(f.run).toHaveBeenCalledTimes(1);
  });

  it('reconciles on native resume even without a pending invalidation or focus event', async () => {
    window.__cognisNative = {
      version: 1, generation: '8d6feafb-2aac-4b41-ac82-42b2314563bb', server: window.location.origin,
      surface: 'main',
    };
    receiveNativeVisibility(true, true);
    const f = setup();
    f.run.mockResolvedValue(undefined);
    await f.controller.request('owner/web');
    receiveNativeVisibility(false, false);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(f.run).toHaveBeenCalledTimes(1);
    receiveNativeVisibility(true, false);
    await vi.advanceTimersByTimeAsync(0);
    expect(f.run).toHaveBeenCalledTimes(2);
    // Duplicate visibility notifications do not schedule more work.
    receiveNativeVisibility(true, false);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(f.run).toHaveBeenCalledTimes(2);
  });

  it('keeps hidden documents quiet and cancels on owner revocation and teardown', async () => {
    const f = setup();
    await f.controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(8_000);
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(180_000);
    expect(f.run).toHaveBeenCalledTimes(3);
    mocks.capture.mockImplementation(() => { throw new Error('Owner revoked'); });
    for (const listener of mocks.invalidated) listener();
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
    window.dispatchEvent(new Event('focus'));
    await vi.advanceTimersByTimeAsync(180_000);
    expect(f.run).toHaveBeenCalledTimes(3);
    stop?.(); stop = undefined;
    expect(mocks.invalidated.size).toBe(0);
    mocks.capture.mockReturnValue({ owner: 'https://cognis.test\nowner@cognis.test', signal: new AbortController().signal });
    window.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(180_000);
    expect(f.run).toHaveBeenCalledTimes(3);
  });
});
