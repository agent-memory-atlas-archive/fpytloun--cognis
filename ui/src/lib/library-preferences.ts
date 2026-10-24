/** Per-person browser preferences; explicit URLs always take precedence. */
export const preferenceKeys = ['kind', 'group', 'q', 'project', 'agent', 'origin', 'ownership', 'format', 'after', 'before', 'sort', 'view', 'favorites'] as const;

export function preferenceKey(email: string, projectId?: string): string {
  return `cognis.library.preferences:${JSON.stringify([email, projectId ?? null])}`;
}

export function readPreferences(storage: Storage, key: string): URLSearchParams {
  const params = new URLSearchParams();
  try {
    const saved: unknown = JSON.parse(storage.getItem(key) ?? '{}');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      for (const name of preferenceKeys) {
        const value = (saved as Record<string, unknown>)[name];
        if (typeof value === 'string' && value.length <= 200) params.set(`lib_${name}`, value);
      }
    }
  } catch { /* Storage is optional; URLs remain authoritative. */ }
  return params;
}

export function savePreferences(storage: Storage, key: string, params: URLSearchParams): void {
  const saved: Record<string, string> = {};
  for (const name of preferenceKeys) {
    const value = params.get(`lib_${name}`);
    if (value !== null) saved[name] = value;
  }
  try { storage.setItem(key, JSON.stringify(saved)); } catch { /* Browsing works without storage. */ }
}
