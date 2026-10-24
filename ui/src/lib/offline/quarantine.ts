import { writable } from 'svelte/store';

export const retainedDataNotice = writable(false);
const MARKER = 'cognis-retained-unowned:v2';

/**
 * Migration by namespace isolation: original DBs/keys are never rewritten,
 * copied, attributed, or deleted. A crash before the notice is harmless; all
 * new owners exclusively use account-v2 namespaces, even without this marker.
 */
export async function inspectRetainedData(storage: Storage = localStorage, factory = indexedDB): Promise<void> {
  const previous = storage.getItem(MARKER);
  if (previous === 'retained') { retainedDataNotice.set(true); return; }
  let retained = false;
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i) ?? '';
    if (!key.includes(':account-v2:') && /cognis.*(?:draft|unsent)/i.test(key)) retained = true;
  }
  if (typeof factory.databases === 'function') {
    const names = await factory.databases();
    retained ||= names.some(({ name }) => name === 'cognis-chat-v2' || name === 'cognis-chat-v2-uploads');
  } else {
    // Do not open/create a legacy database just to discover its contents.
    retained = true;
  }
  if (retained) storage.setItem(MARKER, 'retained');
  retainedDataNotice.set(retained);
}
