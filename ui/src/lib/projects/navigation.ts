const tabs = new Set(['overview', 'conversations', 'tasks', 'schedules', 'agents', 'resources', 'knowledge', 'settings', 'sharing']);
const key = (email: string) => `cognis.projects.lastOpened:${email}`;

/** Store only project identity and tab, never arbitrary URLs or modal contents. */
export function rememberProject(email: string | undefined, projectId: string, tab: string | null): void {
  if (!email) return;
  try {
    localStorage.setItem(key(email), JSON.stringify({ projectId, tab: tabs.has(tab ?? '') ? tab : 'overview' }));
  } catch { /* Navigation remains available when client storage is disabled. */ }
}

export function lastProjectUrl(email: string | undefined, availableIds: string[]): string | null {
  if (!email) return null;
  try {
    const raw = localStorage.getItem(key(email));
    if (!raw) return null;
    const saved = JSON.parse(raw);
    if (!saved || typeof saved.projectId !== 'string' || !availableIds.includes(saved.projectId)) {
      localStorage.removeItem(key(email));
      return null;
    }
    const tab = tabs.has(saved.tab) ? saved.tab : 'overview';
    return `/projects/${encodeURIComponent(saved.projectId)}?tab=${tab}`;
  } catch { return null; }
}
