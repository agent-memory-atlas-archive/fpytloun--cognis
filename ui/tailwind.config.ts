import type { Config } from 'tailwindcss';
import typography from '@tailwindcss/typography';

const tints = ['success', 'warning', 'danger', 'info', 'violet', 'cyan', 'pink', 'orange', 'indigo', 'teal', 'lime', 'purple', 'blue', 'fuchsia'];
// Tinted fills and borders accept an optional palette-owned opacity so a
// palette can reproduce translucent originals (Classic Dark 500/10, 500/30)
// while every other palette keeps opaque values.
const translucent = new Set(['accent-subtle', ...tints.flatMap((tone) => [`${tone}-subtle`, `${tone}-border`])]);
const roles = [
  'canvas', 'chrome', 'surface', 'inset', 'raised', 'elevated', 'surface-hover',
  'foreground', 'strong', 'secondary', 'muted', 'quiet', 'separator', 'control-border', 'border-strong',
  'accent', 'accent-hover', 'on-accent', 'accent-subtle', 'scrim',
  ...['success', 'warning', 'danger', 'info'].flatMap((tone) => [tone, `${tone}-subtle`, `${tone}-border`]),
  ...['violet', 'cyan', 'pink', 'orange', 'indigo', 'teal', 'lime', 'purple', 'blue', 'fuchsia']
    .flatMap((tone) => [`${tone}-tone`, `${tone}-subtle`, `${tone}-border`]),
  ...['keyword', 'string', 'number', 'comment', 'title', 'punctuation'].map((role) => `syntax-${role}`)
];
// Text can need a lighter shade than the fill of the same role (Classic Dark
// used sky-300 text with sky-500 buttons). Palettes may set --text-<role>.
const textRoles = ['accent', 'accent-hover', 'success', 'warning', 'danger', 'info'];
const color = (role: string) => translucent.has(role)
  ? `rgb(var(--color-${role}) / calc(<alpha-value> * var(--alpha-${role}, 1)))`
  : `rgb(var(--color-${role}) / <alpha-value>)`;

const config: Config = {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: Object.fromEntries(roles.map((role) => [role, color(role)])),
      textColor: Object.fromEntries(textRoles.map((role) => [role, `rgb(var(--text-${role}, var(--color-${role})) / <alpha-value>)`])),
      boxShadow: {
        card: 'var(--shadow-card)',
        overlay: 'var(--shadow-overlay)'
      }
    }
  },
  plugins: [typography]
};

export default config;
