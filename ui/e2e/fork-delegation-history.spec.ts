import { expect, test } from '@playwright/test';

const conversationId = 'conv_history_review';
const sessionId = 'sess_history_review';
const originalTime = '2026-10-21T05:47:00Z';
const conversation = {
  conversation_id: conversationId, agent_id: 'laforge', title: 'History review',
  status: 'active', active_session_id: sessionId, context: { type: 'web' },
  has_message_history: true,
};
const message = {
  id: 'history-message', kind: 'message', role: 'assistant', message_id: 'history-message',
  content: 'Review finished before the fork.', sort_key: '0001', stable: true,
  source_refs: [{ store: 'intaris', session_id: sessionId, seq: 1, event_type: 'assistant_message' }],
  created_at: originalTime, updated_at: originalTime, status: 'complete', attachments: [], partial: false,
};
const delegation = {
  id: 'delegation:sess_child_review', kind: 'delegation', sort_key: '0002',
  source_refs: [{ store: 'intaris', session_id: sessionId, seq: 2, event_type: 'delegation' }],
  created_at: originalTime, updated_at: originalTime, status: 'complete', stable: true,
  child_session_id: 'sess_child_review', agent_id: 'system:code-review', title: 'Independent review',
  result_summary: '### Verdict\n\n**APPROVE**\n\n- Preserves `ordering`\n\n[Unsafe](javascript:alert(1))',
};

for (const width of [390, 1280]) {
  test(`history card Markdown and single-click fork at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 960 });
    page.on('pageerror', error => console.error('Browser error:', error.message));
    let forkCalls = 0;
    let finishFork!: () => void;
    const forkReady = new Promise<void>(resolve => { finishFork = resolve; });
    const dialogs: string[] = [];
    page.on('dialog', async dialog => {
      dialogs.push(dialog.message());
      await dialog.dismiss();
    });
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.fallback();
      let body: unknown = [];
      if (path === '/api/auth/me') body = { email: 'review@cognis.local', role: 'user', name: 'Review' };
      else if (path === '/api/bootstrap-status') body = { has_users: true, needs_bootstrap: false };
      else if (path === '/api/health') body = { status: 'ok', services: {}, llm_available: true };
      else if (path.endsWith('/sidebar')) body = {
        agents: [{ agent_id: 'laforge', name: 'LaForge', enabled: true }],
        agent_direct_chats: [], conversations: { items: [conversation], next_cursor: null, has_more: false },
      };
      else if (path === `/api/v1/conversations/${conversationId}`) body = conversation;
      else if (path === '/api/v1/agents/laforge') body = { agent_id: 'laforge', name: 'LaForge', enabled: true };
      else if (path.endsWith('/preferences')) body = {};
      else if (path.endsWith('/snapshot')) body = {
        schema_version: 2, projection_version: 'history-browser-test',
        scope: { kind: 'conversation', key: `conversation:${conversationId}`, conversation_id: conversationId },
        conversation, cursor: 'history-browser-initial', server_time: originalTime,
        timeline: { items: [message, delegation], has_more_before: false, before_cursor: null },
        state: { state_version: 1, snapshot_generated_at: originalTime, capabilities: [],
          active_turn: {}, pending: {}, active_session: {} },
        queue: { messages: [], queued_count: 0 }, runtime: null,
      };
      else if (path.endsWith('/assistant-messages/fork')) {
        forkCalls++;
        expect(route.request().postDataJSON()).toEqual({ source_session_id: sessionId, source_seq: 1 });
        await forkReady;
        body = { conversation_id: 'conv_history_fork', session_id: 'sess_history_fork' };
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto(`/chat/${conversationId}`);
    const card = page.locator('article').filter({ has: page.getByRole('heading', { name: 'Independent review' }) });
    await expect(card.getByRole('heading', { name: 'Verdict' })).toBeVisible();
    await expect(card.getByText('completed', { exact: true })).toBeVisible();
    await expect(card.locator('strong')).toHaveText('APPROVE');
    await expect(card.locator('li code')).toHaveText('ordering');
    await expect(card.locator('a[href^="javascript:"]')).toHaveCount(0);
    await expect(card.getByText('running', { exact: true })).toHaveCount(0);
    await page.reload();
    await expect(card.getByRole('heading', { name: 'Verdict' })).toBeVisible();
    await expect(card.getByText('completed', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`delegation-history-${width}.png`), fullPage: true });

    const forkButton = page.getByRole('button', { name: 'Fork conversation from this message' });
    await forkButton.click();
    await expect.poll(() => forkCalls).toBe(1);
    const pendingFork = page.getByRole('button', { name: 'Forking conversation…' });
    await expect(pendingFork).toBeDisabled();
    await expect(pendingFork).toHaveAttribute('aria-busy', 'true');
    expect(dialogs).toEqual([]);
    finishFork();
    await expect(page).toHaveURL(/\/chat\/conv_history_fork$/);
  });
}
