import { expect, test } from '@playwright/test';

for (const scenario of [
  { id: 'design-document-legacy', selector: '.rich-markdown pre code' },
  { id: 'every-block-reference', selector: '.rich-code code' },
]) {
  for (const theme of ['light', 'dark'] as const) {
    test(`${scenario.id} syntax contrasts in ${theme} viewer with opposite app`, async ({ page }) => {
      await page.goto(`/rich-deliverable-fixture?scenario=${scenario.id}&surface=standalone&capture=viewer&theme=${theme}`);
      const code = page.locator(scenario.selector).first();
      await code.scrollIntoViewIfNeeded();
      await expect(code.locator('[class*="hljs-"]').first()).toBeAttached();
      const colors = () => code.evaluate(node => {
        const rgb = (value: string) => value.match(/[\d.]+/g)!.slice(0, 3).map(Number);
        const luminance = (value: string) => rgb(value).map(v => {
          const c = v / 255;
          return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4;
        }).reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
        const background = getComputedStyle(node.parentElement!).backgroundColor;
        const foreground = [node, ...node.querySelectorAll('[class*="hljs-"]')]
          .map(element => getComputedStyle(element).color);
        return { background, foreground, contrasts: foreground.map(color => {
          const a = luminance(color), b = luminance(background);
          return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
        }) };
      });
      const before = await colors();
      await page.evaluate(value => document.documentElement.setAttribute('data-resolved-theme', value), theme === 'light' ? 'dark' : 'light');
      const after = await colors();
      expect(after).toEqual(before);
      for (const contrast of after.contrasts) expect(contrast).toBeGreaterThanOrEqual(4.5);
    });
  }
}
