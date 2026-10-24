// Small on-device log of user-visible loading paths (sidebar source, chat
// switch refresh path and timing). Kept in localStorage so it can be read on
// a phone after a session (Settings → Offline data → Loading diagnostics).

export interface PerfLogEntry {
  at: number;
  kind: 'sidebar' | 'switch' | 'send';
  /** sidebar: memory | device | network; switch: sync | snapshot | cache-hit | error */
  path: string;
  ms: number;
  detail?: string;
}

const STORAGE_KEY = 'cognis-perf-log';
const MAX_ENTRIES = 60;

export function recordPerf(entry: Omit<PerfLogEntry, 'at'>): void {
  if (typeof window === 'undefined') return;
  try {
    const entries = readPerfLog();
    entries.push({ ...entry, ms: Math.round(entry.ms), at: Date.now() });
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(-MAX_ENTRIES)));
  } catch {
    // Diagnostics are best effort.
  }
}

export function readPerfLog(): PerfLogEntry[] {
  if (typeof window === 'undefined') return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '[]');
    return Array.isArray(parsed) ? (parsed as PerfLogEntry[]) : [];
  } catch {
    return [];
  }
}

export function clearPerfLog(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
