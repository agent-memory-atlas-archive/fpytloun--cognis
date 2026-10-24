import { get, writable } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IDBFactory } from 'fake-indexeddb';
import type { DocumentCoordination } from '$lib/document-coordination';

const mocks = vi.hoisted(() => ({
  listeners: new Set<() => void>(),
  store: null as unknown as ReturnType<typeof writable<{ status: string; user: { email: string } | null }>>,
  setOwner: vi.fn(async (_owner: string | null) => {}),
  reset: vi.fn(),
}));
vi.mock('$lib/stores/auth', () => ({ auth: {
  subscribe: (run: Parameters<typeof mocks.store.subscribe>[0]) => mocks.store.subscribe(run),
  onAnonymous: (run: () => void) => { mocks.listeners.add(run); return () => mocks.listeners.delete(run); },
} }));
vi.mock('./cache', () => ({ offlineCache: { setOwner: mocks.setOwner } }));
vi.mock('$lib/chat-v2/timeline-controller.svelte', () => ({ clearTimelineMemory: vi.fn() }));
vi.mock('$lib/chat-v2/attachment-uploads', () => ({ attachmentUploads: { reset: mocks.reset } }));
vi.mock('./quarantine', () => ({ inspectRetainedData: vi.fn(async () => {}) }));

describe('offline session ownership', () => {
  let coordination: DocumentCoordination;
  beforeEach(async () => {
    vi.resetModules();
    localStorage.clear();
    localStorage.setItem('cognis:chat-v2-draft:legacy', 'retained original bytes');
    vi.clearAllMocks();
    mocks.setOwner.mockReset().mockResolvedValue(undefined);
    mocks.listeners.clear();
    mocks.store = writable({ status: 'loading', user: null });
    vi.stubGlobal('indexedDB', new IDBFactory());
    coordination = (await import('$lib/document-coordination')).documentCoordination();
    await coordination.initialize();
  });
  afterEach(() => { vi.resetModules(); vi.unstubAllGlobals(); });
  async function mount() {
    const session = await import('./session');
    session.installOfflineSession();
    return session;
  }
  async function login(email: string) {
    await coordination.beginLogin();
    await coordination.verified(email);
    mocks.store.set({ status: 'authenticated', user: { email } });
  }
  async function logout() {
    await coordination.invalidate();
    mocks.store.set({ status: 'anonymous', user: null });
    mocks.listeners.forEach((run) => run());
  }
  it('gates pages until the verified account namespace is bound, without migrating legacy bytes', async () => {
    const session = await mount();
    await login('account-a@cognis.test');
    expect(get(session.deviceDataReady)).toBe(false);
    await vi.waitFor(() => expect(get(session.deviceDataReady)).toBe(true));
    expect(mocks.setOwner).toHaveBeenCalledWith(expect.stringContaining(':account-v2:'));
    expect(localStorage.getItem('cognis:chat-v2-draft:legacy')).toBe('retained original bytes');
  });
  it('a late account-A bind cannot enable pages after account B logs in', async () => {
    let release!: () => void;
    mocks.setOwner.mockImplementationOnce(() => new Promise<void>((resolve) => { release = resolve; }));
    const session = await mount();
    await login('account-a@cognis.test');
    await vi.waitFor(() => expect(mocks.setOwner).toHaveBeenCalledOnce());
    await logout();
    await login('account-b@cognis.test');
    await vi.waitFor(() => expect(get(session.deviceDataReady)).toBe(true));
    release();
    await Promise.resolve();
    expect(mocks.setOwner).toHaveBeenLastCalledWith(expect.stringContaining('account-b'));
    expect(localStorage.getItem('cognis:chat-v2-draft:legacy')).toBe('retained original bytes');
  });
  it('logout revokes ready state and resets in-memory uploads, never deleting retained work', async () => {
    const session = await mount();
    await login('account-a@cognis.test');
    await vi.waitFor(() => expect(get(session.deviceDataReady)).toBe(true));
    await logout();
    expect(get(session.deviceDataReady)).toBe(false);
    expect(mocks.reset).toHaveBeenCalledOnce();
    expect(mocks.setOwner).toHaveBeenLastCalledWith(null);
    expect(localStorage.getItem('cognis:chat-v2-draft:legacy')).toBe('retained original bytes');
  });
  it('binding failure leaves pages/sending disabled and exposes a safe error', async () => {
    mocks.setOwner.mockRejectedValueOnce(new Error('fixture storage unavailable'));
    const session = await mount();
    await login('account-a@cognis.test');
    await vi.waitFor(() => expect(get(session.deviceDataError)).toBe('fixture storage unavailable'));
    expect(get(session.deviceDataReady)).toBe(false);
    expect(localStorage.getItem('cognis:chat-v2-draft:legacy')).toBe('retained original bytes');
  });
});
