// @vitest-environment node
import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import postcss from 'postcss';
import tailwind from 'tailwindcss';
import config from '../../../tailwind.config';

const css = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8');
const root = postcss.parse(css);
function palette(dark: boolean): Record<string, string> {
  const values: Record<string, string> = {};
  root.walkRules((rule) => {
    if (rule.parent?.type !== 'root') return;
    if (rule.selector !== ':where(:root, [data-theme-family][data-resolved-theme])'
      && !(dark && rule.selector === ":where([data-theme-family])[data-resolved-theme='dark']")
      ) return;
    rule.walkDecls((decl) => { values[decl.prop] = decl.value; });
  });
  return values;
}
function channels(values: Record<string, string>, role: string): number[] {
  let value = values[`--color-${role}`];
  while (value.startsWith('var(')) value = values[value.slice(4, -1)];
  return value.split(' ').map(Number);
}
function luminance(color: number[]): number {
  return color.map((c) => c / 255).map((c) => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
    .reduce((sum, c, index) => sum + c * [0.2126, 0.7152, 0.0722][index], 0);
}
function contrast(values: Record<string, string>, a: string, b: string): number {
  const pair = [luminance(channels(values, a)), luminance(channels(values, b))].sort((a, b) => b - a);
  return (pair[0] + 0.05) / (pair[1] + 0.05);
}
const hues = ['violet', 'cyan', 'pink', 'orange', 'indigo', 'teal', 'lime', 'purple', 'blue', 'fuchsia'];
describe('semantic color contracts', () => {
  it.each([
    [false, '61274e0f7f45489939b1f906bad35346af7d508b9fb31700415e724ffa4e0d15'],
    [true, 'ca33745ece926d98583dd0da8ebe8c6b5938a63a9a37931e49e4da58987b7b33'],
  ] as const)('keeps every original Classic color declaration byte-equivalent (dark=%s)', (dark, fingerprint) => {
    // Fingerprints of all --color-* and --app-chrome-bg declarations at the
    // accepted semantic-theme base 50f20b7a, before family presentation changes.
    // quiet/strong/raised were added later as pure aliases of existing roles.
    const aliases = ['--color-quiet', '--color-strong', '--color-raised'];
    const colors = Object.entries(palette(dark))
      .filter(([role]) => (role.startsWith('--color-') || role === '--app-chrome-bg') && !aliases.includes(role)).sort();
    expect(createHash('sha256').update(JSON.stringify(colors)).digest('hex')).toBe(fingerprint);
  });

  it.each([false, true])('preserves Classic accessible opaque text, syntax and tone pairings (dark=%s)', (dark) => {
    const values = palette(dark);
    const text = ['foreground', 'secondary', 'muted', 'accent', 'accent-hover',
      'success', 'warning', 'danger', 'info', ...hues.map((hue) => `${hue}-tone`),
      ...['keyword', 'string', 'number', 'comment', 'title', 'punctuation'].map((role) => `syntax-${role}`)];
    for (const role of text) {
      for (const background of ['canvas', 'chrome', 'surface', 'inset', 'elevated', 'surface-hover']) {
        expect.soft(contrast(values, role, background), `${role} on ${background} (dark=${dark})`).toBeGreaterThanOrEqual(4.5);
      }
    }
    for (const hue of hues) expect(contrast(values, `${hue}-tone`, `${hue}-subtle`), hue).toBeGreaterThanOrEqual(4.5);
    for (const tone of ['success', 'warning', 'danger', 'info']) {
      expect(contrast(values, tone, `${tone}-subtle`), tone).toBeGreaterThanOrEqual(4.5);
    }
    for (const fill of ['accent', 'accent-hover']) {
      expect(contrast(values, 'on-accent', fill), fill).toBeGreaterThanOrEqual(4.5);
    }
    expect(values['--app-chrome-bg']).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('generates opacity-compatible colors and state variants without replacing native palettes', async () => {
    const result = await postcss([tailwind({
      ...config, content: [{ raw: 'bg-surface/80 text-foreground hover:bg-surface-hover border-violet-border/40 text-violet-tone bg-violet-subtle focus-visible:ring-accent bg-slate-950', extension: 'html' }]
    })]).process('@tailwind utilities;', { from: undefined });
    expect(result.css).toContain('rgb(var(--color-surface) / 0.8)');
    // Tinted roles multiply utility opacity by the palette-owned opacity.
    expect(result.css).toContain('rgb(var(--color-violet-border) / calc(0.4 * var(--alpha-violet-border, 1)))');
    expect(result.css).toContain('--color-surface-hover');
    expect(result.css).toContain('--color-accent');
    expect(result.css).toContain('2 6 23');
  });

  it('ships system-qualified light and dark PWA launch images', () => {
    const html = readFileSync(new URL('../../app.html', import.meta.url), 'utf8');
    const links = [...html.matchAll(/href="(\/pwa\/apple-splash[^"]+)"\s+media="([^"]+)"/g)];
    expect(links).toHaveLength(22);
    for (const [, path, media] of links) {
      expect(media).toContain(`prefers-color-scheme: ${path.includes('light-') ? 'light' : 'dark'}`);
      expect(existsSync(new URL(`../../../static${path}`, import.meta.url))).toBe(true);
    }
  });
});
