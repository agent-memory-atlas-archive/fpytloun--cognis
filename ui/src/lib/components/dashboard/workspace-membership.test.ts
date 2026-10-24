import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/svelte';
import { afterEach, expect, it } from 'vitest';
import { ConversationWorkspace } from '$lib/dashboard/conversation-workspace';
import { WorkspaceManager } from '$lib/dashboard/workspace';
import { WorkspaceOwner, WorkspaceReplica } from '$lib/native/workspace-protocol';
import type { Conversation } from '$lib/types/api';
import WorkspaceWindowFixture from './WorkspaceWindow.test-fixture.svelte';

afterEach(cleanup);
const safe = { x: 0, y: 0, width: 1440, height: 900 };
const conversation = (id: string) => ({
  conversation_id: id, agent_id: 'agent-race', title: id, status: 'idle', project_id: 'project-one'
}) as Conversation;

it.each(['before', 'after'])('real dashboard Close accepted %s a deferred replica pin respects acceptance order', async (order) => {
  const workspace = new ConversationWorkspace();
  workspace.setOwner('owner@race.test', null);
  await workspace.pin(conversation('race'));
  const manager = new WorkspaceManager('desktop', safe);
  const unbind = workspace.bind(manager, 'project-one', 'race-layout');
  let resolve!: () => void;
  let requested = false;
  let deferLease = false;
  const lease = new Promise<void>((done) => { resolve = done; });
  const scope = { profile: 'https://race.test', account: 'owner@race.test', authEpoch: 'auth-race' };
  const replicaWorkspace = new ConversationWorkspace(true);
  let replica!: WorkspaceReplica;
  const owner = new WorkspaceOwner(scope, 'main-race', 'epoch-race', workspace,
    () => ({ workspace: workspace.snapshot(), agents: [], conversations: {}, background: [] }),
    async (id) => conversation(id),
    async () => { if (deferLease) { requested = true; await lease; } },
    (frame) => replica.receive(frame));
  workspace.setCommand((intent) => owner.submit(intent));
  replica = new WorkspaceReplica(scope, 'replica-race', replicaWorkspace, () => {}, (frame) => owner.receive(frame));
  replica.hello();
  render(WorkspaceWindowFixture, { window: manager.snapshot()[0], manager });
  if (order === 'before') {
    await fireEvent.click(screen.getByTitle('Close'));
    await waitFor(() => expect(workspace.snapshot().entries).toHaveLength(0));
  }
  // Retained restores skip metadata; the lease remains their async admission boundary.
  deferLease = true;
  const pending = replicaWorkspace.execute({ type: 'pin', conversationId: 'race', select: true });
  await waitFor(() => expect(requested).toBe(true));
  const unrelated = replicaWorkspace.execute({ type: 'pin', conversationId: 'unrelated', select: true });
  if (order === 'after') await fireEvent.click(screen.getByTitle('Close'));
  resolve();
  await Promise.all([pending, unrelated]);
  await waitFor(() => expect(workspace.snapshot().entries.map((entry) => entry.window.entityId))
    .toEqual(order === 'after' ? ['unrelated'] : ['race', 'unrelated']));
  expect((await replicaWorkspace.execute({ type: 'select', agentId: 'agent-race', key: 'conversation:race' })).ok).toBe(order === 'before');
  unbind(); replica.stop(); owner.stop();
});

it('filtered Close and stale layout cannot mutate another project or restore missing membership', async () => {
  const workspace = new ConversationWorkspace();
  workspace.setOwner('owner@race.test', null);
  await workspace.pin(conversation('first'));
  await workspace.pin({ ...conversation('second'), project_id: 'project-two' });
  const manager = new WorkspaceManager('desktop', safe);
  const stop = workspace.bind(manager, 'project-one', 'project-one-layout');
  const stale = manager.snapshot();
  manager.minimize('conversation:first');
  expect(workspace.snapshot().entries.map((entry) => entry.window.entityId)).toEqual(['first', 'second']);
  render(WorkspaceWindowFixture, { window: stale[0], manager });
  await fireEvent.click(screen.getByTitle('Close'));
  await waitFor(() => expect(workspace.snapshot().entries.map((entry) => entry.window.entityId)).toEqual(['second']));
  manager.replaceProjection(stale);
  expect(workspace.snapshot().entries.map((entry) => entry.window.entityId)).toEqual(['second']);
  expect(manager.snapshot()).toEqual([]);
  stop();
});

it('returns honest capacity and stale-selection failures through owner result transport', async () => {
  const workspace = new ConversationWorkspace(), replicaWorkspace = new ConversationWorkspace(true);
  workspace.setOwner('owner@race.test', null);
  for (let i = 0; i < 10; i++) await workspace.pinAgent(`agent-${i}`);
  const scope = { profile: 'https://race.test', account: 'owner@race.test', authEpoch: 'auth-race' };
  let replica!: WorkspaceReplica;
  const owner = new WorkspaceOwner(scope, 'main-race', 'epoch-race', workspace,
    () => ({ workspace: workspace.snapshot(), agents: [], conversations: {}, background: [] }),
    async (id) => conversation(id), async () => {}, (frame) => replica.receive(frame));
  replica = new WorkspaceReplica(scope, 'replica-race', replicaWorkspace, () => {}, (frame) => owner.receive(frame));
  replica.hello();
  expect(await replicaWorkspace.execute({ type: 'agent', agentId: 'agent-eleventh', pinned: true }))
    .toEqual({ ok: false, reason: 'capacity-pinned-agents' });
  expect(await replicaWorkspace.execute({ type: 'select', agentId: 'agent-0', key: 'conversation:missing' }))
    .toEqual({ ok: false, reason: 'missing-selection' });
  expect(await replicaWorkspace.execute({ type: 'unpin', key: 'conversation:missing' })).toEqual({ ok: true });
  replica.stop(); owner.stop();
});

it('keeps the actual agent window full-page link before resolve, after acknowledgement and after restore', async () => {
  const workspace = new ConversationWorkspace();
  localStorage.clear();
  workspace.setOwner('owner@race.test', localStorage);
  const manager = new WorkspaceManager('desktop', safe);
  const stop = workspace.bind(manager, null, 'agent-link-layout');
  await manager.requestOpen({ kind: 'agent', entityId: 'agent-race', title: 'Agent',
    canonicalHref: '/chat/new?agent=agent-race' });
  const rendered = render(WorkspaceWindowFixture, { window: manager.snapshot()[0], manager });
  expect(screen.getByRole('link', { name: 'Open full page' })).toHaveAttribute('href', '/chat/new?agent=agent-race');
  const result = await workspace.resolveAgent('agent:agent-race', conversation('resolved'));
  expect(result.ok).toBe(true);
  await rendered.rerender({ window: manager.snapshot()[0], manager });
  expect(screen.getByRole('link', { name: 'Open full page' })).toHaveAttribute('href', '/chat/resolved');
  stop(); cleanup();
  const restored = new ConversationWorkspace(), restoredManager = new WorkspaceManager('desktop', safe);
  restored.setOwner('owner@race.test', localStorage);
  const stopRestored = restored.bind(restoredManager, null, 'agent-link-layout');
  render(WorkspaceWindowFixture, { window: restoredManager.snapshot()[0], manager: restoredManager });
  expect(screen.getByRole('link', { name: 'Open full page' })).toHaveAttribute('href', '/chat/resolved');
  stopRestored();
});
