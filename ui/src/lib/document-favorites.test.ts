import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get, type Writable } from 'svelte/store';
import { auth } from '$lib/stores/auth';
import { favoriteItems, loadFavorite, saveFavorite } from './document-favorites';
import type { LibraryItem } from './library';

const mocks = vi.hoisted(() => ({ item: vi.fn(), favorite: vi.fn() }));
vi.mock('$lib/api/client', () => ({ api: { library: mocks } }));
vi.mock('$lib/stores/auth', async () => {
  const { writable } = await import('svelte/store');
  return { auth: writable({ user: null }) };
});
function login(email: string) {
  (auth as unknown as Writable<{ user: { email: string } }>).set({ user: { email } });
}
const item = (id: string, favorite: boolean): LibraryItem => ({
  id, kind: 'artifact', lineage_id: 'art_root', is_favorite: favorite,
} as LibraryItem);
describe('Personal document favorite state', () => {
  beforeEach(() => { login('reset@test.local'); login('owner@test.local'); vi.clearAllMocks(); });
  it('deduplicates initial reads and synchronizes revisions after a write', async () => {
    mocks.item.mockResolvedValue(item('art_root', false));
    await Promise.all([loadFavorite('artifact', 'art_root'), loadFavorite('artifact', 'art_root')]);
    expect(mocks.item).toHaveBeenCalledTimes(1);
    await loadFavorite('artifact', 'art_revision', item('art_revision', false));
    mocks.favorite.mockResolvedValue(item('art_revision', true));
    await saveFavorite('artifact', 'art_revision', true);
    expect(get(favoriteItems)['artifact:art_root'].is_favorite).toBe(true);
    expect(get(favoriteItems)['artifact:art_revision'].is_favorite).toBe(true);
  });
  it('ignores a late read from an older revision after the user stars the lineage', async () => {
    let resolve!: (value: LibraryItem) => void;
    mocks.item.mockReturnValue(new Promise<LibraryItem>(done => { resolve = done; }));
    const reading = loadFavorite('artifact', 'art_root');
    await loadFavorite('artifact', 'art_revision', item('art_revision', false));
    mocks.favorite.mockResolvedValue(item('art_revision', true));
    await saveFavorite('artifact', 'art_revision', true);
    resolve(item('art_root', false));
    await reading;
    expect(get(favoriteItems)['artifact:art_root'].is_favorite).toBe(true);
  });
  it('does not leak late responses after logout and login to the same account', async () => {
    let resolve!: (value: LibraryItem) => void;
    mocks.item.mockReturnValue(new Promise<LibraryItem>(done => { resolve = done; }));
    const reading = loadFavorite('artifact', 'art_root');
    login('another@test.local');
    login('owner@test.local');
    resolve(item('art_root', true));
    await reading;
    expect(get(favoriteItems)).toEqual({});
  });
  it('keeps the last confirmed state when a write fails', async () => {
    await loadFavorite('artifact', 'art_root', item('art_root', false));
    mocks.favorite.mockRejectedValue(new Error('Network failed'));
    await expect(saveFavorite('artifact', 'art_root', true)).rejects.toThrow('Network failed');
    expect(get(favoriteItems)['artifact:art_root'].is_favorite).toBe(false);
  });
  it('does not let stale list metadata overwrite a confirmed lineage write', async () => {
    await loadFavorite('artifact', 'art_root', item('art_root', false));
    mocks.favorite.mockResolvedValue(item('art_root', true));
    await saveFavorite('artifact', 'art_root', true);
    await loadFavorite('artifact', 'art_revision', item('art_revision', false));
    expect(get(favoriteItems)['artifact:art_root'].is_favorite).toBe(true);
    expect(get(favoriteItems)['artifact:art_revision'].is_favorite).toBe(true);
  });
});
