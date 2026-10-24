import { afterEach, describe, expect, it, vi } from 'vitest';
import { RefreshCooldown, SidebarRefreshController, overlaySidebarRows, updateSidebarRow } from './sidebar-refresh';
import { SidebarRevisionAdmission } from './chat-page';
import { CoordinationUnavailableError, StaleDocumentError } from './document-coordination';

const deferred = () => {
  let resolve!: () => void;
  const promise = new Promise<void>(done => { resolve = done; });
  return { promise, resolve };
};

afterEach(() => vi.useRealTimers());

describe('sidebar refresh ownership', () => {
  it('queues opening recovery behind an aborted flight from a replaced owner', async () => {
    vi.useFakeTimers();
    const hold = deferred();
    const run = vi.fn().mockImplementationOnce(() => hold.promise).mockResolvedValue(undefined);
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    controller.setLifecycle({ scope: 'web', eligible: true, ownerSignal: new AbortController().signal });
    const old = controller.request('web');
    controller.setLifecycle({ scope: 'web', eligible: true, ownerSignal: new AbortController().signal });
    const replacement = controller.request('web', { maxAgeMs: 30_000 });
    expect(run).toHaveBeenCalledTimes(1);
    hold.resolve();
    await old;
    await vi.advanceTimersByTimeAsync(4_000);
    await replacement;
    expect(run).toHaveBeenCalledTimes(2);
    controller.dispose();
  });

  it('repairs a stale opened surface once without polling, recent reads or duplicate flights', async () => {
    vi.useFakeTimers();
    const hold = deferred();
    const run = vi.fn().mockResolvedValue(undefined);
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    await controller.request('owner/web');
    await controller.request('owner/web', { maxAgeMs: 30_000 });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(run).toHaveBeenCalledTimes(1);
    run.mockImplementationOnce(() => hold.promise);
    const opened = controller.request('owner/web', { maxAgeMs: 30_000 });
    for (let i = 0; i < 20; i++) void controller.request('owner/web', { maxAgeMs: 30_000 });
    expect(run).toHaveBeenCalledTimes(2);
    hold.resolve();
    await opened;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(run).toHaveBeenCalledTimes(2);
    controller.dispose();
  });

  it('does not let a recent surface check suppress invalidations or survive an owner change', async () => {
    vi.useFakeTimers();
    const run = vi.fn().mockResolvedValue(undefined);
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    controller.setLifecycle({ scope: 'web', eligible: true, ownerSignal: new AbortController().signal });
    await controller.request('web');
    void controller.request('web');
    await controller.request('web', { maxAgeMs: 30_000 });
    await vi.advanceTimersByTimeAsync(4_000);
    expect(run).toHaveBeenCalledTimes(2);
    controller.setLifecycle({ scope: 'web', eligible: true, ownerSignal: new AbortController().signal });
    void controller.request('web', { maxAgeMs: 30_000 });
    await vi.advanceTimersByTimeAsync(4_000);
    expect(run).toHaveBeenCalledTimes(3);
    controller.dispose();
  });

  it.each(['during', 'after'])('keeps local failure pacing for urgent intents arriving %s a failed flight', async when => {
    vi.useFakeTimers();
    let reject!: (error: unknown) => void;
    const hold = new Promise<void>((_resolve, fail) => { reject = fail; });
    const run = vi.fn().mockImplementationOnce(() => hold).mockResolvedValue(undefined);
    const cooldown = new RefreshCooldown();
    const controller = new SidebarRefreshController(run, cooldown);
    const first = controller.request('owner/web');
    if (when === 'during') void controller.request('owner/web', { urgent: true });
    reject({ status: 503 });
    await first;
    if (when === 'after') void controller.request('owner/web', { urgent: true });
    expect(cooldown.until).toBe(0);
    expect(run).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3_999);
    expect(run).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(run).toHaveBeenCalledTimes(2);
    controller.dispose();
  });

  it('keeps ordinary 503 pacing local while another resource remains immediately admissible', async () => {
    vi.useFakeTimers();
    const cooldown = new RefreshCooldown();
    const failures = vi.fn().mockRejectedValue({ status: 503 });
    const other = vi.fn().mockResolvedValue(undefined);
    const a = new SidebarRefreshController(failures, cooldown);
    const b = new SidebarRefreshController(other, cooldown);
    await a.request('owner/web');
    void b.request('owner/web', { urgent: true });
    expect(cooldown.until).toBe(0);
    expect(other).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3_999);
    expect(failures).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(failures).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4_000);
    expect(failures).toHaveBeenCalledTimes(3);
    for (let i = 0; i < 100; i++) void a.request('owner/web', { urgent: true });
    await vi.advanceTimersByTimeAsync(59_999);
    expect(failures).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(failures).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(4_000);
    expect(failures).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(56_000);
    expect(failures).toHaveBeenCalledTimes(5);
    expect(other).toHaveBeenCalledTimes(1);
    expect(cooldown.until).toBe(0);
    a.dispose(); b.dispose();
  });

  it('shares an explicit 503 Retry-After across independent resources', async () => {
    vi.useFakeTimers();
    const cooldown = new RefreshCooldown();
    const failure = vi.fn().mockRejectedValue({ status: 503, retryAfterMs: 8_000 });
    const other = vi.fn().mockResolvedValue(undefined);
    const a = new SidebarRefreshController(failure, cooldown);
    const b = new SidebarRefreshController(other, cooldown);
    await a.request('owner/web');
    void b.request('owner/web', { manual: true, urgent: true });
    await vi.advanceTimersByTimeAsync(7_999);
    expect(failure).toHaveBeenCalledTimes(1);
    expect(other).not.toHaveBeenCalled();
    a.dispose();
    await vi.advanceTimersByTimeAsync(1);
    expect(other).toHaveBeenCalledTimes(1);
    b.dispose();
  });

  it('shares a minimum four-second cooldown for 429 without Retry-After', async () => {
    vi.useFakeTimers();
    const cooldown = new RefreshCooldown();
    const other = vi.fn().mockResolvedValue(undefined);
    const a = new SidebarRefreshController(vi.fn().mockRejectedValue({ status: 429 }), cooldown);
    const b = new SidebarRefreshController(other, cooldown);
    await a.request('owner/web');
    expect(cooldown.until).toBe(Date.now() + 4_000);
    void b.request('owner/web', { urgent: true });
    a.dispose();
    await vi.advanceTimersByTimeAsync(3_999);
    expect(other).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(other).toHaveBeenCalledTimes(1);
    b.dispose();
  });

  it.each([401, 403, 500])('shares canonical Retry-After even on status %i', async status => {
    vi.useFakeTimers();
    const cooldown = new RefreshCooldown();
    const other = vi.fn().mockResolvedValue(undefined);
    const a = new SidebarRefreshController(
      vi.fn().mockRejectedValue({ status, retryAfterMs: 12_000 }), cooldown,
    );
    const b = new SidebarRefreshController(other, cooldown);
    await a.request('owner/web');
    void b.request('owner/web', { urgent: true });
    a.dispose();
    await vi.advanceTimersByTimeAsync(11_999);
    expect(other).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(other).toHaveBeenCalledTimes(1);
    b.dispose();
  });

  it.each([NaN, Infinity, -1])('does not turn a noncanonical retry hint %s into shared admission', async retryAfterMs => {
    vi.useFakeTimers();
    const cooldown = new RefreshCooldown();
    const other = vi.fn().mockResolvedValue(undefined);
    const failure = vi.fn().mockRejectedValueOnce({ status: 503, retryAfterMs })
      .mockImplementation(() => new Promise<void>(() => {}));
    const a = new SidebarRefreshController(failure, cooldown);
    const b = new SidebarRefreshController(other, cooldown);
    await a.request('owner/web');
    void b.request('owner/web', { urgent: true });
    expect(cooldown.until).toBe(0);
    expect(other).toHaveBeenCalledTimes(1);
    a.dispose(); b.dispose();
  });

  it('collapses reconnect and missing-row bursts into one trailing full refresh', async () => {
    vi.useFakeTimers();
    const hold = deferred();
    const run = vi.fn().mockImplementationOnce(() => hold.promise).mockResolvedValue(undefined);
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    const first = controller.request('owner/web');
    for (let i = 0; i < 100; i++) void controller.request('owner/web', { full: i === 30 });
    expect(run).toHaveBeenCalledTimes(1);
    hold.resolve();
    await first; // The first caller completes even while a trailing intent exists.
    await vi.advanceTimersByTimeAsync(3_999);
    expect(run).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(run).toHaveBeenCalledTimes(2);
    expect(run.mock.calls[1][0].full).toBe(true);
    controller.dispose();
  });

  it('aborts old scope and serializes latest scope without overlap', async () => {
    vi.useFakeTimers();
    const hold = deferred();
    const run = vi.fn().mockImplementationOnce(() => hold.promise).mockResolvedValue(undefined);
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    void controller.request('owner/web');
    void controller.request('owner/project-a', { urgent: true });
    void controller.request('owner/project-b', { urgent: true, full: true });
    expect(run.mock.calls[0][0].signal.aborted).toBe(true);
    expect(run).toHaveBeenCalledTimes(1);
    hold.resolve();
    await vi.advanceTimersByTimeAsync(0);
    expect(run).toHaveBeenCalledTimes(2);
    expect(run.mock.calls[1][0].scope).toBe('owner/project-b');
    controller.dispose();
  });

  it.each([429, 503])('bounds %i recovery despite events and honors shared Retry-After', async status => {
    vi.useFakeTimers();
    const cooldown = new RefreshCooldown();
    const run = vi.fn().mockRejectedValue({ status, retryAfterMs: 10_000 });
    const controller = new SidebarRefreshController(run, cooldown);
    await controller.request('owner/web');
    for (let i = 0; i < 100; i++) void controller.request('owner/web', { urgent: true });
    await vi.advanceTimersByTimeAsync(9_999);
    expect(run).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(run).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(run).toHaveBeenCalledTimes(3);
    for (let i = 0; i < 100; i++) void controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(59_999);
    expect(run).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(run).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(10_000);
    const waiting = vi.fn().mockResolvedValue(undefined);
    const waitingController = new SidebarRefreshController(waiting, cooldown);
    await waitingController.request('owner/web');
    expect(waiting).toHaveBeenCalledTimes(1);
    run.mockResolvedValue(undefined);
    await controller.request('owner/web', { manual: true, urgent: true });
    expect(run).toHaveBeenCalledTimes(5);
    controller.dispose();
    waitingController.dispose();
  });

  it('probes without another event and never replenishes the failed burst', async () => {
    vi.useFakeTimers();
    const run = vi.fn().mockRejectedValue({ status: 503 });
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    await controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(8_000);
    expect(run).toHaveBeenCalledTimes(3);
    for (let i = 0; i < 100; i++) void controller.request('owner/web', { urgent: true });
    await vi.advanceTimersByTimeAsync(59_999);
    expect(run).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(run).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(4_000);
    expect(run).toHaveBeenCalledTimes(4);
    run.mockResolvedValue(undefined);
    await vi.advanceTimersByTimeAsync(56_000);
    expect(run).toHaveBeenCalledTimes(5);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(run).toHaveBeenCalledTimes(5);
    controller.dispose();
  });

  it('honors a longer shared cooldown even for a half-open foreground request', async () => {
    vi.useFakeTimers();
    const cooldown = new RefreshCooldown();
    const run = vi.fn().mockRejectedValue({ status: 429 });
    const controller = new SidebarRefreshController(run, cooldown);
    await controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(8_000);
    cooldown.until = Date.now() + 120_000;
    void controller.request('owner/web', { urgent: true });
    await vi.advanceTimersByTimeAsync(119_999);
    expect(run).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(run).toHaveBeenCalledTimes(4);
    controller.dispose();
  });

  it('suspends recovery while ineligible without losing intent or restarting the budget', async () => {
    vi.useFakeTimers();
    const run = vi.fn().mockRejectedValue({ status: 503 });
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    controller.setLifecycle({ scope: 'owner/web', eligible: true });
    await controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(8_000);
    controller.setLifecycle({ scope: 'owner/web', eligible: false });
    for (let i = 0; i < 100; i++) void controller.request('owner/web', { urgent: true });
    await vi.advanceTimersByTimeAsync(180_000);
    expect(run).toHaveBeenCalledTimes(3);
    controller.setLifecycle({ scope: 'owner/web', eligible: true });
    await vi.advanceTimersByTimeAsync(0);
    expect(run).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(59_999);
    expect(run).toHaveBeenCalledTimes(4);
    controller.dispose();
  });

  it('revokes flights and delayed probes without allowing stale owner intents', async () => {
    vi.useFakeTimers();
    const owner = new AbortController();
    const hold = deferred();
    const run = vi.fn().mockImplementationOnce(() => hold.promise).mockResolvedValue(undefined);
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    controller.setLifecycle({ scope: 'owner/web', eligible: true, ownerSignal: owner.signal });
    void controller.request('owner/web');
    owner.abort();
    expect(run.mock.calls[0][0].signal.aborted).toBe(true);
    hold.resolve();
    await vi.advanceTimersByTimeAsync(0);
    void controller.request('owner/web', { urgent: true, manual: true });
    await vi.advanceTimersByTimeAsync(180_000);
    expect(run).toHaveBeenCalledTimes(1);
    controller.dispose();
  });

  it.each([401, 403])('never automatically retries or probes authorization failure %i', async status => {
    vi.useFakeTimers();
    const run = vi.fn().mockRejectedValue({ status });
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    await controller.request('owner/web');
    for (let i = 0; i < 100; i++) void controller.request('owner/web', { urgent: true });
    await vi.advanceTimersByTimeAsync(180_000);
    expect(run).toHaveBeenCalledTimes(1);
    controller.dispose();
  });

  it('an explicit retry after authorization failure still honors Retry-After', async () => {
    vi.useFakeTimers();
    const run = vi.fn().mockRejectedValueOnce({ status: 403, retryAfterMs: 120_000 })
      .mockResolvedValue(undefined);
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    await controller.request('owner/web');
    const done = controller.request('owner/web', { manual: true, urgent: true });
    await vi.advanceTimersByTimeAsync(119_999);
    expect(run).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await done;
    expect(run).toHaveBeenCalledTimes(2);
    controller.dispose();
  });

  it.each([new StaleDocumentError(), new CoordinationUnavailableError()])(
    'never probes revoked or unavailable ownership: %s', async error => {
      vi.useFakeTimers();
      const run = vi.fn().mockRejectedValue(error);
      const controller = new SidebarRefreshController(run, new RefreshCooldown());
      await controller.request('owner/web');
      for (let i = 0; i < 100; i++) void controller.request('owner/web');
      await vi.advanceTimersByTimeAsync(180_000);
      expect(run).toHaveBeenCalledTimes(1);
      controller.dispose();
    },
  );

  it('a new owner cancels a pending probe even when its account scope is unchanged', async () => {
    vi.useFakeTimers();
    const oldOwner = new AbortController();
    const run = vi.fn().mockRejectedValue({ status: 503 });
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    controller.setLifecycle({ scope: 'owner/web', eligible: true, ownerSignal: oldOwner.signal });
    await controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(8_000);
    oldOwner.abort();
    await vi.advanceTimersByTimeAsync(180_000);
    expect(run).toHaveBeenCalledTimes(3);
    controller.setLifecycle({
      scope: 'owner/web', eligible: true, ownerSignal: new AbortController().signal,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(run).toHaveBeenCalledTimes(3);
    run.mockResolvedValue(undefined);
    await controller.request('owner/web', { urgent: true });
    expect(run).toHaveBeenCalledTimes(4);
    controller.dispose();
  });

  it('cancels the old probe when lifecycle scope changes and aborts on disposal', async () => {
    vi.useFakeTimers();
    const run = vi.fn().mockRejectedValue({ status: 503 });
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    controller.setLifecycle({ scope: 'owner/web', eligible: true });
    await controller.request('owner/web');
    await vi.advanceTimersByTimeAsync(8_000);
    controller.setLifecycle({ scope: 'owner/project', eligible: true });
    run.mockResolvedValue(undefined);
    await controller.request('owner/web', { urgent: true });
    expect(run).toHaveBeenCalledTimes(3);
    const done = controller.request('owner/project', { urgent: true });
    await vi.advanceTimersByTimeAsync(4_000);
    await done;
    expect(run).toHaveBeenCalledTimes(4);
    expect(run.mock.calls[3][0].scope).toBe('owner/project');
    controller.dispose();
    await vi.advanceTimersByTimeAsync(180_000);
    expect(run).toHaveBeenCalledTimes(4);
  });

  it('lets Waiting recover independently and does not bypass a shared cooldown', async () => {
    vi.useFakeTimers();
    const cooldown = new RefreshCooldown();
    const sidebar = new SidebarRefreshController(
      vi.fn().mockRejectedValue({ status: 503, retryAfterMs: 8_000 }), cooldown,
    );
    await sidebar.request('owner/web');
    const waiting = vi.fn().mockResolvedValue(undefined);
    const controller = new SidebarRefreshController(waiting, cooldown);
    const done = controller.request('owner/web', { manual: true, urgent: true });
    expect(waiting).not.toHaveBeenCalled();
    sidebar.dispose();
    await vi.advanceTimersByTimeAsync(8_000);
    await done;
    expect(waiting).toHaveBeenCalledTimes(1);
    controller.dispose();
  });

  it('applies useful snapshots under churn without overwriting pushes or resurrecting removals', () => {
    const admission = new SidebarRevisionAdmission();
    admission.selectScope('owner/web');
    admission.recordProjection('10', ['row-a', 'row-removed']);
    admission.admitPush('row-a', '12');
    admission.admitPush('row-removed', '13');
    admission.observeInvalidation('14');
    expect(admission.admitProjection('11')).toEqual({ apply: true, reconcile: true });
    const rows = overlaySidebarRows(
      [{ conversation_id: 'row-a', title: 'stale' }, { conversation_id: 'row-removed', title: 'removed' }],
      [{ conversation_id: 'row-a', title: 'new' }],
      admission.newerConversationIds('11'),
    );
    expect(rows).toEqual([{ conversation_id: 'row-a', title: 'new' }]);
    admission.recordProjection('11', ['row-a', 'row-removed']);
    expect(admission.admitPush('row-a', '12').apply).toBe(false);
    expect(admission.authoritativeRestCursor).toBe('11');
    expect(admission.needsReconciliation).toBe(true);
    expect(admission.admitProjection('10').apply).toBe(false);
    admission.selectScope('owner/project');
    expect(admission.authoritativeRestCursor).toBeNull();
  });

  it('disposes timers and aborts flights', async () => {
    vi.useFakeTimers();
    const run = vi.fn().mockRejectedValue({ status: 429 });
    const controller = new SidebarRefreshController(run, new RefreshCooldown());
    await controller.request('owner/web');
    controller.dispose();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it('retains pushed updates and removals across cached scope round trips', () => {
    const cache = new Map([
      ['all', [{ conversation_id: 'removed-row', title: 'old' }, { conversation_id: 'updated-row', title: 'old' }]],
      ['web', [{ conversation_id: 'removed-row', title: 'old' }, { conversation_id: 'updated-row', title: 'old' }]],
    ]);
    for (const [key, rows] of cache) {
      const updated = updateSidebarRow(rows, 'updated-row', row => ({ ...row, title: 'new' }));
      cache.set(key, updateSidebarRow(updated, 'removed-row', () => null));
    }
    for (const rows of cache.values()) {
      expect(rows).toEqual([{ conversation_id: 'updated-row', title: 'new' }]);
    }
  });
});
