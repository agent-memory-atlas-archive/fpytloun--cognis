import { expect, test, type Locator, type Page } from '@playwright/test';
import { installLibraryFixture } from './library-fixture';
import { installTaskCockpitFixture } from './task-cockpit-fixture';
import type { ConversationFlatSearchMatch } from '../src/lib/types/api';

async function selected(input: Locator) {
  await expect(input).toBeFocused();
  await expect.poll(() => input.evaluate((node: HTMLInputElement) =>
    [node.selectionStart, node.selectionEnd, node.value.length])).toEqual(
    [0, (await input.inputValue()).length, (await input.inputValue()).length],
  );
}
async function defaultPreserved(page: Page) {
  return page.evaluate(() => {
    const event = new KeyboardEvent('keydown', { key: 'f', ctrlKey: true, bubbles: true, cancelable: true });
    (document.activeElement ?? document.body).dispatchEvent(event);
    return !event.defaultPrevented;
  });
}
function observeFindRequests(page: Page) {
  const mutations: string[] = [];
  const searches: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path === '/api/v1/chat/v2/client-performance') return;
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) mutations.push(`${request.method()} ${path}`);
    if (path.startsWith('/api/v1/search/conversation/')) searches.push(path);
  });
  return { mutations, searches };
}
async function chatState(page: Page) {
  return page.evaluate(() => {
    const search = document.querySelector<HTMLInputElement>('input[placeholder="Search this conversation"]');
    return {
      query: search?.value ?? '',
      drafts: [...document.querySelectorAll<HTMLTextAreaElement>('textarea')].map((input) => input.value),
      results: [...(search?.closest('form')?.querySelectorAll<HTMLButtonElement>('button[type="button"]:not([aria-label])') ?? [])]
        .map((button) => [button.textContent, button.className]),
    };
  });
}

test('library Find selects query, follows tabs and respects a searchless reader modal', async ({ page }) => {
  await installLibraryFixture(page);
  await page.goto('/library');
  const search = page.getByRole('searchbox');
  await search.fill('release');
  await page.getByRole('heading', { name: 'Library', exact: true }).click();
  await page.keyboard.press('Control+f');
  await selected(search);
  await expect(search).toHaveValue('release');
  await page.getByRole('link', { name: /Release readiness review/ }).click();
  await expect(page.getByTestId('library-resource-modal')).toBeVisible();
  expect(await defaultPreserved(page)).toBe(true);
  await page.keyboard.press('Escape');
  await page.getByRole('tab', { name: 'Files', exact: true }).click();
  await page.keyboard.press('Meta+f');
  await selected(search);
  // Browser-injected Meta is DOM parity evidence, not an AppKit key-delivery test.
  await page.screenshot({ path: test.info().outputPath('find-library.png') });
});

test('full chat opens collapsed search and preserves composer draft without submitting', async ({ page }) => {
  await installLibraryFixture(page);
  await page.route('**/api/v1/search/health', (route) => route.fulfill({ json: { enabled: true } }));
  // Loading an observed conversation acknowledges it independently of Find.
  // Finish that public lifecycle request before taking the no-mutation baseline.
  const initialRead = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/conversations/conv-task-chat/read');
  await page.goto('/chat/conv-task-chat');
  const search = page.getByPlaceholder('Search this conversation');
  await expect(page.getByRole('button', { name: 'Search conversation', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Search conversation', exact: true })).toBeEnabled();
  await (await initialRead).finished();
  await expect(search).toHaveCount(0);
  const composer = page.locator('textarea').first();
  await composer.fill('unsent focus test');
  const requests = observeFindRequests(page);
  const beforeFirstKey = await chatState(page);
  await page.keyboard.press('Control+f');
  await selected(search);
  expect(await chatState(page)).toEqual(beforeFirstKey);
  expect(requests).toEqual({ mutations: [], searches: [] });
  const matches: ConversationFlatSearchMatch[] = ['First retained match', 'Second retained match'].map((snippet, index) => ({
    conversation_id: 'conv-task-chat', conversation_title: 'Task chat', agent_id: 'agent-stage39',
    project_id: null, status: 'active', session_id: 'sess-task-chat',
    intaris_session_id: 'sess-task-chat', kind_rank: index,
    match: {
      session_id: 'sess-task-chat', kind: 'summary', ref_id: null, role: 'assistant',
      ts: null, snippet, score: 1 - index / 10, score_breakdown: {}, agent_id: null,
      session_title: null, session_intention: null,
    },
  }));
  await page.route('**/api/v1/search/conversation/*', (route) => route.fulfill({ json: { matches } }));
  await search.fill('retained query');
  await search.press('Enter');
  const form = page.locator('form').filter({ has: search });
  await expect(form.getByRole('button', { name: /Second retained match/ })).toBeVisible();
  await form.getByRole('button', { name: 'Next match', exact: true }).click();
  await expect(form).toContainText('2/2');
  expect(requests.mutations).toEqual(['POST /api/v1/search/conversation/conv-task-chat']);
  expect(requests.searches).toHaveLength(1);
  const afterExplicitSearch = structuredClone(requests);
  await composer.focus();
  const beforeRepeatedKey = await chatState(page);
  expect(beforeRepeatedKey.results).toHaveLength(2);
  await page.keyboard.press('Control+f');
  await selected(search);
  expect(await chatState(page)).toEqual(beforeRepeatedKey);
  await expect(form).toContainText('2/2');
  await expect(composer).toHaveValue('unsent focus test');
  expect(requests).toEqual(afterExplicitSearch);
  await page.keyboard.press('Escape');
  await expect(search).toHaveCount(0);
  await page.keyboard.press('Control+f');
  await expect(search).toBeVisible();
  let seededRequests = 0;
  await page.route('**/api/v1/search/conversation/*', async (route) => {
    seededRequests++;
    await route.fulfill({ json: { matches: [] } });
  });
  // A same-document SvelteKit navigation must clear focus-only suppression.
  await page.evaluate(() => {
    const link = document.createElement('a');
    link.href = '/chat/conv-task-chat?search=explicit-seed&searchSession=sess-task-chat&searchRef=seed-ref';
    link.textContent = 'Explicit search destination';
    document.body.append(link);
    link.click();
    link.remove();
  });
  await expect(search).toHaveValue('explicit-seed');
  await expect.poll(() => seededRequests).toBeGreaterThan(0);
});

test('dashboard compact window falls back to visible dashboard search, including after minimize', async ({ page }) => {
  await installLibraryFixture(page);
  await installTaskCockpitFixture(page, { dashboardWorkspaceWindows: true, dashboardConversation: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/');
  const search = page.getByRole('textbox', { name: 'Search tasks and conversations' });
  await expect(search).toBeVisible();
  await page.keyboard.press('Control+f');
  await selected(search);
  const row = page.locator('[data-testid^="dashboard-conversation-row-"]:not([data-testid*="-link-"])').first();
  const initialRead = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/conversations/conv-task-chat/read');
  await row.click();
  const window = page.locator('[data-window-key][data-focused="true"]');
  await expect(window).toBeVisible();
  await expect(window.locator('textarea').first()).toBeEnabled();
  await (await initialRead).finished();
  await window.locator('textarea').first().focus();
  const requests = observeFindRequests(page);
  const beforeKey = await chatState(page);
  const dashboardQuery = await search.inputValue();
  await page.keyboard.press('Control+f');
  await selected(search);
  expect(await chatState(page)).toEqual(beforeKey);
  await expect(search).toHaveValue(dashboardQuery);
  expect(requests).toEqual({ mutations: [], searches: [] });
  await window.getByRole('button', { name: 'Minimize', exact: true }).click();
  await page.keyboard.press('Control+f');
  await selected(search);
  await expect(search).toHaveValue(dashboardQuery);
  expect(requests).toEqual({ mutations: [], searches: [] });
});
