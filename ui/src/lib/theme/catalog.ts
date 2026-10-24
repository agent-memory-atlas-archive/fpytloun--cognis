export const THEME_FAMILIES = [
  { id: 'porcelain', name: 'Porcelain', description: 'Refined neutral surfaces.' },
  { id: 'classic', name: 'Classic', description: 'Source-restored Cognis colors. The default theme.' },
  { id: 'gruvbox', name: 'Gruvbox', description: 'Original yellow light surfaces and Material dark colors.' },
  { id: 'paper', name: 'Paper', description: 'Claude-inspired light and dark surfaces with compact chat.' }
] as const;

export type ThemeFamily = (typeof THEME_FAMILIES)[number]['id'];
export const DEFAULT_THEME_FAMILY: ThemeFamily = 'classic';

export function normalizeThemeFamily(value: unknown): ThemeFamily {
  return THEME_FAMILIES.find((family) => family.id === value)?.id ?? DEFAULT_THEME_FAMILY;
}
