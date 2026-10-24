import { expect, test, type Page } from '@playwright/test';
import { installTaskCockpitFixture } from './task-cockpit-fixture';
import { queuedComposerRuntime } from './queued-composer-runtime';
import type { ChatSnapshot, ChatSyncResponse } from '../src/lib/chat-v2/types';

test.use({ serviceWorkers: 'block' });
const conversationId = 'conv-task-chat';
const installedPages = new WeakSet<Page>();

async function installConversation(page: Page, handoffText?: string, conversationId = 'conv-task-chat'): Promise<ChatSnapshot> {
  if (!installedPages.has(page)) {
  installedPages.add(page);
  await installTaskCockpitFixture(page);
  await page.routeWebSocket('**/api/ws', (socket) => {
    socket.send(JSON.stringify({ type: 'authenticated' }));
    socket.onMessage((message) => {
      if (JSON.parse(String(message)).type === 'ping') socket.send(JSON.stringify({ type: 'pong' }));
    });
  });
  await page.route('**/api/auth/me', (route) => route.fulfill({ json: {
    email: 'owner@cognis.test', name: 'Demo owner', role: 'user',
  } }));
  await page.route('**/api/health**', (route) => route.fulfill({ json: { status: 'ok', providers: {} } }));
  await page.route('**/api/v1/skills', (route) => route.fulfill({ json: [] }));
  }
  const { runtime, state } = queuedComposerRuntime(conversationId);
  const conversation = {
    conversation_id: conversationId, agent_id: 'agent-stage39', title: 'Queued composer regression',
    user_email: 'owner@cognis.test', context: { type: 'web', ref: null, platform_data: {} },
    status: 'active', is_readonly_for_caller: false, has_active_turn: runtime.has_active_turn,
    active_session_id: runtime.active_turn!.session_id,
    project_id: null, project_name: null,
    created_at: '2030-04-16T12:00:00Z', updated_at: '2030-04-16T12:00:00Z',
  };
  await page.route(`**/api/v1/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: conversation }));
  await page.route(`**/api/v1/conversations/${conversationId}?**`, (route) =>
    route.fulfill({ json: conversation }));
  const snapshot: ChatSnapshot = {
    schema_version: 2, projection_version: 'composer-regression',
    scope: { key: `conversation:${conversationId}`, kind: 'conversation', conversation_id: conversationId },
    conversation, timeline: { items: [], has_more_before: false, before_cursor: null },
    state,
    queue: { messages: [], queued_count: 0 },
    runtime, cursor: 'composer-regression', server_time: '2030-04-16T12:00:00Z',
  };
  if (handoffText) {
    snapshot.timeline.items.push({
      kind: 'handoff', id: 'handoff:sess-task-chat:7', sort_key: '0001:0000000007:0000:handoff',
      stable: true, source_refs: [{ store: 'intaris', session_id: 'sess-task-chat', seq: 7, event_type: 'lifecycle' }],
      text: handoffText, focus: 'Review', source_session_id: 'sess-task-chat', source_seq: 6,
    });
  }
  await page.route(`**/api/v1/chat/v2/conversations/${conversationId}/snapshot*`, (route) =>
    route.fulfill({ json: snapshot }));
  const sync: ChatSyncResponse = {
    schema_version: 2, projection_version: snapshot.projection_version,
    conversation_id: conversationId, cursor_before: snapshot.cursor, cursor_after: snapshot.cursor,
    ops: [], reset_required: false, has_more: false, runtime, server_time: snapshot.server_time,
  };
  await page.route(`**/api/v1/chat/v2/conversations/${conversationId}/sync*`, (route) =>
    route.fulfill({ json: { ...sync, ops: snapshot.timeline.items.map(item => ({ op: 'upsert_item', item })) } }));
  return snapshot;
}

async function spaNavigate(page: Page, id: string): Promise<void> {
  const snapshot = page.waitForResponse(async response => {
    const path = new URL(response.url()).pathname;
    const prefix = `/api/v1/chat/v2/conversations/${encodeURIComponent(id)}/`;
    if (response.status() !== 200 || ![`${prefix}snapshot`, `${prefix}sync`].includes(path)) return false;
    const body = await response.json();
    return path.endsWith('/snapshot')
      ? body.conversation?.conversation_id === id : body.conversation_id === id;
  });
  await page.evaluate((id) => {
    const link = document.createElement('a');
    link.href = `/chat/${id}`; link.textContent = 'Synthetic SPA navigation';
    document.body.append(link); link.click(); link.remove();
  }, id);
  await expect(page).toHaveURL(new RegExp(`/chat/${id}$`));
  const body = await (await snapshot).json();
  expect(body.conversation?.conversation_id ?? body.conversation_id).toBe(id);
}

// Derive the account/profile namespace from a real UI autosave, never an
// invented profile ID or application-private object.
async function ownerSuffix(page: Page, id: string): Promise<string> {
  const snapshot = page.waitForResponse(response =>
    response.url().includes(`/chat/v2/conversations/${id}/snapshot`) && response.status() === 200);
  await page.goto(`/chat/${id}`);
  expect((await (await snapshot).json()).conversation.conversation_id).toBe(id);
  await page.getByRole('textbox', { name: 'Chat message', exact: true }).fill('Synthetic namespace seed');
  await expect.poll(() => page.evaluate((id) => Object.keys(localStorage).some(key => {
    if (!key.startsWith(`composer-v3:cognis-chat-draft:${id}:account-v2:`)) return false;
    return JSON.parse(localStorage.getItem(key)!).text === 'Synthetic namespace seed';
  }), id)).toBe(true);
  return page.evaluate((id) => {
    const key = Object.keys(localStorage).find(key => key.startsWith(`composer-v3:cognis-chat-draft:${id}:account-v2:`))!;
    return key.slice(key.indexOf(':account-v2:'));
  }, id);
}

async function outboxRowCount(page: Page, suffix: string, conversation: string): Promise<number> {
  return page.evaluate(async ({ suffix, conversation }) => {
    const name = `cognis-chat-v2${suffix}`;
    if (!(await indexedDB.databases()).some(info => info.name === name)) {
      throw new Error('Expected synthetic account outbox database was not inspected');
    }
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(name);
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    try {
      if (!db.objectStoreNames.contains('outbox')) throw new Error('Expected outbox store missing');
      const rows = await new Promise<Array<{ conversation_id: string }>>((resolve, reject) => {
        const request = db.transaction('outbox', 'readonly').objectStore('outbox').getAll();
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      return rows.filter(row => row.conversation_id === conversation).length;
    } finally { db.close(); }
  }, { suffix, conversation });
}

for (const mode of [null, 'default', 'plan', 'build'] as const) {
  test(`full page preserves canonical ${mode ?? 'inherit'} mode and newer input across SPA/reopen`, async ({ page }) => {
    const seed = 'conv-mode-seed', target = 'conv-mode-target';
    for (const id of [seed, target]) await installConversation(page, undefined, id);
    const suffix = await ownerSuffix(page, seed);
    await page.evaluate(({ suffix, target, mode }) => {
      localStorage.setItem(`composer-v3:cognis-chat-draft:${target}${suffix}`, JSON.stringify({
        version: 3, revision: crypto.randomUUID(), input_revision: crypto.randomUUID(), consumed: false,
        text: 'Canonical synthetic input', attachments: [], chat_mode: mode,
      }));
      // Canonical data wins over opposite legacy data without deleting it.
      localStorage.setItem(`cognis:chat-v2-draft:${target}${suffix}`, JSON.stringify({
        version: 2, revision: crypto.randomUUID(), value: 'Older compact input',
      }));
    }, { suffix, target, mode });
    const captured = await page.evaluate(({ suffix, target }) =>
      JSON.parse(localStorage.getItem(`composer-v3:cognis-chat-draft:${target}${suffix}`)!), { suffix, target });
    await spaNavigate(page, target);
    const composer = page.getByRole('textbox', { name: 'Chat message', exact: true });
    await expect(composer).toHaveValue(captured.text);
    await expect(page.getByRole('button', { name: 'Send as new', exact: true })).toHaveCount(0);
    await page.reload();
    await expect(composer).toHaveValue(captured.text);
    expect(await page.evaluate(({ suffix, target }) => {
      const record = JSON.parse(localStorage.getItem(`composer-v3:cognis-chat-draft:${target}${suffix}`)!);
      return { input_revision: record.input_revision, chat_mode: record.chat_mode };
    }, { suffix, target })).toEqual({ input_revision: captured.input_revision, chat_mode: mode });
    await composer.fill('Newer synthetic input');
    await expect.poll(() => page.evaluate(({ suffix, target, original }) => {
      const record = JSON.parse(localStorage.getItem(`composer-v3:cognis-chat-draft:${target}${suffix}`)!);
      return record.text === 'Newer synthetic input' && record.input_revision !== original;
    }, { suffix, target, original: captured.input_revision })).toBe(true);
    let sentMode: unknown = 'not-sent';
    await page.route(`**/api/v1/chat/v2/conversations/${target}/messages/*`, async route => {
      const request = route.request().postDataJSON();
      sentMode = request.chat_mode ?? null;
      await route.fulfill({ json: { status: 'queued', conversation_id: target,
        client_txn_id: new URL(route.request().url()).pathname.split('/').pop(),
        client_message_id: request.client_message_id, server_time: new Date().toISOString() } });
    });
    await page.getByRole('button', { name: 'Queue message', exact: true }).click();
    await expect.poll(() => sentMode).toBe(mode);
  });
}

test('full page displays opposite legacy attachments and explicit new-mode confirmation', async ({ page }) => {
  const seed = 'conv-legacy-seed', target = 'conv-legacy-target';
  for (const id of [seed, target]) await installConversation(page, undefined, id);
  const suffix = await ownerSuffix(page, seed);
  await page.evaluate(({ suffix, target }) => {
    const store = (key: string, value: string) => localStorage.setItem(`${key}${suffix}`,
      JSON.stringify({ version: 2, revision: crypto.randomUUID(), value }));
    store(`cognis:chat-v2-draft:${target}`, '<b>Synthetic legacy text</b>');
    store(`cognis:chat-v2-draft-attachments:${target}`, JSON.stringify([{
      artifact_id: `synthetic-artifact-${crypto.randomUUID()}`, filename: 'synthetic.png',
      mime_type: 'image/png', kind: 'image', size_bytes: 1,
    }]));
  }, { suffix, target });
  await spaNavigate(page, target);
  const composer = page.getByRole('textbox', { name: 'Chat message', exact: true });
  await expect(composer).toHaveValue('<b>Synthetic legacy text</b>');
  await expect(page.getByText('synthetic.png', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send as new', exact: true })).toBeVisible();
  await expect(page.getByLabel('Mode for new message')).toHaveValue('inherit');
  expect(await page.locator('b').filter({ hasText: 'Synthetic legacy text' }).count()).toBe(0);
  await page.getByLabel('Mode for new message').selectOption('default');
  await page.getByRole('button', { name: 'Send as new', exact: true }).click();
  await expect.poll(() => page.evaluate(({ suffix, target }) => {
    const raw = localStorage.getItem(`composer-v3:cognis-chat-draft:${target}${suffix}`);
    return raw ? JSON.parse(raw).chat_mode : 'missing';
  }, { suffix, target })).toBe('default');
  await page.reload();
  await expect(composer).toHaveValue('<b>Synthetic legacy text</b>');
  await expect(page.getByText('synthetic.png', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send as new', exact: true })).toHaveCount(0);
});

test('full-page failed admission reopens with original transaction and message IDs', async ({ page }) => {
  await installConversation(page);
  const attempts: Array<{ txn: string; message: string }> = [];
  let permitReceipt = false, receipts = 0;
  await page.route(`**/api/v1/chat/v2/conversations/${conversationId}/messages/*`, async route => {
    const request = route.request().postDataJSON();
    const txn = new URL(route.request().url()).pathname.split('/').pop()!;
    attempts.push({ txn, message: request.client_message_id });
    if (!permitReceipt) { await route.abort('failed'); return; }
    receipts++;
    await route.fulfill({ json: { status: 'queued', conversation_id: conversationId,
      client_txn_id: txn, client_message_id: request.client_message_id, server_time: new Date().toISOString() } });
  });
  await page.goto(`/chat/${conversationId}`);
  const composer = page.getByRole('textbox', { name: 'Chat message', exact: true });
  await composer.fill('Synthetic retry input');
  await page.getByRole('button', { name: 'Queue message', exact: true }).click();
  await expect.poll(() => attempts.length).toBeGreaterThan(0);
  await expect(composer).toHaveValue('');
  permitReceipt = true;
  await page.reload();
  await expect.poll(() => receipts).toBe(1);
  await expect(composer).toHaveValue('');
  expect(new Set(attempts.map(attempt => attempt.txn)).size).toBe(1);
  expect(new Set(attempts.map(attempt => attempt.message)).size).toBe(1);
});

test('full composer retires recovery before malformed next-conversation hydration', async ({ page }) => {
  const a = 'conv-recovery-a', b = 'conv-recovery-b', c = 'conv-recovery-c';
  for (const id of [a, b, c]) await installConversation(page, undefined, id);
  let sends = 0;
  await page.route('**/api/v1/chat/v2/conversations/*/messages/*', async (route) => {
    sends++;
    await route.fulfill({ status: 500, json: { detail: 'No admission expected' } });
  });
  await page.goto(`/chat/${c}`);
  const composer = page.getByRole('textbox', { name: 'Chat message', exact: true });
  await expect(composer).toBeEditable();
  await composer.fill('valid C');
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage)
    .some((key) => key.startsWith('composer-v3:cognis-chat-draft:conv-recovery-c:account-v2:')))).toBe(true);
  const suffix = await page.evaluate(({ a, b, c }) => {
    const canonical = Object.keys(localStorage).find((key) => key.startsWith(`composer-v3:cognis-chat-draft:${c}:account-v2:`))!;
    const suffix = canonical.slice(canonical.indexOf(':account-v2:'));
    localStorage.setItem(`cognis:chat-v2-draft:${a}${suffix}`, JSON.stringify({ version: 2, revision: crypto.randomUUID(), value: 'private A recovery' }));
    localStorage.setItem(`cognis:chat-v2-draft-attachments:${a}${suffix}`, JSON.stringify({
      version: 2, revision: crypto.randomUUID(), value: JSON.stringify([{
        artifact_id: `synthetic-artifact-${crypto.randomUUID()}`, kind: 'image',
        filename: 'synthetic-A.png', mime_type: 'image/png', size_bytes: 1,
      }]),
    }));
    localStorage.setItem(`cognis:chat-v2-draft-attachments:${b}${suffix}`, JSON.stringify({ version: 2, revision: 'synthetic-B', value: '{malformed' }));
    return suffix;
  }, { a, b, c });
  const navigate = (id: string) => spaNavigate(page, id);
  await navigate(a);
  const oldSelection = await page.getByRole('button', { name: 'Send as new', exact: true }).elementHandle();
  await expect(composer).toHaveValue('private A recovery');
  await expect(page.getByText('synthetic-A.png', { exact: true }).first()).toBeVisible();
  await expect(page.getByLabel('Mode for new message')).toHaveValue('inherit');
  await navigate(b);
  await expect(composer).toHaveValue('');
  await expect(page.getByText('synthetic-A.png', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Mode for new message')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Send as new', exact: true })).toHaveCount(0);
  await oldSelection!.evaluate((button) => (button as HTMLButtonElement).click());
  expect(await page.evaluate(({ a, b, suffix }) => ({
    a: JSON.parse(localStorage.getItem(`cognis:chat-v2-draft:${a}${suffix}`)!).value,
    b: JSON.parse(localStorage.getItem(`cognis:chat-v2-draft-attachments:${b}${suffix}`)!).value,
    canonicalB: localStorage.getItem(`composer-v3:cognis-chat-draft:${b}${suffix}`),
  }), { a, b, suffix })).toEqual({ a: 'private A recovery', b: '{malformed', canonicalB: null });
  expect(sends).toBe(0);
  expect(await outboxRowCount(page, suffix, b)).toBe(0);
  await navigate(c);
  await expect(composer).toHaveValue('valid C');
  expect(sends).toBe(0);
  // Negative control after all application assertions: prove the count is not
  // vacuous. This fresh browser context is discarded by Playwright afterward.
  await page.evaluate(async ({ suffix, b }) => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(`cognis-chat-v2${suffix}`);
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    try {
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction('outbox', 'readwrite');
        tx.oncomplete = () => resolve(); tx.onabort = () => reject(tx.error);
        tx.objectStore('outbox').put({
          client_txn_id: crypto.randomUUID(), client_message_id: crypto.randomUUID(),
          conversation_id: b, content: 'Synthetic assertion control', attachments: [],
          status: 'preparing', created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        });
      });
    } finally { db.close(); }
  }, { suffix, b });
  expect(await outboxRowCount(page, suffix, b)).toBe(1);
});

test('main composer clears a queued message and stays empty after reload', async ({ page }) => {
  await installConversation(page);
  let sends = 0;
  const message = 'Synthetic message accepted into the queue';
  await page.route(`**/api/v1/chat/v2/conversations/${conversationId}/messages/*`, async (route) => {
    const request = route.request().postDataJSON();
    expect(route.request().method()).toBe('PUT');
    expect(request.content).toBe(message);
    sends += 1;
    await route.fulfill({ json: {
      status: 'queued', conversation_id: conversationId,
      client_txn_id: new URL(route.request().url()).pathname.split('/').pop(),
      client_message_id: request.client_message_id,
      server_time: '2030-04-16T12:00:00Z',
    } });
  });
  const ready = page.waitForResponse((response) =>
    response.url().includes(`/chat/v2/conversations/${conversationId}/snapshot`)
    && response.status() === 200);
  await page.goto(`/chat/${conversationId}`);
  await ready;
  const composer = page.getByRole('textbox', { name: 'Chat message', exact: true });
  await expect(composer).toBeEditable();
  await composer.fill(message);
  await page.getByRole('button', { name: 'Queue message', exact: true }).click();
  await expect.poll(() => sends).toBe(1);
  await expect(composer).toHaveValue('');
  const reloaded = page.waitForResponse((response) =>
    ['snapshot', 'sync'].some((operation) =>
      response.url().includes(`/chat/v2/conversations/${conversationId}/${operation}`))
    && response.status() === 200);
  await page.reload();
  await reloaded;
  await expect(composer).toBeEditable();
  await expect(composer).toHaveValue('');
  expect(sends).toBe(1);
});

test('handoff creates an unsent recipient draft and preserves the source composer', async ({ page }) => {
  const handoff = '# Review handoff\n\nPreserve **pending approval**.\n\nNext: inspect the diff.';
  const sourceSnapshot = await installConversation(page, handoff);
  sourceSnapshot.conversation.agent_profile_id = 'developer';
  const recipientSnapshot = await installConversation(page, undefined, 'conv-task-chat-b');
  recipientSnapshot.runtime.has_active_turn = false;
  recipientSnapshot.runtime.active_turn = null;
  recipientSnapshot.state.active_turn = { has_active_turn: false };
  Object.assign(recipientSnapshot.conversation, { has_active_turn: false });
  let sentMessages = 0;
  let createdConversations = 0;
  let linked = false;
  await page.route('**/api/v1/chat/v2/conversations/*/messages/*', async (route) => {
    sentMessages += 1;
    expect(route.request().postDataJSON().content).toBe(handoff);
    await route.fulfill({ json: { status: 'accepted', conversation_id: 'conv-task-chat-b',
      client_txn_id: new URL(route.request().url()).pathname.split('/').pop(),
      client_message_id: route.request().postDataJSON().client_message_id,
      server_time: new Date().toISOString() } });
  });
  await page.route(`**/api/v1/conversations/${conversationId}/handoff-links`, async route => {
    expect(createdConversations).toBe(1);
    expect(route.request().postDataJSON()).toEqual({
      source_session_id: 'sess-task-chat', source_event_seq: 7, recipient_conversation_id: 'conv-task-chat-b',
    });
    linked = true;
    const card = sourceSnapshot.timeline.items.find(item => item.kind === 'handoff');
    if (card?.kind === 'handoff') card.recipient_conversation_id = 'conv-task-chat-b';
    await route.fulfill({ json: { ok: true } });
  });
  await page.route('**/api/v1/conversations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    createdConversations += 1;
    expect(route.request().postDataJSON()).toMatchObject({ agent_id: 'agent-stage39', agent_profile_id: 'developer' });
    await route.fulfill({ json: {
      conversation_id: 'conv-task-chat-b', agent_id: 'agent-stage39',
      user_email: 'owner@cognis.test', title: 'Handoff recipient', status: 'active',
      context: { type: 'web', platform_data: {} },
    } });
  });
  await page.goto(`/chat/${conversationId}`);
  const composer = page.getByRole('textbox', { name: 'Chat message', exact: true });
  await expect(composer).toBeEditable();
  await composer.fill('Keep this source draft');
  await expect(page.getByRole('heading', { name: 'Review handoff' })).toHaveCount(0);
  await page.getByRole('button', { name: 'New conversation from handoff' }).click();
  const dialog = page.getByRole('dialog', { name: /Continue from handoff|New chat/ });
  await expect(dialog.getByLabel('Primary agent')).toHaveCount(0);
  await expect(dialog.getByLabel('Agent profile')).toHaveValue('developer');
  await expect(dialog.getByTestId('new-chat-project')).toHaveCount(0);
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(createdConversations).toBe(0);
  expect(linked).toBe(false);
  await expect(page.getByRole('button', { name: 'New conversation from handoff' })).toBeVisible();
  await page.getByRole('button', { name: 'New conversation from handoff' }).click();
  await dialog.getByRole('button', { name: 'Create conversation', exact: true }).click();
  await expect(page).toHaveURL(/\/chat\/conv-task-chat-b$/);
  await expect(composer).toHaveValue(handoff);
  await expect(page.getByRole('button', { name: 'Send as new', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Mode for new message')).toHaveCount(0);
  await expect(page.getByText(/Recovered draft may already have been sent/)).toHaveCount(0);
  await page.reload();
  await expect(composer).toHaveValue(handoff);
  expect(createdConversations).toBe(1);
  expect(sentMessages).toBe(0);
  expect(linked).toBe(true);
  await page.goto(`/chat/${conversationId}`);
  await expect(composer).toHaveValue('Keep this source draft');
  await expect(page.getByRole('link', { name: 'Open handoff conversation' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'New conversation from handoff' })).toHaveCount(0);
  await page.getByRole('link', { name: 'Open handoff conversation' }).click();
  await expect(composer).toHaveValue(handoff);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect.poll(() => sentMessages).toBe(1);
});
