import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Conversation } from '$lib/types/api';
import { WorkspaceOwner } from '$lib/native/workspace-protocol';
import { ConversationWorkspace } from './conversation-workspace';
import { WorkspaceManager } from './workspace';

const account = 'restore@workspace.test';
const chat = (id: string, agent = 'agent-first', project: string | null = null) => ({
  conversation_id: id, agent_id: agent, project_id: project, title: id, status: 'idle',
}) as Conversation;
const input = (id: string) => ({
  kind: 'conversation' as const, entityId: id, title: id, canonicalHref: `/chat/${id}`,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const stops: (() => void)[] = [];
afterEach(() => { stops.splice(0).forEach((stop) => stop()); vi.useRealTimers(); });

async function setup(count = 1, project: string | null = null) {
  const workspace = new ConversationWorkspace();
  workspace.setOwner(account, null);
  for (let i = 0; i < count; i++) await workspace.pin(chat(`chat-${i}`, 'agent-first', project));
  const manager = new WorkspaceManager('desktop', { x: 0, y: 0, width: 1440, height: 900 });
  const unbind = workspace.bind(manager, project, `layout:${project ?? 'dashboard'}`);
  await workspace.execute({ type: 'position', value: 0.65 });
  const resolve = vi.fn(async (id: string) => chat(id, 'agent-first', project));
  const validate = vi.fn(async () => {});
  const owner = new WorkspaceOwner(
    { profile: 'https://workspace.test', account, authEpoch: 'auth-first' },
    'main-document', 'owner-first', workspace,
    () => ({ workspace: workspace.snapshot(), agents: [], conversations: {}, background: [] }),
    resolve, validate, () => {},
  );
  workspace.setCommand((intent) => owner.submit(intent));
  stops.push(() => { unbind(); owner.stop(); workspace.setCommand(null); });
  return { workspace, manager, owner, resolve, validate, unbind };
}

describe('owner-verified list open and retained restore', () => {
  it('restores at ten retained and four visible without fetching allocation metadata', async () => {
    const h = await setup(10);
    h.manager.minimize('conversation:chat-0');
    expect(h.manager.snapshot().filter((w) => !w.minimized)).toHaveLength(4);
    expect(await h.manager.requestOpen(input('chat-9'))).toEqual({ status: 'focused', key: 'conversation:chat-9' });
    expect(h.manager.snapshot().filter((w) => !w.minimized)).toHaveLength(5);
    expect(h.workspace.snapshot().entries).toHaveLength(10);
    expect(h.resolve).not.toHaveBeenCalled();
    expect(h.validate).toHaveBeenCalled();
  });

  it('singleflights repeated clicks and waits for the lease before restoring', async () => {
    const h = await setup();
    h.manager.minimize('conversation:chat-0');
    const lease = deferred<void>();
    h.validate.mockImplementation(() => lease.promise);
    const first = h.manager.requestOpen(input('chat-0'));
    const second = h.manager.requestOpen(input('chat-0'));
    await Promise.resolve();
    expect(h.manager.snapshot()[0].minimized).toBe(true);
    lease.resolve();
    expect(await first).toEqual(await second);
    expect(h.validate).toHaveBeenCalledTimes(1);
    expect(h.resolve).not.toHaveBeenCalled();
    expect(h.workspace.snapshot().entries).toHaveLength(1);
    expect(h.manager.snapshot()[0].minimized).toBe(false);
  });

  it.each(['owner-unavailable', 'scope-changed', 'invalid-home', 'unresolved', 'uncertain', 'permission-denied'])(
    'preserves %s instead of inventing capacity', async (reason) => {
      const h = await setup();
      h.workspace.setCommand(async () => ({ ok: false, reason }));
      expect(await h.manager.requestOpen(input('chat-0'))).toEqual({ status: 'failed', reason });
    },
  );

  it.each(['dispose', 'account', 'account-roundtrip', 'project'])('does not focus after %s changes during acknowledgement', async (change) => {
    const h = await setup();
    const lease = deferred<void>();
    h.validate.mockImplementation(() => lease.promise);
    const focus = vi.spyOn(h.manager, 'focus');
    const pending = h.manager.requestOpen(input('chat-0'));
    if (change === 'dispose') h.unbind();
    if (change === 'account' || change === 'account-roundtrip') {
      h.workspace.setOwner('other@workspace.test', null);
      if (change === 'account-roundtrip') h.workspace.setOwner(account, null);
    }
    if (change === 'project') {
      const stop = h.workspace.bind(h.manager, 'project-other', 'layout:project-other');
      stops.push(stop);
      h.unbind();
    }
    lease.resolve();
    expect((await pending).status).toBe('failed');
    expect(focus).not.toHaveBeenCalled();
    if (change.startsWith('account')) expect(h.workspace.snapshot().entries).toHaveLength(0);
  });

  it('does not restore through a rejected owner lease', async () => {
    const h = await setup();
    h.manager.minimize('conversation:chat-0');
    h.validate.mockRejectedValue(new Error('Lease revoked'));
    expect(await h.manager.requestOpen(input('chat-0'))).toEqual({ status: 'failed', reason: 'uncertain' });
    expect(h.manager.snapshot()[0].minimized).toBe(true);
    expect(h.resolve).not.toHaveBeenCalled();
  });

  it('honors visible capacity while restoring a retained identity', async () => {
    const h = await setup(10);
    expect(await h.manager.requestOpen(input('chat-9'))).toEqual({ status: 'capped', limit: 5, scope: 'visible' });
    expect(h.workspace.snapshot().entries).toHaveLength(10);
    expect(h.resolve).not.toHaveBeenCalled();
  });

  it('browser ownership also reuses retained identity without a detail request', async () => {
    const h = await setup();
    h.workspace.setCommand(null);
    h.manager.minimize('conversation:chat-0');
    expect(await h.manager.requestOpen(input('chat-0'))).toEqual({ status: 'focused', key: 'conversation:chat-0' });
    expect(h.workspace.snapshot().entries).toHaveLength(1);
  });

  it.each([{ ok: true }, { ok: true, key: 'conversation:missing' }])(
    'does not focus a successful acknowledgement with no projected matching key: %j', async (result) => {
      const h = await setup();
      h.workspace.setCommand(async () => result);
      const focus = vi.spyOn(h.manager, 'focus');
      expect((await h.manager.requestOpen(input('chat-0'))).status).toBe('failed');
      expect(focus).not.toHaveBeenCalled();
    },
  );

  it('does not report success for a key outside the current project projection', async () => {
    const h = await setup(1, 'project-first');
    h.resolve.mockImplementation(async (id) => chat(id, 'agent-first', 'project-other'));
    const focus = vi.spyOn(h.manager, 'focus');
    expect(await h.manager.requestOpen(input('chat-other'))).toEqual({ status: 'failed', reason: 'not-projected' });
    expect(focus).not.toHaveBeenCalled();
  });

  it('keeps a timed-out command uncertain and never replays it or focuses late', async () => {
    vi.useFakeTimers();
    const h = await setup();
    h.manager.minimize('conversation:chat-0');
    const lease = deferred<void>();
    h.validate.mockImplementation(() => lease.promise);
    const focus = vi.spyOn(h.manager, 'focus');
    const pending = h.manager.requestOpen(input('chat-0'));
    await vi.advanceTimersByTimeAsync(8000);
    expect(await pending).toEqual({ status: 'failed', reason: 'uncertain' });
    lease.resolve();
    await vi.advanceTimersByTimeAsync(0);
    expect(focus).not.toHaveBeenCalled();
    expect(h.validate).toHaveBeenCalledTimes(1);
    expect(h.manager.snapshot()[0].minimized).toBe(true);
  });

  it('reuses resolved agent identity at cap', async () => {
    const h = await setup(9);
    await h.manager.requestOpen({ kind: 'agent', entityId: 'agent-first', title: 'Agent', canonicalHref: '/chat/new' });
    await h.workspace.resolveAgent('agent:agent-first', chat('chat-resolved'));
    h.manager.minimize('conversation:chat-0');
    h.manager.minimize('agent:agent-first');
    expect(await h.manager.requestOpen(input('chat-resolved'))).toEqual({ status: 'focused', key: 'agent:agent-first' });
    expect(h.workspace.snapshot().entries).toHaveLength(10);
    expect(await h.manager.requestOpen(input('chat-new'))).toEqual({ status: 'capped', limit: 10, scope: 'retained' });
  });

  it('does not match an unresolved placeholder solely by agent ID', async () => {
    const h = await setup(9);
    await h.manager.requestOpen({ kind: 'agent', entityId: 'agent-first', title: 'Agent', canonicalHref: '/chat/new' });
    expect(await h.manager.requestOpen(input('chat-new'))).toEqual({ status: 'capped', limit: 10, scope: 'retained' });
    expect(h.workspace.snapshot().entries).toHaveLength(10);
    expect(h.workspace.snapshot().entries.at(-1)?.window.resolvedConversationId).toBeFalsy();
  });

  it('rejects a genuinely new entry at cap and preserves atomic replacement', async () => {
    const h = await setup(10);
    const before = h.workspace.snapshot().entries;
    expect(await h.manager.requestOpen(input('chat-new'))).toEqual({ status: 'capped', limit: 10, scope: 'retained' });
    expect(h.workspace.snapshot().entries).toEqual(before);
    expect((await h.workspace.pinAndSelect(chat('chat-new'), true, 'conversation:chat-0')).ok).toBe(true);
    expect(h.workspace.snapshot().entries).toHaveLength(10);
    expect(h.workspace.snapshot().entries.some((e) => e.window.entityId === 'chat-0')).toBe(false);
  });

  it('reports the separate pinned-agent cap without deleting retained entries', async () => {
    const h = await setup();
    for (let i = 1; i < 10; i++) await h.workspace.pinAgent(`agent-${i}`);
    h.resolve.mockImplementation(async (id) => chat(id, 'agent-eleventh'));
    expect(await h.manager.requestOpen(input('chat-new'))).toEqual({ status: 'capped', limit: 10, scope: 'pinned-agents' });
    expect(h.workspace.snapshot().entries).toHaveLength(1);
    expect(h.workspace.snapshot().agents).toHaveLength(10);
    const before = h.workspace.snapshot().entries;
    expect(await h.workspace.pinAndSelect(chat('chat-new', 'agent-eleventh'), true, 'conversation:chat-0'))
      .toEqual({ ok: false, reason: 'capacity-pinned-agents' });
    expect(h.workspace.snapshot().entries).toEqual(before);
  });
});
