import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { DEFAULT_USER_PREFERENCES } from '$lib/user-preferences';
import type { UserPreferences } from '$lib/types/api';

vi.mock('$app/environment', () => ({ browser: true }));
vi.mock('$lib/api/client', () => ({ api: { userPreferences: { get: vi.fn(), update: vi.fn() } } }));
vi.mock('$lib/errors', () => ({ reportError: vi.fn() }));
vi.mock('$lib/stores/auth', async () => {
  const { writable } = await import('svelte/store');
  return { auth: writable({ status: 'authenticated', user: { email: 'first@cognis.test' } }) };
});
const identity = vi.hoisted(() => ({ email: '', epoch: 0 }));
vi.mock('$lib/document-coordination', () => ({
  documentCoordination: () => ({
    capture: () => {
      const epoch = identity.epoch, email = identity.email;
      const assertCurrent = () => { if (epoch !== identity.epoch) throw new Error('Stale document'); };
      return { owner: `https://controller.test\n${email}`, epoch: String(epoch), assertCurrent,
        validate: async () => assertCurrent() };
    },
    storageName: () => cacheKey(identity.email),
  }),
}));
function cacheKey(email: string): string {
  return `cognis_user_preferences:account-v2:${encodeURIComponent(`https://controller.test\n${email}`)}`;
}
async function loadUserPreferences(email: string) {
  const store = await import('./userPreferences');
  if (email !== identity.email) { identity.email = email; identity.epoch++; }
  return store.loadUserPreferences(email);
}

function deferred() {
  let resolve!: (value: UserPreferences) => void;
  const promise = new Promise<UserPreferences>((done) => { resolve = done; });
  return { resolve, promise };
}
function preferences(collapsed: boolean): UserPreferences {
  return { ...structuredClone(DEFAULT_USER_PREFERENCES), display: {
    ...DEFAULT_USER_PREFERENCES.display, pinned_agents_collapsed: collapsed,
  } };
}
describe('account-owned display preferences', () => {
  beforeEach(() => { vi.resetModules(); vi.resetAllMocks(); localStorage.clear(); identity.email = ''; identity.epoch++; });
  it('ignores a stale owner load even when the account cycles back to the same email', async () => {
    const { api } = await import('$lib/api/client');
    const { userPreferences } = await import('./userPreferences');
    const first = deferred(), second = deferred(), latest = deferred();
    vi.mocked(api.userPreferences.get).mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise).mockReturnValueOnce(latest.promise);
    const a = loadUserPreferences('first@cognis.test');
    await vi.waitFor(() => expect(api.userPreferences.get).toHaveBeenCalledTimes(1));
    const b = loadUserPreferences('second@cognis.test');
    await vi.waitFor(() => expect(api.userPreferences.get).toHaveBeenCalledTimes(2));
    const current = loadUserPreferences('first@cognis.test');
    await vi.waitFor(() => expect(api.userPreferences.get).toHaveBeenCalledTimes(3));
    first.resolve(preferences(false)); second.resolve(preferences(false));
    await Promise.all([a, b]);
    expect(get(userPreferences).display.pinned_agents_collapsed).toBe(true);
    latest.resolve(preferences(true)); await current;
    expect(get(userPreferences).display.pinned_agents_collapsed).toBe(true);
  });
  it('does not apply a save completion to another account or its cache', async () => {
    const { api } = await import('$lib/api/client');
    const { saveUserPreferences, userPreferences } = await import('./userPreferences');
    vi.mocked(api.userPreferences.get).mockResolvedValue(preferences(true));
    await loadUserPreferences('first@cognis.test');
    const update = deferred();
    vi.mocked(api.userPreferences.update).mockReturnValue(update.promise);
    const saving = saveUserPreferences(preferences(false)).catch(() => undefined);
    await vi.waitFor(() => expect(api.userPreferences.update).toHaveBeenCalled());
    await loadUserPreferences('second@cognis.test');
    update.resolve(preferences(false)); await saving;
    expect(get(userPreferences).display.pinned_agents_collapsed).toBe(true);
    expect(JSON.parse(localStorage.getItem(cacheKey('second@cognis.test'))!).display.pinned_agents_collapsed).toBe(true);
  });
  for (const rejects of [false, true]) {
    it(`does not ${rejects ? 'roll back' : 'replace'} preferences after an A→B→A account cycle`, async () => {
      const { api } = await import('$lib/api/client');
      const { saveUserPreferences, userPreferences } = await import('./userPreferences');
      vi.mocked(api.userPreferences.get).mockResolvedValue(preferences(true));
      await loadUserPreferences('first@cognis.test');
      let resolve!: (value: UserPreferences) => void;
      let reject!: (error: Error) => void;
      vi.mocked(api.userPreferences.update).mockReturnValue(new Promise((done, fail) => { resolve = done; reject = fail; }));
      const saving = saveUserPreferences(preferences(false));
      const settled = saving.catch(() => undefined);
      await vi.waitFor(() => expect(api.userPreferences.update).toHaveBeenCalled());
      await loadUserPreferences('second@cognis.test');
      const latest = preferences(true);
      latest.display.pinned_agents_order_by_activity = false;
      vi.mocked(api.userPreferences.get).mockResolvedValueOnce(latest);
      await loadUserPreferences('first@cognis.test');
      if (rejects) reject(new Error('Preference save failed'));
      else resolve(preferences(false));
      await settled;
      expect(get(userPreferences).display.pinned_agents_collapsed).toBe(true);
      expect(get(userPreferences).display.pinned_agents_order_by_activity).toBe(false);
      expect(JSON.parse(localStorage.getItem(cacheKey('first@cognis.test'))!).display.pinned_agents_collapsed).toBe(true);
      expect(JSON.parse(localStorage.getItem(cacheKey('first@cognis.test'))!).display.pinned_agents_order_by_activity).toBe(false);
      expect(JSON.parse(localStorage.getItem(cacheKey('second@cognis.test'))!).display.pinned_agents_collapsed).toBe(true);
    });
  }
});
