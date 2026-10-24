// @vitest-environment node
import { readFileSync } from 'node:fs';
import postcss from 'postcss';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';

const mainRoles = 'canvas chrome surface inset elevated surface-hover foreground secondary muted separator control-border border-strong accent accent-hover on-accent accent-subtle'.split(' ');
function expandImports(url: URL): string {
  const root = postcss.parse(readFileSync(url, 'utf8'));
  root.walkAtRules('import', (rule) => {
    const path = rule.params.match(/^['"]([^'"]+)['"]$/)![1];
    rule.replaceWith(postcss.parse(expandImports(new URL(path, url))).nodes);
  });
  return root.toString();
}
const css = expandImports(new URL('./tokens.css', import.meta.url));
let browser: Browser;
let page: Page;
beforeAll(async () => {
  browser = await chromium.launch();
  page = await browser.newPage();
  await page.setContent(`<style>${css}</style><div class="theme-palette" id="local"></div>`);
});
afterAll(async () => { await browser?.close(); });
async function values(family: string, mode: string, local = false) {
  return page.evaluate(({ family, mode, local }) => {
    const root = document.documentElement;
    root.dataset.themeFamily = family;
    root.dataset.resolvedTheme = local ? (mode === 'light' ? 'dark' : 'light') : mode;
    const scope = local ? document.getElementById('local')! : root;
    scope.dataset.themeFamily = family;
    scope.dataset.resolvedTheme = mode;
    const style = getComputedStyle(scope);
    return Object.fromEntries(Array.from(style).filter((role) => role.startsWith('--'))
      .map((role) => [role, style.getPropertyValue(role).trim()]));
  }, { family, mode, local });
}
const cases = [
  // Explicit local-review intent, not a claim of approved-preset fidelity.
  ['classic', 'light', 'f8fafc e9eef4 ffffff f1f5f9 ffffff e2e8f0 0f172a 334155 5a687c e2e8f0 cbd5e1 64748b 036f9f 035a82 ffffff e4f0fa'],
  // Restored pre-theme shades: slate-950 sheets, slate-200 text, slate-400
  // strong borders; the accent tint is sky-500 at palette-owned 10% opacity.
  ['classic', 'dark', '020617 07111a 0f172a 020617 020617 1e293b e2e8f0 cbd5e1 94a3b8 1e293b 334155 94a3b8 0ea5e9 38bdf8 020617 0ea5e9'],
  ['porcelain', 'light', 'f9f9fa ececed ffffff f3f3f4 ffffff e5e6e7 18191a 424344 606162 e4e4e5 d4d4d5 969798 176a55 10513f ffffff e2e6e4'],
  ['porcelain', 'dark', '111213 18191a 222324 151617 2a2b2c 323334 eeeff0 c1c2c3 a2a3a4 3b3c3d 68696a a2a3a4 77be9f 93d1b5 111814 2b302d'],
  ['gruvbox', 'light', 'fbf1c7 f2e5bc f4e8be f2e5bc f2e5bc eee0b7 654735 4f3829 7c6f64 e5d5ad 7c6f64 654735 45707a 654735 fbf1c7 dadec0'],
  ['gruvbox', 'dark', '282828 1b1b1b 32302f 1b1b1b 32302f 45403d d4be98 ddc7a1 a89984 45403d a89984 d4be98 a9b665 89b482 282828 3b4439'],
  ['paper', 'light', 'faf9f5 efede6 ffffff f3f1ec ffffff e9e7e0 131313 383835 66645e e6e3da d6d2c7 969288 9b4c32 783923 ffffff eeece6'],
  ['paper', 'dark', '262624 1f1e1d 30302e 141413 30302e 3e3e39 faf9f5 c2bfb6 b2aea2 41413b 77756b b2aea2 ebaa90 f2c2ad 29211d 393933'],
];
describe('local review palette intent and unchanged Gruvbox fidelity', () => {
  it('restores original Classic context-specific alpha rather than opaque category substitutes', async () => {
    const palette = await values('classic', 'dark');
    const expected = {
      '--compaction-info-bg': 'rgb(6 182 212 / .1)',
      '--compaction-info-border': 'rgb(6 182 212 / .3)',
      '--compaction-info-fg': 'rgb(207 250 254)',
      '--helper-managed-bg': 'rgb(139 92 246 / .05)',
      '--helper-managed-border': 'rgb(167 139 250 / .25)',
      '--helper-error-bg': 'rgb(244 63 94 / .05)',
      '--helper-error-border': 'rgb(244 63 94 / .3)',
      '--recap-bg': 'rgb(15 23 42 / .9)',
      '--recap-border': 'rgb(14 165 233 / .25)',
    };
    const scoped = await values('classic', 'dark', true);
    for (const [role, value] of Object.entries(expected)) {
      expect(palette[role]).toBe(value);
      expect(scoped[role]).toBe(value);
    }
    const actual = await page.evaluate(() => {
      const roles = ['compaction-info-bg', 'helper-managed-bg', 'helper-error-bg', 'recap-border'];
      return roles.map((role) => {
        const node = document.createElement('div');
        node.style.background = `var(--${role})`;
        document.getElementById('local')!.append(node);
        const color = getComputedStyle(node).backgroundColor;
        node.remove();
        return color;
      });
    });
    expect(actual).toEqual(['rgba(6, 182, 212, 0.1)', 'rgba(139, 92, 246, 0.05)', 'rgba(244, 63, 94, 0.05)', 'rgba(14, 165, 233, 0.25)']);
  });

  it.each(['light', 'dark'] as const)('uses Classic for the attribute-less %s CSS boot state', async (mode) => {
    await page.emulateMedia({ colorScheme: mode });
    const color = await page.evaluate(() => {
      const root = document.documentElement;
      delete root.dataset.themeFamily;
      delete root.dataset.resolvedTheme;
      const style = getComputedStyle(root);
      return [style.getPropertyValue('--color-canvas').trim(), style.getPropertyValue('--app-chrome-bg').trim()];
    });
    expect(color).toEqual(mode === 'light' ? ['248 250 252', '#e9eef4'] : ['2 6 23', '#07111a']);
    await page.emulateMedia({ colorScheme: 'light' });
  });
  it.each([
    ['paper', 'light', '32 32 31'], ['paper', 'dark', '20 19 18'],
    ['porcelain', 'light', '24 25 26'], ['porcelain', 'dark', '12 13 14'],
    ['gruvbox', 'light', '242 229 188'], ['gruvbox', 'dark', '27 27 27'],
  ])('%s %s owns a non-navy scrim in root and opposite reader scope', async (family, mode, expected) => {
    const root = await values(family, mode);
    const scope = await values(family, mode, true);
    expect(root['--color-scrim']).toBe(expected);
    expect(scope['--color-scrim']).toBe(expected);
    const composite = expected.split(' ').map(Number).map((c, index) =>
      Math.round(c * .8 + Number(root['--color-canvas'].split(' ')[index]) * .2));
    if (family === 'paper') expect(Math.max(...composite) - Math.min(...composite)).toBeLessThanOrEqual(3);
  });
  it.each(['light', 'dark'])('keeps Porcelain %s neutral at root and local scopes', async (mode) => {
    for (const local of [false, true]) {
      const palette = await values('porcelain', mode, local);
      for (const role of mainRoles.slice(0, 12)) {
        const channels = palette[`--color-${role}`].split(' ').map(Number);
        expect(Math.max(...channels) - Math.min(...channels), role).toBeLessThanOrEqual(2);
      }
    }
  });
  it.each(['keyword', 'string', 'number', 'comment', 'title', 'punctuation'])(
    'keeps Gruvbox Light syntax %s readable on its unchanged code inset', async (role) => {
      const palette = await values('gruvbox', 'light');
      const scoped = await values('gruvbox', 'light', true);
      expect(scoped[`--color-syntax-${role}`]).toBe(palette[`--color-syntax-${role}`]);
      const luminance = (channels: string) => channels.split(' ').map(Number)
        .map((c) => c / 255).map((c) => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
        .reduce((sum, c, index) => sum + c * [0.2126, 0.7152, 0.0722][index], 0);
      expect(palette['--color-inset']).toBe('242 229 188');
      const pair = [luminance(palette[`--color-syntax-${role}`]), luminance(palette['--color-inset'])]
        .sort((a, b) => b - a);
      expect((pair[0] + 0.05) / (pair[1] + 0.05)).toBeGreaterThanOrEqual(4.5);
    },
  );

  it.each(cases)('%s %s keeps approved main roles, including original yellow Gruvbox', async (family, mode, hex) => {
    const palette = await values(family, mode);
    const scoped = await values(family, mode, true);
    expect(mainRoles.map((role) => scoped[`--color-${role}`])).toEqual(mainRoles.map((role) => palette[`--color-${role}`]));
    const expected = hex.split(' ').map((hex) => hex.match(/../g)!.map((channel) => parseInt(channel, 16)).join(' '));
    expect(mainRoles.map((role) => palette[`--color-${role}`])).toEqual(expected);
    expect(palette['--app-chrome-bg']).toBe(`#${hex.split(' ')[1]}`);
  });

  it('keeps Paper message contrast independent of the clay action color', () => {
    expect(css).toContain('--message-user-bg: rgb(var(--color-accent-subtle))');
    expect(css).toContain('--message-user-fg: rgb(var(--color-foreground))');
    expect(css).toContain('--message-assistant-bg: transparent');
  });
});
