import { expect, test } from '@playwright/test';

for (const width of [390, 1440]) {
  for (const theme of ['light', 'dark']) {
    test(`all-element surface and sibling rhythm ${theme} ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.goto(`/rich-deliverable-fixture?scenario=every-block-reference&surface=standalone&capture=viewer&theme=${theme}&width=${width}`);
      const viewer = page.getByTestId('rich-deliverable');
      await expect(viewer).toHaveAttribute('data-viewer-theme', theme);
      await page.evaluate(() => document.fonts.ready);

      const surfaces = viewer.locator('.rich-chart-card, .rich-timeline-card, .rich-callout, .rich-dashboard, .rich-incident');
      expect(await surfaces.count()).toBeGreaterThan(3);
      for (const surface of await surfaces.all()) {
        await expect(surface).toHaveCSS('background-image', 'none');
        await expect(surface).toHaveCSS('box-shadow', 'none');
      }
      const gaps = await viewer.locator('.rich-block-list').evaluateAll(lists =>
        lists.flatMap(list => {
          if (getComputedStyle(list).display !== 'flex') return [];
          const children = Array.from(list.children).filter(child =>
            child.classList.contains('rich-block-anchor') && child.getBoundingClientRect().height > 0,
          );
          return children.slice(1).map((child, i) =>
            child.getBoundingClientRect().top - children[i].getBoundingClientRect().bottom,
          );
        }),
      );
      expect(gaps.length).toBeGreaterThan(10);
      expect(gaps.every(gap => gap >= 23)).toBe(true);
      expect(await viewer.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      if (width <= 600) {
        const body = await viewer.locator('.rich-body').first().boundingBox();
        expect(body).not.toBeNull();
        expect(body!.x).toBeCloseTo(16, 0);
        expect(body!.width).toBeCloseTo(width - 32, 0);
      }
      await page.screenshot({ path: `/tmp/rich-elements-${theme}-${width}.png` });
      for (const [name, selector] of Object.entries({
        chart: '.rich-chart-card',
        timeline: '.rich-timeline',
        callout: '.rich-callout',
      })) {
        const element = viewer.locator(selector).first();
        await element.scrollIntoViewIfNeeded();
        await page.screenshot({ path: `/tmp/rich-elements-${name}-${theme}-${width}.png` });
      }
    });
  }
}
