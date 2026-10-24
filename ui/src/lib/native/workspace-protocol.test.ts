import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConversationWorkspace, retainedConversationId } from '$lib/dashboard/conversation-workspace';
import type { Conversation } from '$lib/types/api';
import { WorkspaceOwner, WorkspaceReplica, type WorkspaceFrame, type WorkspaceProjection } from './workspace-protocol';

const scope = { profile: 'https://workspace.test', account: 'owner@workspace.test', authEpoch: 'auth-first' };
const conversation = (id: string) => ({ conversation_id: id, agent_id: 'agent_first', title: id, status: 'idle' }) as Conversation;
const settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
afterEach(() => vi.useRealTimers());
function setup() {
  const storage = { getItem: vi.fn(() => null), setItem: vi.fn() } as unknown as Storage;
  const workspace = new ConversationWorkspace();
  workspace.setOwner(scope.account, storage);
  const copies = [new ConversationWorkspace(true), new ConversationWorkspace(true)];
  const outgoing: WorkspaceFrame[] = [], incoming: WorkspaceFrame[] = [];
  let deliver = true;
  const replicas: WorkspaceReplica[] = [];
  let owner = makeOwner('owner-first');
  function makeOwner(epoch: string) {
    return new WorkspaceOwner(scope, 'main-doc', epoch, workspace,
      (): WorkspaceProjection => ({ workspace: workspace.snapshot(), agents: [], conversations: {}, background: [] }),
      async (id) => conversation(id), async () => {}, (frame) => {
        outgoing.push(frame);
        if (deliver) replicas.forEach((replica) => replica.receive(structuredClone(frame)));
      });
  }
  for (let i = 0; i < 2; i++) {
    replicas.push(new WorkspaceReplica(scope, `replica-${i}`, copies[i], () => {}, (frame) => {
      incoming.push(frame); owner.receive(structuredClone(frame));
    }, 50));
  }
  owner.publish();
  return { workspace, storage, copies, replicas, outgoing, incoming,
    get owner() { return owner; }, set deliver(value: boolean) { deliver = value; },
    restart() { owner.stop(); replicas.forEach((r) => r.reset()); owner = makeOwner('owner-second'); owner.publish(); },
    stop() { owner.stop(); replicas.forEach((r) => r.stop()); }
  };
}
describe('resident workspace mutation authority', () => {
  it('transports precise capacity reasons in only the existing ok/key/reason envelope', async () => {
    const h = setup();
    for (let i = 0; i < 10; i++) await h.workspace.pin(conversation(`conv_${i}`));
    const retained = await h.copies[0].pinAndSelect(conversation('conv_overflow'));
    expect(retained).toEqual({ ok: false, reason: 'capacity-retained' });
    await h.workspace.unpin('conversation:conv_0');
    for (let i = 1; i < 10; i++) await h.workspace.pinAgent(`agent_${i}`);
    const agents = await h.copies[0].execute({ type: 'agent', agentId: 'agent_overflow', pinned: true });
    expect(agents).toEqual({ ok: false, reason: 'capacity-pinned-agents' });
    for (const frame of h.outgoing.filter((frame) => frame.result)) {
      expect(Object.keys(frame.result!).every((key) => ['ok', 'key', 'reason'].includes(key))).toBe(true);
      expect(typeof frame.result!.ok).toBe('boolean');
    }
    h.stop();
  });
  it('serializes simultaneous pins and selection without replica writes', async () => {
    const h = setup();
    const [first, second] = await Promise.all(h.copies.map((copy, i) => copy.pinAndSelect(conversation(`conv_${i}`))));
    expect(first.ok && second.ok).toBe(true);
    expect(h.workspace.snapshot().entries.map((entry) => retainedConversationId(entry.window))).toEqual(['conv_0', 'conv_1']);
    expect(h.copies[0].snapshot()).toEqual(h.copies[1].snapshot());
    expect(h.copies[0].snapshot()).toEqual(h.workspace.snapshot());
    h.copies[0].setOwner('wrong@workspace.test', h.storage);
    h.copies[0].pin(conversation('not_admitted'));
    expect(h.copies[0].snapshot()).toEqual(h.workspace.snapshot());
    h.stop();
  });
  it('waits for the authoritative pin-and-select result and never resurrects stale unpins', async () => {
    const h = setup();
    h.deliver = false;
    let acknowledged = false;
    const pending = h.copies[0].pinAndSelect(conversation('conv_first')).then((result) => { acknowledged = true; return result; });
    await settle();
    expect(acknowledged).toBe(false);
    expect(h.copies[0].snapshot().entries).toEqual([]);
    const result = h.outgoing.find((frame) => frame.kind === 'result')!;
    h.replicas[0].receive(result);
    expect((await pending).key).toBe('conversation:conv_first');
    h.deliver = true;
    await h.copies[1].execute({ type: 'unpin', key: 'conversation:conv_first' });
    const writes = vi.mocked(h.storage.setItem).mock.calls.length;
    h.owner.receive(h.incoming.find((frame) => frame.kind === 'command')!);
    h.replicas[0].receive(result);
    await settle();
    expect(h.workspace.snapshot().entries).toEqual([]);
    expect(h.copies[0].snapshot().entries).toEqual([]);
    expect(vi.mocked(h.storage.setItem).mock.calls.length).toBe(writes);
    h.stop();
  });
  it('queries a timed out ID instead of replaying its mutation and reconciles from owner snapshot', async () => {
    vi.useFakeTimers();
    const h = setup(); h.deliver = false;
    const pending = h.copies[0].pinAndSelect(conversation('conv_uncertain'));
    await settle();
    await vi.advanceTimersByTimeAsync(50);
    expect(h.incoming.filter((f) => f.kind === 'command')).toHaveLength(1);
    expect(h.incoming.filter((f) => f.kind === 'query')).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(50);
    expect(await pending).toEqual({ ok: false, reason: 'uncertain' });
    const result = h.outgoing.findLast((f) => f.kind === 'result')!;
    h.replicas[0].receive(result);
    expect(h.copies[0].snapshot().entries).toHaveLength(1);
    h.stop();
  });
  it('fences owner restart, stale scope/projections and unavailable authority', async () => {
    const h = setup();
    await h.copies[0].pinAndSelect(conversation('conv_first'));
    const stale = h.outgoing.at(-1)!;
    h.restart();
    await h.copies[1].execute({ type: 'unpin', key: 'conversation:conv_first' });
    h.replicas[0].receive({ ...stale, revision: 9999 });
    expect(h.copies[0].snapshot().entries).toEqual([]);
    h.owner.receive({ ...h.incoming.find((f) => f.kind === 'command')!, account: 'other@workspace.test' });
    await settle();
    expect(h.workspace.snapshot().entries).toEqual([]);
    h.replicas[0].reset();
    expect(await h.copies[0].pinAndSelect(conversation('not_admitted'))).toEqual({ ok: false, reason: 'owner-unavailable' });
    h.stop();
  });
  it('does not admit reordered commands or execute an evicted ID twice', async () => {
    const h = setup();
    await h.copies[0].pinAndSelect(conversation('conv_first'));
    const frame = h.incoming.find((f) => f.kind === 'command')!;
    h.owner.receive({ ...frame, id: 50, intent: { type: 'unpin', key: 'conversation:conv_first' } });
    h.owner.receive({ ...frame, id: 49, intent: { type: 'pin', conversationId: 'not_admitted', select: true } });
    await settle();
    expect(h.workspace.snapshot().entries).toEqual([]);
    expect(h.outgoing.some((f) => f.id === 49 && f.result?.reason === 'outcome-expired')).toBe(true);
    h.stop();
  });
});
