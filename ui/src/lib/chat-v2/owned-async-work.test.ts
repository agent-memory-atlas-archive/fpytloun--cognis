import { expect, it } from 'vitest';
import { OwnedAsyncWork } from '../../../e2e/owned-async-work';

it('drains a released route before allowing context disposal', async () => {
  const owner = new OwnedAsyncWork();
  let release!: () => void;
  const hold = new Promise<void>(resolve => { release = resolve; });
  const order: string[] = [];
  void owner.run('route', async () => { await hold; order.push('fulfilled'); });
  const cleanup = owner.drain().then(() => order.push('disposed'));
  expect(owner.pendingLabels).toEqual(['route']);
  expect(order).toEqual([]);
  release();
  await cleanup;
  expect(order).toEqual(['fulfilled', 'disposed']);
  expect(owner.pendingLabels).toEqual([]);
});

it('owns callback rejection and signals body failure without transport secrets', async () => {
  const owner = new OwnedAsyncWork();
  const guarded = owner.guard(new Promise<void>(() => {}));
  const assertion = expect(guarded).rejects.toThrow('route (context-disposed)');
  await owner.run('route', async () => {
    throw new Error('route.fetch: Request context disposed. Authorization: secret');
  });
  await assertion;
  expect(owner.failures).toEqual([{ label: 'route', phase: 'body', category: 'context-disposed' }]);
  expect(JSON.stringify(owner.failures)).not.toContain('secret');
});

it('retains cleanup observer rejection separately from a prior primary failure', async () => {
  const owner = new OwnedAsyncWork();
  const primary = new Error('body failed');
  owner.phase = 'cleanup';
  let observed: unknown;
  try {
    try { throw primary; }
    finally {
      owner.observe('response', Promise.reject(new Error('context disposed')));
      await owner.drain();
    }
  } catch (error) { observed = error; }
  expect(observed).toBe(primary);
  expect(owner.failures).toEqual([{ label: 'response', phase: 'cleanup', category: 'context-disposed' }]);
});

it('drains callbacks without waiting for event waiters that require context closure', async () => {
  const owner = new OwnedAsyncWork();
  let close!: (error: Error) => void;
  owner.observe('response', new Promise<void>((_resolve, reject) => { close = reject; }));
  await owner.run('route', async () => {});
  await owner.drainCallbacks();
  expect(owner.pendingLabels).toEqual(['response']);
  owner.phase = 'cleanup';
  close(new Error('context disposed'));
  await owner.drain();
  expect(owner.pendingLabels).toEqual([]);
  expect(owner.failures[0].phase).toBe('cleanup');
});
