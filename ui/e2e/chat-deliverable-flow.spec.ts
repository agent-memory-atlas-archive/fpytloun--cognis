import { expect, test } from '@playwright/test';

for (const family of ['classic', 'paper'] as const) {
  for (const mode of ['light', 'dark'] as const) {
    test(`${family} ${mode} chat deliverable`, async ({ page }) => {
      await page.setViewportSize({ width: 1200, height: 1200 });
      await page.emulateMedia({ colorScheme: mode, reducedMotion: 'reduce' });
      await page.goto('/chat-deliverable-fixture');
      await expect(page.getByText('Queued messages delivered once')).toBeVisible();
      await page.evaluate(({ family, mode }) => {
        document.documentElement.dataset.themeFamily = family;
        document.documentElement.dataset.resolvedTheme = mode;
        document.documentElement.classList.toggle('dark', mode === 'dark');
      }, { family, mode });
      await expect(page.getByTestId('rich-deliverable')).toHaveAttribute('data-theme-family', family);
      await page.evaluate(() => document.fonts.ready);
      await page.getByTestId('chat-deliverable-preview').screenshot({
        path: `/tmp/chat-deliverable-after-${family}-${mode}.png`,
        animations: 'disabled',
      });
      const rich = page.getByTestId('rich-deliverable');
      const styles = await rich.evaluate(element => {
        const style = getComputedStyle(element);
        const prose = getComputedStyle(element.querySelector('.rich-markdown')!);
        const assistant = getComputedStyle(document.querySelector('.chat-markdown')!);
        return {
          background: style.backgroundColor, border: style.borderTopWidth,
          prose: [prose.fontFamily, prose.fontSize, prose.color],
          assistant: [assistant.fontFamily, assistant.fontSize, assistant.color],
          left: element.querySelector('.rich-markdown')!.getBoundingClientRect().left,
          assistantLeft: document.querySelector('.chat-markdown')!.getBoundingClientRect().left,
          overflow: element.scrollWidth > element.clientWidth,
        };
      });
      expect(styles.background).toBe('rgba(0, 0, 0, 0)');
      expect(styles.border).toBe('0px');
      expect(styles.prose).toEqual(styles.assistant);
      expect(Math.abs(styles.left - styles.assistantLeft)).toBeLessThan(1);
      expect(styles.overflow).toBe(false);
      const footer = page.getByTestId('chat-document-footer');
      expect(await footer.evaluate(element => element.previousElementSibling?.classList.contains('rich-inline-document'))).toBe(true);
      const actions = footer.getByRole('navigation', { name: 'Document actions' });
      expect(Math.abs((await actions.boundingBox())!.x + (await actions.boundingBox())!.width - (await rich.boundingBox())!.x - (await rich.boundingBox())!.width)).toBeLessThan(1);
      await expect(actions.getByRole('button', { name: 'Open fullscreen' })).toHaveText('');
      await expect(actions.getByRole('button', { name: 'Share public link' })).toBeVisible();
      await expect(footer.getByRole('link', { name: 'Open in Library ↗' })).toHaveCount(0);
      await footer.getByTitle('More document actions').click();
      await expect(footer.getByRole('button', { name: 'Copy document' })).toBeVisible();
      await expect(footer.getByRole('link', { name: 'Open in Library ↗' })).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(footer.getByTitle('More document actions')).toBeFocused();
      await footer.getByRole('button', { name: 'Open fullscreen' }).click();
      const full = page.getByTestId('rich-deliverable-full-view');
      await expect(full.getByTestId('rich-viewer-chrome')).toBeVisible();
      await expect(full).not.toHaveClass(/conversational/);
      await full.getByRole('button', { name: 'Close', exact: true }).click();
      await expect(rich.getByRole('heading', { name: 'Release readiness' })).toHaveCount(1);
    });
  }
}

test('chat document actions and tables remain contained on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/chat-deliverable-fixture');
  await expect(page.getByTestId('chat-document-footer')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByTitle('Download document').click();
  await expect(page.getByRole('link', { name: 'PDF', exact: true })).toBeVisible();
});

test('chat contents uses a collapsible area sidebar and adapts to host width', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto('/chat-deliverable-fixture?wide');
  const inline = page.getByTestId('rich-deliverable-inline-document');
  await expect(inline).toHaveClass(/inline-toc-sidebar/);
  const sidebar = inline.locator('aside[aria-label="Table of contents"]');
  const body = inline.getByTestId('rich-deliverable-body');
  expect((await sidebar.boundingBox())!.x).toBeGreaterThan((await body.boundingBox())!.x + (await body.boundingBox())!.width);
  await page.screenshot({ path: '/tmp/chat-controls-right-sidebar.png' });
  await page.getByRole('button', { name: 'Close table of contents', exact: true }).click();
  await expect(inline).not.toHaveClass(/inline-toc-sidebar/);
  await page.getByRole('button', { name: 'Open table of contents' }).click();
  await expect(inline).toHaveClass(/inline-toc-sidebar/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(inline).not.toHaveClass(/inline-toc-sidebar/);
  await expect(page.getByRole('dialog', { name: 'Table of contents' })).toHaveCount(0);
  await expect(inline.locator('.chat-toc-rail')).toBeVisible();
  await page.getByRole('button', { name: 'Open table of contents' }).click();
  await expect(page.getByRole('dialog', { name: 'Table of contents' })).toBeVisible();
  await page.screenshot({ path: '/tmp/chat-controls-right-drawer.png' });
});

for (const family of ['classic', 'porcelain', 'paper', 'gruvbox'] as const) {
  for (const mode of ['light', 'dark'] as const) {
    test(`${family} ${mode} semantic deliverable treatments`, async ({ page }) => {
      await page.goto('/chat-deliverable-fixture?tones');
      const rich = page.getByTestId('rich-deliverable');
      await expect(rich.locator('.rich-callout.tone-danger')).toBeVisible();
      await page.evaluate(({ family, mode }) => {
        document.documentElement.dataset.themeFamily = family;
        document.documentElement.dataset.resolvedTheme = mode;
      }, { family, mode });
      await expect(rich).toHaveAttribute('data-viewer-theme', mode);
      await expect(rich).toHaveAttribute('data-theme-family', family);
      for (const tone of ['neutral', 'info', 'success', 'warning', 'danger']) {
        const callout = rich.locator(`.rich-callout.tone-${tone}`);
        const badge = rich.locator(`.rich-hero-badges .tone-${tone}`);
        const colors = await callout.evaluate(element => {
          const style = getComputedStyle(element);
          return { background: style.backgroundColor, border: style.borderTopColor };
        });
        await expect(badge).toHaveCSS('background-color', colors.background);
        await expect(badge).toHaveCSS('border-top-color', colors.border);
        expect(colors.background).not.toBe('rgba(0, 0, 0, 0)');
      }
      if (family === 'classic' && mode === 'dark') {
        const original = {
          neutral: 'rgba(148, 163, 184, 0.1)', info: 'rgba(14, 165, 233, 0.12)',
          success: 'rgba(16, 185, 129, 0.12)', warning: 'rgba(217, 119, 6, 0.14)',
          danger: 'rgba(220, 38, 38, 0.14)',
        };
        for (const [tone, color] of Object.entries(original)) {
          await expect(rich.locator(`.rich-callout.tone-${tone}`)).toHaveCSS('background-color', color);
        }
        await rich.getByRole('button', { name: 'Open fullscreen' }).click();
        await expect(page.getByTestId('rich-deliverable-full-view').locator('.rich-callout.tone-warning')).toHaveCSS('background-color', original.warning);
      }
    });
  }
}
