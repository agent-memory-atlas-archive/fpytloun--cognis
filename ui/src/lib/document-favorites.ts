import { get, writable } from 'svelte/store';
import { api } from '$lib/api/client';
import { auth } from '$lib/stores/auth';
import type { LibraryItem, LibraryKind } from '$lib/library';

export const favoriteItems = writable<Record<string, LibraryItem>>({});
export const favoriteRevision = writable(0);
const pending = new Map<string, Promise<void>>();
let user: string | undefined;
let epoch = 0;
let version = 0;
const writes = new Map<string, number>();
auth.subscribe(value => {
  if (user === value.user?.email) return;
  user = value.user?.email;
  epoch++;
  writes.clear();
  favoriteItems.set({});
  pending.clear();
});

export const favoriteKey = (kind: LibraryKind, id: string) => `${kind}:${id}`;

function remember(item: LibraryItem, readVersion = version) {
  favoriteItems.update(items => {
    const lineage = favoriteKey(item.kind, item.lineage_id || item.id);
    if ((writes.get(lineage) ?? 0) > readVersion) {
      const newer = Object.values(items).find(previous => previous.kind === item.kind
        && (previous.lineage_id || previous.id) === (item.lineage_id || item.id));
      if (newer) item = { ...item, is_favorite: newer.is_favorite };
    }
    const result = { ...items, [favoriteKey(item.kind, item.id)]: item };
    for (const [key, previous] of Object.entries(result)) {
      if (previous.kind === item.kind && (previous.lineage_id || previous.id) === (item.lineage_id || item.id)) {
        result[key] = { ...previous, is_favorite: item.is_favorite };
      }
    }
    return result;
  });
}

export async function loadFavorite(kind: LibraryKind, id: string, initial?: LibraryItem): Promise<void> {
  const key = favoriteKey(kind, id);
  if (get(favoriteItems)[key]) return;
  if (initial && typeof initial.is_favorite === 'boolean') { remember(initial, 0); return; }
  if (pending.has(key)) return pending.get(key);
  const owner = epoch, readVersion = version;
  const request = api.library.item(kind, id).then(item => {
    if (owner === epoch) remember(item, readVersion);
  }).finally(() => { if (pending.get(key) === request) pending.delete(key); });
  pending.set(key, request);
  return request;
}

export async function saveFavorite(kind: LibraryKind, id: string, favorite: boolean): Promise<void> {
  const owner = epoch;
  const item = await api.library.favorite(kind, id, favorite);
  if (owner !== epoch) return;
  writes.set(favoriteKey(kind, item.lineage_id || item.id), ++version);
  remember(item);
  favoriteRevision.update(value => value + 1);
}
