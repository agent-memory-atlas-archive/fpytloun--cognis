import { test, expect, type WebSocketRoute } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { saveDiagnostics, startDiagnostics } from './window-drag/diagnostics';
import type { ToolCallTimelineItem } from '../src/lib/chat-v2/types';

const expansionEnabled = process.env.DRAG_EXPANSION === '1';

test.beforeEach(async ({ page }) => { await startDiagnostics(page); });
test.afterEach(async ({ page }, testInfo) => { await saveDiagnostics(page, testInfo); });

interface Counts {
  publications: number;
  retainedPublications: number;
  writes: number;
  json: number;
}

for (const { count, streaming } of [
  { count: 1, streaming: false }, { count: 3, streaming: false }, { count: 5, streaming: false },
  ...(process.env.DRAG_BASELINE === '1' ? [] : [{ count: 5, streaming: true }]),
]) {
  test(`${count} mounted synthetic chats${streaming ? ' streaming' : ''}: durable drag fanout`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => {
      if (process.env.DRAG_DIAGNOSTIC === '1') {
        if (errors.length < 20) errors.push(error.message.slice(0, 300));
      } else {
        errors.push(error.message);
        console.log('fixture error:', error.stack);
      }
    });
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      const conversationId = url.pathname.match(/conversations\/([^/]+)/)?.[1] ?? 'drag-chat-0';
      const conversation = { conversation_id: conversationId, agent_id: 'drag-agent', title: 'Synthetic chat',
        active_session_id: `session-${conversationId}`, status: 'active' };
      let body: unknown = {};
      if (url.pathname.endsWith('/auth/me')) body = { email: 'drag-acceptance@cognis.test', role: 'user' };
      else if (url.pathname.endsWith('/snapshot')) {
        body = {
          schema_version: 2, projection_version: 'drag-acceptance',
          scope: { key: `conversation:${conversationId}`, kind: 'conversation', conversation_id: conversationId },
          conversation,
          timeline: { items: [...Array.from({ length: 120 }, (_, i) => ({
            id: `message:${conversationId}-${i}`, kind: 'message', role: i % 2 ? 'assistant' : 'user',
            sort_key: `0000:${String(i + 1).padStart(15, '0')}:000000:02:000000000`,
            source_refs: [{ store: 'intaris', session_id: `session-${conversationId}`, seq: i + 1, event_type: 'assistant_message' }],
            stable: true, content: `Synthetic message ${i}\n\n` + 'Substantial deterministic chat content with **markdown** and `code`.\n\n'.repeat(8),
            message_id: `${conversationId}-${i}`, attachments: [], partial: false,
          })), ...(expansionEnabled ? [{
            id: `tool:${conversationId}-detail`, kind: 'tool_call',
            call_id: `${conversationId}-detail`, tool_name: 'read',
            sort_key: '0000:000000000000121:000000:02:000000000',
            source_refs: [], stable: true, status: 'complete',
            arguments: { file_path: 'synthetic-drag-detail.txt' },
            result_preview: 'Synthetic expanded detail retained across the gesture.',
            is_error: false, attachments: [], file_diffs: [],
            truncated: false, has_full_output: false,
          } satisfies ToolCallTimelineItem] : [])], has_more_before: false, before_cursor: null },
          state: { state_version: 1, snapshot_generated_at: '2026-10-20T08:00:00Z',
            capabilities: [], active_turn: {}, pending: {}, active_session: { session_id: `session-${conversationId}`, status: 'active', todos: [] } },
          queue: { messages: [], queued_count: 0 },
          runtime: { runtime_epoch: 'drag-acceptance', runtime_revision: 1, generated_at: '2026-10-20T08:00:00Z', has_active_turn: false, volatile_items: [] },
          cursor: `cursor:${conversationId}`, server_time: '2026-10-20T08:00:00Z',
        };
      } else if (/\/conversations\/[^/]+$/.test(url.pathname)) body = conversation;
      else if (url.pathname.endsWith('/timeline')) body = { items: [], has_more_before: false };
      else if (['/sessions', '/models', '/interactions', '/todos', '/notifications'].some((suffix) => url.pathname.endsWith(suffix))) body = [];
      await route.fulfill({ json: body });
    });
    let socket: WebSocketRoute | undefined;
    await page.routeWebSocket('**/api/ws', (ws) => {
      socket = ws;
      ws.send(JSON.stringify({ type: 'authenticated' }));
      ws.onMessage((message) => {
        if (JSON.parse(String(message)).type === 'ping') ws.send(JSON.stringify({ type: 'pong' }));
      });
    });
    await page.goto(`/?windows=${count}${streaming ? '&streaming=1' : ''}${process.env.DRAG_ORIGINAL_SCOPE === '1' ? '&scope=original' : ''}`);
    await page.waitForTimeout(500);
    await expect(page.locator('[data-window-key]')).toHaveCount(count);
    await expect(page.getByText('Synthetic message 119', { exact: false })).toHaveCount(count);
    await expect(page.getByTestId('scoped-timeline-viewport').filter({ visible: true })).toHaveCount(count);
    await page.waitForTimeout(1000);
    if (expansionEnabled) {
      const activePanel = page.locator(`[data-window-key="conversation:drag-chat-${count - 1}"]`);
      // Open any rendered grouping through its real disclosure button, then
      // open the canonical ToolCallBlock control (never mutate component state).
      const groups = activePanel.locator('[data-kind="activity_segment"] > button[aria-expanded="false"], [data-kind="tool_group"] > button[aria-expanded="false"]');
      for (const group of await groups.all()) await group.click();
      const detail = activePanel.locator(`button[aria-controls="tool-call-content-drag-chat-${count - 1}-detail"]`);
      await expect(detail).toHaveAttribute('aria-expanded', 'false');
      await detail.click();
      await expect(detail).toHaveAttribute('aria-expanded', 'true');
      await expect(activePanel.getByText('Synthetic expanded detail retained across the gesture.', { exact: true })).toBeVisible();
      await detail.evaluate((node) => Object.assign(window, { dragExpandedControl: node }));
    }
    const preservation = await page.evaluate(() => {
      const panels = [...document.querySelectorAll<HTMLElement>('[data-window-key]')];
      const inputs = panels.map((panel, index) => {
        const input = panel.querySelector<HTMLTextAreaElement>('textarea')!;
        input.value = `Preserved draft ${index}`;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        return input;
      });
      inputs[inputs.length - 1].focus();
      inputs[inputs.length - 1].setSelectionRange(2, 7);
      const scrollers = panels.map((panel) => panel.querySelector<HTMLElement>('[data-testid="scoped-timeline-viewport"]')!);
      scrollers.forEach((node) => { node.scrollTop = Math.floor((node.scrollHeight - node.clientHeight) / 2); });
      const saved = { panels, inputs, scrollers, scroll: scrollers.map((node) => node.scrollTop), active: document.activeElement };
      Object.assign(window, { dragPreservation: saved });
      return { scrollers: scrollers.length };
    });
    expect(preservation.scrollers).toBeGreaterThanOrEqual(count);
    const phaseEvidence: Array<Record<string, unknown>> = [];
    const assertPhase = async (phase: string) => {
      const value = await page.evaluate(() => {
        const saved = (window as any).dragPreservation;
        const control = (window as any).dragExpandedControl as HTMLElement | undefined;
        return {
          viewportIdentity: saved.scrollers.every((node: HTMLElement, index: number) =>
            node.isConnected && saved.panels[index].querySelector('[data-testid="scoped-timeline-viewport"]') === node),
          expanded: !control || control.isConnected && control.getAttribute('aria-expanded') === 'true',
        };
      });
      phaseEvidence.push({ phase, ...value });
      expect(value.viewportIdentity, `${phase}: original viewport DOM identity`).toBe(true);
      expect(value.expanded, `${phase}: public tool disclosure remains expanded`).toBe(true);
    };
    await assertPhase('focused');
    await page.waitForTimeout(300);
    console.log('scroll readiness', await page.evaluate(() => (window as any).dragPreservation.scrollers.map((node: HTMLElement) => ({ top: node.scrollTop, height: node.clientHeight, content: node.scrollHeight }))));
    const client = await page.context().newCDPSession(page);
    await client.send('Tracing.start', { categories: 'devtools.timeline,v8,blink.user_timing', transferMode: 'ReturnAsStream' });
    const header = page.getByTestId(`workspace-window-drag-conversation:drag-chat-${count - 1}`);
    const box = (await header.boundingBox())!;
    await page.mouse.move(box.x + 100, box.y + 20);
    await page.mouse.down();
    await assertPhase('start');
    console.log('after down', await page.evaluate(() => (window as any).dragPreservation.scrollers.map((node: HTMLElement) => ({ connected: node.isConnected, top: node.scrollTop, height: node.clientHeight, content: node.scrollHeight }))));
    await page.evaluate(() => (window as any).dragAcceptance.reset());
    const samples: Counts[] = [];
    for (let i = 1; i <= 24; i++) {
      if (streaming) {
        const conversationId = `drag-chat-${count - 1}`;
        socket!.send(JSON.stringify({
          type: 'chat_v2_frame', schema_version: 2, projection_version: 'drag-acceptance',
          scope: { key: `conversation:${conversationId}`, kind: 'conversation', conversation_id: conversationId },
          conversation_id: conversationId, cursor_before: `cursor:${conversationId}`, cursor_after: `cursor:${conversationId}`,
          ops: [], server_time: '2026-10-20T08:00:00Z',
          runtime: { runtime_epoch: 'drag-acceptance', runtime_revision: i + 1, generated_at: '2026-10-20T08:00:00Z',
            has_active_turn: true, active_turn: null, cycle_states: [],
            volatile_items: [{
              id: 'drag-stream', kind: 'message', role: 'assistant', partial: true, stable: false,
              sort_key: `0000:000000000000${expansionEnabled ? '122' : '121'}:000000:02:000000000`,
              content: `Streaming acceptance token ${i}`, attachments: [], source_refs: [],
            }] },
        }));
      }
      await page.mouse.move(box.x + 100 + i * 2, box.y + 20 + i);
      await page.evaluate(() => new Promise(requestAnimationFrame));
      if (i === 12 || i === 24) {
        samples.push(await page.evaluate(() => (window as any).dragAcceptance.counts()));
        await assertPhase(`motion-${i}`);
      }
    }
    await page.mouse.up();
    const final = await page.evaluate(() => (window as any).dragAcceptance.counts());
    await assertPhase('commit');
    console.log('after gesture', final, await page.evaluate(() => (window as any).dragPreservation.scrollers.map((node: HTMLElement) => ({ connected: node.isConnected, top: node.scrollTop, height: node.clientHeight, content: node.scrollHeight }))));
    if (streaming) await expect(page.getByText('Streaming acceptance token 24', { exact: false })).toBeAttached();
    const preserved = await page.evaluate(() => {
      const saved = (window as any).dragPreservation;
      return {
        panels: saved.panels.every((node: HTMLElement) => node.isConnected),
        viewports: saved.scrollers.every((node: HTMLElement, index: number) =>
          node.isConnected && saved.panels[index].querySelector('[data-testid="scoped-timeline-viewport"]') === node),
        inputs: saved.inputs.every((node: HTMLTextAreaElement, index: number) => node.isConnected && node.value === `Preserved draft ${index}`),
        focus: document.activeElement === saved.active,
        selection: [saved.inputs.at(-1).selectionStart, saved.inputs.at(-1).selectionEnd],
        scroll: saved.scrollers.map((node: HTMLElement) => node.scrollTop),
        expectedScroll: saved.scroll,
      };
    });
    const completed = new Promise<any>((resolve) => client.once('Tracing.tracingComplete', resolve));
    await client.send('Tracing.end');
    const { stream } = await completed;
    let trace = '';
    while (true) {
      const result = await client.send('IO.read', { handle: stream });
      trace += result.data;
      if (result.eof) break;
    }
    await client.send('IO.close', { handle: stream });
    await writeFile(testInfo.outputPath('chromium-trace.json'), trace);
    await writeFile(testInfo.outputPath('counts.json'), JSON.stringify({ count, streaming, expansionEnabled, phaseEvidence, samples, final, preserved, browserErrors: errors }, null, 2));
    console.log(JSON.stringify({ count, streaming, samples, final }));
    expect(preserved.panels).toBe(true);
    expect(preserved.viewports).toBe(true);
    expect(preserved.inputs).toBe(true);
    expect(preserved.focus).toBe(true);
    expect(preserved.selection).toEqual([2, 7]);
    expect(preserved.scroll).toEqual(preserved.expectedScroll);
    expect(errors).toEqual([]);
    if (process.env.DRAG_BASELINE === '1') {
      expect(samples.map((sample) => sample.publications)).toEqual([12, 24]);
      expect(samples.map((sample) => sample.writes)).toEqual([24, 48]);
      expect(final.publications).toBe(24);
    } else {
      expect(samples.map((sample) => sample.publications)).toEqual([0, 0]);
      expect(samples.map((sample) => sample.writes)).toEqual([0, 0]);
      expect(final.publications).toBe(1);
    }
  });
}
