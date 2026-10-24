import { userPreferences, userPreferencesOwned } from '$lib/stores/userPreferences';
import { readStartupAppearance, rememberStartupAppearance } from './startup-appearance';
import type { UserPreferences } from '$lib/types/api';
import { DEFAULT_THEME_FAMILY, type ThemeFamily } from './catalog';

export type AppearancePreference = UserPreferences['display']['theme'];
export type ResolvedTheme = 'light' | 'dark';

export function resolveTheme(preference: AppearancePreference, systemDark: boolean): ResolvedTheme {
  return preference === 'system' ? (systemDark ? 'dark' : 'light') : preference;
}

/** Project a resolved appearance without changing account preferences. */
export function projectAppearance(family: ThemeFamily, theme: ResolvedTheme): void {
  const root = document.documentElement;
  root.dataset.themeFamily = family;
  root.dataset.resolvedTheme = theme;
  root.classList.toggle('dark', theme === 'dark');
  root.style.colorScheme = theme;
  const chrome = getComputedStyle(root).getPropertyValue('--app-chrome-bg').trim();
  for (const [name, content] of [['color-scheme', theme], ['theme-color', chrome]]) {
    let meta = document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = name;
      document.head.appendChild(meta);
    }
    meta.content = content;
  }
}

/**
 * Projection only: the preference store owns account binding, persistence and
 * rollback. Until an account first binds in this document, keep the device's
 * startup hint (what app.html already painted) instead of flashing defaults.
 * After a revocation the defaults apply; the prior account is never replayed.
 */
export function startAppearance(): () => void {
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference: AppearancePreference = 'system';
  let family: ThemeFamily = DEFAULT_THEME_FAMILY;
  let owned = false;
  let bound = false;
  const hint = readStartupAppearance();
  const apply = () => {
    if (owned) {
      bound = true;
      rememberStartupAppearance(family, preference);
    } else if (!bound && hint) {
      const mode = resolveTheme(hint.theme, system.matches);
      projectAppearance(hint[mode].family, mode);
      return;
    }
    projectAppearance(family, resolveTheme(preference, system.matches));
  };
  system.addEventListener('change', apply);
  const stopPreferences = userPreferences.subscribe((value) => {
    preference = value.display.theme;
    family = value.display.theme_family;
    apply();
  });
  const stopOwned = userPreferencesOwned.subscribe((value) => {
    owned = value;
    apply();
  });
  return () => {
    stopPreferences();
    stopOwned();
    system.removeEventListener('change', apply);
  };
}
