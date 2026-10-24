import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { DEFAULT_USER_PREFERENCES } from '$lib/user-preferences';
import type { UserPreferences } from '$lib/types/api';

const environment = vi.hoisted(() => ({
  owner: 'https://controller.test\nfirst@cognis.test' as string | null,
  epoch: 'epoch-1',
  listeners: new Set<() => void>(),
}));
vi.mock('$app/environment', () => ({ browser: true }));
vi.mock('$lib/api/client', () => ({ api: { userPreferences: { get: vi.fn(), update: vi.fn() } } }));
vi.mock('$lib/errors', () => ({ reportError: vi.fn() }));
vi.mock('$lib/stores/auth', async () => {
  const { writable } = await import('svelte/store');
  const state = writable({ status: 'authenticated', user: { email: 'first@cognis.test' } });
  return { auth: { ...state } };
});
vi.mock('$lib/document-coordination', () => ({
  documentCoordination: () => ({
    capture: () => {
      const owner = environment.owner, epoch = environment.epoch;
      const assertCurrent = () => {
        if (!owner || owner !== environment.owner || epoch !== environment.epoch) throw new Error('Stale document');
      };
      assertCurrent();
      return { owner, epoch, signal: new AbortController().signal, assertCurrent, validate: async () => assertCurrent() };
    },
    storageName: (name: string) => `${name}:account-v2:${encodeURIComponent(environment.owner!)}`,
    onInvalidated: (listener: () => void) => {
      environment.listeners.add(listener);
      return () => environment.listeners.delete(listener);
    },
  }),
}));

function prefs(separate: boolean): UserPreferences {
  const value = structuredClone(DEFAULT_USER_PREFERENCES);
  value.chat.keep_assistant_messages_separate = separate;
  value.display.theme_family = separate ? 'paper' : 'classic';
  return value;
}
function deferred() {
  let resolve!: (value: UserPreferences) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<UserPreferences>((done, fail) => { resolve = done; reject = fail; });
  return { resolve, reject, promise };
}
let stop: (() => void) | undefined;
afterEach(() => { stop?.(); stop = undefined; });
beforeEach(() => {
  vi.resetModules(); vi.clearAllMocks(); localStorage.clear();
  environment.owner = 'https://controller.test\nfirst@cognis.test';
  environment.epoch = 'epoch-1'; environment.listeners.clear();
});

describe('authenticated document preference lifecycle', () => {
  async function start() {
    const { api } = await import('$lib/api/client');
    const store = await import('./userPreferences');
    vi.mocked(api.userPreferences.get).mockResolvedValue(prefs(true));
    stop = store.startUserPreferences();
    await vi.waitFor(() => expect(get(store.userPreferences).chat.keep_assistant_messages_separate).toBe(true));
    return { api, ...store };
  }

  it('loads a cold document without mounting any chat or settings page and clears synchronously on revocation', async () => {
    const store = await start();
    environment.owner = null; environment.epoch = 'epoch-2';
    environment.listeners.forEach((listener) => listener());
    expect(get(store.userPreferences)).toEqual(DEFAULT_USER_PREFERENCES);
    expect(get(store.userPreferencesReady)).toBe(false);
  });

  it('resets synchronously on anonymous auth and never adopts the same email cache from another profile', async () => {
    const store = await start();
    const { auth } = await import('$lib/stores/auth');
    const state = auth as unknown as { set(value: unknown): void };
    state.set({ status: 'anonymous', user: null });
    expect(get(store.userPreferences)).toEqual(DEFAULT_USER_PREFERENCES);
    environment.owner = 'https://other.test\nfirst@cognis.test';
    environment.epoch = 'other-profile-epoch';
    vi.mocked(store.api.userPreferences.get).mockRejectedValueOnce(new Error('Offline'));
    state.set({ status: 'authenticated', user: { email: 'first@cognis.test' } });
    await vi.waitFor(() => expect(get(store.userPreferencesReady)).toBe(true));
    expect(get(store.userPreferences)).toEqual(DEFAULT_USER_PREFERENCES);
  });

  it.each(['profile', 'ABA'])('rejects stale load and save after a %s transition', async (transition) => {
    const store = await start();
    const loading = deferred(), saving = deferred();
    vi.mocked(store.api.userPreferences.get).mockReturnValueOnce(loading.promise);
    const load = store.loadUserPreferences('first@cognis.test');
    await Promise.resolve();
    vi.mocked(store.api.userPreferences.update).mockReturnValueOnce(saving.promise);
    const save = store.saveUserPreferences(prefs(false)).catch(() => undefined);
    await vi.waitFor(() => expect(store.api.userPreferences.update).toHaveBeenCalled());
    const original = environment.owner;
    environment.owner = transition === 'profile' ? 'https://other.test\nfirst@cognis.test' : null;
    environment.epoch = 'epoch-2';
    environment.listeners.forEach((listener) => listener());
    if (transition === 'ABA') {
      environment.owner = original; environment.epoch = 'epoch-3';
      environment.listeners.forEach((listener) => listener());
    }
    const { auth } = await import('$lib/stores/auth');
    // A new verified auth emission admits the replacement document lease.
    (auth as unknown as { set(value: unknown): void }).set({
      status: 'authenticated', user: { email: 'first@cognis.test' },
    });
    loading.resolve(prefs(false)); saving.resolve(prefs(false));
    await Promise.all([load, save]);
    await vi.waitFor(() => expect(get(store.userPreferences).chat.keep_assistant_messages_separate).toBe(true));
  });

  it('does not let a delayed load overwrite an optimistic save or its rollback', async () => {
    const store = await start();
    const loading = deferred(), saving = deferred();
    vi.mocked(store.api.userPreferences.get).mockReturnValueOnce(loading.promise);
    const load = store.loadUserPreferences();
    await Promise.resolve();
    vi.mocked(store.api.userPreferences.update).mockReturnValueOnce(saving.promise);
    const save = store.saveUserPreferences(prefs(false)).catch(() => undefined);
    loading.resolve(prefs(true)); await load;
    expect(get(store.userPreferences).chat.keep_assistant_messages_separate).toBe(false);
    saving.reject(new Error('Save failed')); await save;
    expect(get(store.userPreferences).chat.keep_assistant_messages_separate).toBe(true);
  });

  it('revalidates scoped storage hints, coalesces bursts, ignores payloads and does not echo unchanged values', async () => {
    const store = await start();
    const key = `cognis_user_preferences:account-v2:${encodeURIComponent(environment.owner!)}`;
    const writes = vi.spyOn(Storage.prototype, 'setItem');
    vi.mocked(store.api.userPreferences.get).mockClear();
    const emit = (eventKey: string) => window.dispatchEvent(new StorageEvent('storage', {
      key: eventKey, newValue: JSON.stringify(prefs(false)), storageArea: localStorage,
    }));
    emit('cognis_user_preferences:another-owner');
    await new Promise((done) => setTimeout(done, 5));
    expect(store.api.userPreferences.get).not.toHaveBeenCalled();
    emit(key); emit(key); emit(key);
    await vi.waitFor(() => expect(store.api.userPreferences.get).toHaveBeenCalledTimes(1));
    expect(get(store.userPreferences).chat.keep_assistant_messages_separate).toBe(true);
    expect(writes).not.toHaveBeenCalled();
    writes.mockRestore();
  });

  it('defers a live refresh during a local save and applies the server value after settlement', async () => {
    const store = await start();
    const saving = deferred();
    vi.mocked(store.api.userPreferences.update).mockReturnValueOnce(saving.promise);
    const save = store.saveUserPreferences(prefs(false));
    vi.mocked(store.api.userPreferences.get).mockClear();
    window.dispatchEvent(new StorageEvent('storage', {
      key: `cognis_user_preferences:account-v2:${encodeURIComponent(environment.owner!)}`, storageArea: localStorage,
    }));
    await new Promise((done) => setTimeout(done, 5));
    expect(store.api.userPreferences.get).not.toHaveBeenCalled();
    vi.mocked(store.api.userPreferences.get).mockResolvedValue(prefs(false));
    saving.resolve(prefs(false)); await save;
    await vi.waitFor(() => expect(store.api.userPreferences.get).toHaveBeenCalledTimes(1));
    expect(get(store.userPreferences).chat.keep_assistant_messages_separate).toBe(false);
  });

  it('serializes overlapping saves and rolls a later failure back to the earlier confirmed value and cache', async () => {
    const store = await start();
    const first = deferred(), second = deferred();
    const confirmed = prefs(false), optimistic = prefs(true);
    confirmed.chat.enter_to_send = false;
    confirmed.display.theme_family = 'gruvbox';
    vi.mocked(store.api.userPreferences.update).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const a = store.saveUserPreferences(confirmed);
    const b = store.saveUserPreferences(optimistic).catch(() => undefined);
    await vi.waitFor(() => expect(store.api.userPreferences.update).toHaveBeenCalledTimes(1));
    expect(get(store.userPreferences)).toEqual(optimistic);
    first.resolve(confirmed); await a;
    await vi.waitFor(() => expect(store.api.userPreferences.update).toHaveBeenCalledTimes(2));
    expect(get(store.userPreferences)).toEqual(optimistic);
    second.reject(new Error('Second save failed')); await b;
    expect(get(store.userPreferences)).toEqual(confirmed);
    const key = `cognis_user_preferences:account-v2:${encodeURIComponent(environment.owner!)}`;
    expect(JSON.parse(localStorage.getItem(key)!)).toEqual(confirmed);
    expect(vi.mocked(store.api.userPreferences.update).mock.calls.map(([payload]) => payload)).toEqual([confirmed, optimistic]);
  });

  it('reloads only the verified account/profile family cache', async () => {
    localStorage.setItem('cognis_user_preferences', JSON.stringify(prefs(false)));
    const key = `cognis_user_preferences:account-v2:${encodeURIComponent(environment.owner!)}`;
    const cached = prefs(true);
    cached.display.theme_family = 'gruvbox';
    localStorage.setItem(key, JSON.stringify(cached));
    const { api } = await import('$lib/api/client');
    const store = await import('./userPreferences');
    vi.mocked(api.userPreferences.get).mockReturnValue(new Promise(() => {}));
    stop = store.startUserPreferences();
    expect(get(store.userPreferences).display.theme_family).toBe('gruvbox');
    stop(); stop = undefined;
    expect(get(store.userPreferences).display.theme_family).toBe('classic');
    environment.owner = 'https://other.test\nfirst@cognis.test';
    environment.epoch = 'other-profile';
    stop = store.startUserPreferences();
    expect(get(store.userPreferences).display.theme_family).toBe('classic');
  });

  it('does not send a queued save after revocation', async () => {
    const store = await start();
    const first = deferred();
    vi.mocked(store.api.userPreferences.update).mockReturnValueOnce(first.promise);
    const a = store.saveUserPreferences(prefs(false)).catch(() => undefined);
    const b = store.saveUserPreferences(prefs(true)).catch(() => undefined);
    await vi.waitFor(() => expect(store.api.userPreferences.update).toHaveBeenCalledTimes(1));
    environment.owner = null; environment.epoch = 'revoked-epoch';
    environment.listeners.forEach((listener) => listener());
    first.resolve(prefs(false)); await Promise.all([a, b]);
    expect(store.api.userPreferences.update).toHaveBeenCalledTimes(1);
    expect(get(store.userPreferences)).toEqual(DEFAULT_USER_PREFERENCES);
  });
});
