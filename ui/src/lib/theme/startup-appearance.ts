import type { AppearancePreference, ResolvedTheme } from './appearance';
import { THEME_FAMILIES, type ThemeFamily } from './catalog';

/**
 * Device-local hint so the pre-bootstrap loading screen in app.html paints the
 * last verified account appearance instead of the Classic default. It is a
 * cosmetic projection only: account preferences remain the source of truth
 * and replace it as soon as they bind. Explicit logout removes it.
 *
 * The boot script runs before application CSS loads, so the hint carries the
 * literal startup colors for both modes (System follows the OS at launch).
 * app.html validates this exact shape; keep them in sync.
 */
export const STARTUP_APPEARANCE_KEY = 'cognis-startup-appearance';

export interface StartupPalette {
  family: ThemeFamily;
  chrome: string;
  bg: string;
  surface: string;
  text: string;
  border: string;
  accent: string;
  onAccent: string;
}

export interface StartupAppearance {
  v: 1;
  theme: AppearancePreference;
  light: StartupPalette;
  dark: StartupPalette;
}

const ROLES = {
  bg: '--color-chrome',
  surface: '--color-surface',
  text: '--color-foreground',
  border: '--color-control-border',
  accent: '--color-accent',
  onAccent: '--color-on-accent'
} as const;
const CHANNELS = /^\d{1,3} \d{1,3} \d{1,3}$/;
const HEX = /^#[0-9a-f]{6}$/i;

function measure(family: ThemeFamily, mode: ResolvedTheme): StartupPalette | null {
  const probe = document.createElement('div');
  probe.hidden = true;
  probe.dataset.themeFamily = family;
  probe.dataset.resolvedTheme = mode;
  document.documentElement.appendChild(probe);
  try {
    const style = getComputedStyle(probe);
    const read = (name: string) => style.getPropertyValue(name).trim();
    const chrome = read('--app-chrome-bg');
    const palette = { family, chrome } as StartupPalette;
    for (const [key, role] of Object.entries(ROLES)) {
      const value = read(role);
      if (!CHANNELS.test(value)) return null;
      palette[key as keyof typeof ROLES] = value;
    }
    return HEX.test(chrome) ? palette : null;
  } finally {
    probe.remove();
  }
}

/** Record the verified account appearance for the next cold start. */
export function rememberStartupAppearance(family: ThemeFamily, theme: AppearancePreference): void {
  try {
    const light = measure(family, 'light');
    const dark = measure(family, 'dark');
    if (!light || !dark) return;
    const serialized = JSON.stringify({ v: 1, theme, light, dark } satisfies StartupAppearance);
    if (localStorage.getItem(STARTUP_APPEARANCE_KEY) !== serialized) {
      localStorage.setItem(STARTUP_APPEARANCE_KEY, serialized);
    }
  } catch {
    // Storage unavailable: startup keeps the Classic/OS default.
  }
}

export function readStartupAppearance(): StartupAppearance | null {
  try {
    const value = JSON.parse(localStorage.getItem(STARTUP_APPEARANCE_KEY) || 'null') as StartupAppearance | null;
    const valid = (palette: StartupPalette | undefined) => !!palette && HEX.test(palette.chrome)
      && THEME_FAMILIES.some((family) => family.id === palette.family) && Object.keys(ROLES).every((key) => CHANNELS.test(palette[key as keyof typeof ROLES]));
    if (value?.v !== 1 || !['system', 'light', 'dark'].includes(value.theme) || !valid(value.light) || !valid(value.dark)) return null;
    return value;
  } catch {
    return null;
  }
}

export function forgetStartupAppearance(): void {
  try {
    localStorage.removeItem(STARTUP_APPEARANCE_KEY);
  } catch {
    // non-fatal
  }
}
