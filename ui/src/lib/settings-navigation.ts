/** Canonical settings destinations and human UI visibility. */
export const ALL_SETTINGS_TABS = [
  'providers', 'routing', 'secrets', 'notifications', 'display', 'web',
  'tools', 'executors', 'users', 'system', 'account',
] as const;
export type SettingsTab = typeof ALL_SETTINGS_TABS[number];
export const USER_SETTINGS_TABS: readonly SettingsTab[] = [
  'providers', 'secrets', 'notifications', 'display', 'tools', 'executors', 'account',
];
export function settingsTabVisible(tab: SettingsTab, admin: boolean): boolean {
  return admin || USER_SETTINGS_TABS.includes(tab);
}
