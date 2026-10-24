import { offlineCache } from '$lib/offline/cache';
import { withRequestDeadline } from '$lib/api/fetch';
import { documentCoordination } from '$lib/document-coordination';
import { chatV2Api, type ChatV2ApiClient } from './api';
import { ChatV2Store } from './store.svelte';
import type { ChatV2ClientState } from './sync-engine';
import type { ChatSnapshot, TimelineBackfillResponse, TimelineScope } from './types';
import type { WebSocketScopeInvalidatedEvent } from '$lib/types/api';
import { invalidatesTimeline } from './invalidation';

type TimelineApi = Pick<ChatV2ApiClient, 'snapshot' | 'sync' | 'timeline'>;
export type TimelinePhase = 'idle' | 'loading' | 'ready' | 'error' | 'identity-required';
export class TimelineOwnershipError extends Error {
  readonly code = 'timeline_owner_changed';
  constructor(message = 'Your account or server context changed. Verify your session, then try again.') {
    super(message);
    this.name = 'TimelineOwnershipError';
  }
}
const RESIDENT_LIMIT = 20;
const MAX_SYNC_PAGES = 8;
const registry = new Map<string, TimelineController>();

async function yieldBeforeProjection(): Promise<void> {
  await new Promise<void>((resolve) => {
    let task: ReturnType<typeof setTimeout> | undefined;
    const finish = () => {
      clearTimeout(watchdog);
      if (task !== undefined) clearTimeout(task);
      resolve();
    };
    const watchdog = setTimeout(finish, 100);
    const scheduler = (globalThis as typeof globalThis & { scheduler?: { yield?: () => Promise<void> } }).scheduler;
    if (scheduler?.yield) {
      try { void scheduler.yield().then(finish, finish); } catch { task = setTimeout(finish, 0); }
    } else task = setTimeout(finish, 0);
  });
}

function usable(state: ChatV2ClientState | null | undefined, scope: TimelineScope): state is ChatV2ClientState {
  return Boolean(state?.cursor && Array.isArray(state.timelineItems)
    && (!state.scopeKey || state.scopeKey === scope.key)
    && (!scope.conversation_id || !state.conversationId || state.conversationId === scope.conversation_id));
}

async function budget<T>(operation: Promise<T>, fallback: T): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([operation.catch(() => fallback), new Promise<T>((resolve) => {
      timer = setTimeout(() => resolve(fallback), 400);
    })]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

interface Flight<T> {
  controller: AbortController;
  promise: Promise<T>;
  consumers: number;
  forceSnapshot?: boolean;
  dirty?: boolean;
}

/** One timeline owner per account and scope. Views own scroll and WS references,
 * never cached timeline copies or bootstrap policy. No timers run while idle.
 */
export class TimelineController {
  readonly store: ChatV2Store;
  private disposeProjection: () => void;
  private stopCoordination: () => void;
  phase: TimelinePhase = $state('idle');
  reconciled = $state(false);
  error: unknown = $state.raw(null);
  private valid = true;
  private ownership = new AbortController();
  get ownerSignal(): AbortSignal { return this.ownership.signal; }

  onInvalidated(listener: (error: TimelineOwnershipError) => void): () => void {
    const notify = () => listener(this.ownerSignal.reason);
    if (this.ownerSignal.aborted) notify();
    else this.ownerSignal.addEventListener('abort', notify, { once: true });
    return () => this.ownerSignal.removeEventListener('abort', notify);
  }
  private references = 0;
  private hydration: Promise<void> | null = null;
  private persistedRevision = -1;
  private lineageGeneration = 0;
  private flight: Flight<ChatSnapshot | null> | null = null;
  private backfills = new Map<string, Flight<TimelineBackfillResponse | null>>();

  constructor(readonly scope: TimelineScope, readonly owner: string | null, private readonly api: TimelineApi) {
    let store!: ChatV2Store;
    // Derived projections must outlive the component that first opens a scope.
    this.disposeProjection = $effect.root(() => { store = new ChatV2Store(); });
    this.store = store;
    this.stopCoordination = documentCoordination().onInvalidated(() => this.invalidate());
  }

  get retained(): boolean { return this.references > 0 || this.flight !== null || this.backfills.size > 0; }
  get hasConsumers(): boolean { return this.references > 0; }
  usesProvider(api: TimelineApi): boolean { return this.api === api; }
  get current(): boolean { return this.valid && this.owner === offlineCache.currentOwner; }

  retain(): void { this.references += 1; }
  release(): void {
    this.references = Math.max(0, this.references - 1);
    if (!this.owner && this.references === 0) this.invalidate();
    trim();
  }

  invalidate(): void {
    if (!this.valid) return;
    this.valid = false;
    this.stopCoordination();
    const key = `${this.owner}\u0000${this.scope.key}`;
    if (registry.get(key) === this) registry.delete(key);
    const error = new TimelineOwnershipError();
    this.store.reset();
    this.reconciled = false;
    this.phase = 'identity-required';
    this.error = error;
    this.ownership.abort(error);
    this.flight?.controller.abort(error);
    for (const flight of this.backfills.values()) flight.controller.abort(error);
    this.disposeProjection();
  }

  private assertCurrent(signal?: AbortSignal): void {
    if (!this.current) throw this.ownerSignal.reason ?? new TimelineOwnershipError();
    signal?.throwIfAborted();
  }

  admitInvalidation(event: WebSocketScopeInvalidatedEvent): boolean {
    if (!this.current || !invalidatesTimeline(this.store.snapshot.scope ?? this.scope, event)) return false;
    this.reconciled = false;
    if (this.flight) this.flight.dirty = true;
    return true;
  }

  private replaceLineage(): void {
    this.lineageGeneration += 1;
    for (const flight of this.backfills.values()) flight.controller.abort();
    this.backfills.clear();
  }

  async hydrate(): Promise<void> {
    this.assertCurrent();
    if (this.store.snapshot.cursor || !this.owner) return;
    this.hydration ??= withRequestDeadline(() => this.readDevice(), { signal: this.ownerSignal, timeoutMs: 0 });
    await this.hydration;
  }

  private async readDevice(): Promise<void> {
    const watermark = this.store.refreshWatermark();
    const canonical = await budget(offlineCache.get<{ state: ChatV2ClientState }>('timeline', this.scope.key, this.owner), null);
    let state = canonical?.state;
    // Read-only migration for deployed v1 device records. Remove this reader
    // when pre-timeline-registry device caches are no longer supported. All new
    // timeline writes use `timeline`; route records now contain metadata only.
    if (!state) {
      const [scoped, page] = await Promise.all([
        budget(offlineCache.get<{ state: ChatV2ClientState; savedAt: number }>('scoped-view', this.scope.key, this.owner), null),
        this.scope.kind === 'conversation' && this.scope.conversation_id
          ? budget(offlineCache.get<{ chatV2State?: ChatV2ClientState; fetchedAt: number }>('conversation-view', this.scope.conversation_id, this.owner), null)
          : null,
      ]);
      state = (scoped?.savedAt ?? 0) >= (page?.fetchedAt ?? 0)
        ? scoped?.state ?? page?.chatV2State : page?.chatV2State ?? scoped?.state;
    }
    this.assertCurrent();
    if (usable(state, this.scope) && this.store.refreshWatermark().mutationRevision === watermark.mutationRevision) {
      this.store.restoreState(state);
      this.store.settleRuntimeOverlay();
      this.replaceLineage();
      this.phase = 'ready';
      this.persist();
    }
  }

  persist(): void {
    if (!this.current || !this.owner || !usable(this.store.snapshot, this.scope)) return;
    const revision = this.store.refreshWatermark().mutationRevision;
    if (revision === this.persistedRevision) return;
    this.persistedRevision = revision;
    const value = { state: this.store.serializeState({ settleRuntimeOverlay: true }) };
    void offlineCache.put('timeline', this.scope.key, value, this.owner).then(saved => {
      if (!saved && this.persistedRevision === revision) this.persistedRevision = -1;
    });
  }

  /** Equivalent opens/reconnects share the whole snapshot/sync operation.
   * A consumer abort releases only its own interest in the shared fetch.
   */
  load(options: { signal?: AbortSignal; forceSnapshot?: boolean; invalidate?: boolean } = {}): Promise<ChatSnapshot | null> {
    this.assertCurrent();
    options.signal?.throwIfAborted();
    if (this.flight?.controller.signal.aborted) this.flight = null;
    // An invalidation is newer information, not just another consumer opening
    // the same view. Keep one trailing intent rather than another transport.
    if (options.invalidate) {
      this.reconciled = false;
      if (this.flight) this.flight.dirty = true;
    }
    if (this.flight && options.forceSnapshot && !this.flight.forceSnapshot) {
      return this.join(this.flight, options.signal).catch(error => {
        if (options.signal?.aborted || !this.current) throw error;
      }).then(() => this.load(options));
    }
    if (!this.flight) {
      const controller = new AbortController();
      const flight: Flight<ChatSnapshot | null> = {
        controller, consumers: 0, forceSnapshot: options.forceSnapshot,
        promise: Promise.resolve(null),
      };
      this.flight = flight;
      flight.promise = withRequestDeadline(
        async signal => {
          let snapshot: ChatSnapshot | null = null;
          let forceSnapshot = options.forceSnapshot === true;
          do {
            flight.dirty = false;
            this.reconciled = false;
            snapshot = await this.performLoad(signal, forceSnapshot) ?? snapshot;
            forceSnapshot = false;
            this.assertCurrent(signal);
            if (flight.dirty) await yieldBeforeProjection();
          } while (flight.dirty);
          this.reconciled = true;
          return snapshot;
        },
        { signal: AbortSignal.any([controller.signal, this.ownerSignal]), timeoutMs: 15_000 },
      ).catch(error => {
        if (this.current && !controller.signal.aborted) {
          this.error = error;
          this.phase = 'error';
        }
        throw error;
      }).finally(() => {
        if (this.flight === flight) this.flight = null;
        if (this.current && controller.signal.aborted && this.phase === 'loading') {
          this.phase = this.store.snapshot.syncStatus === 'ready' ? 'ready' : 'idle';
        }
        trim();
      });
    }
    return this.join(this.flight, options.signal);
  }

  private async join<T>(flight: Flight<T>, signal?: AbortSignal): Promise<T> {
    this.assertCurrent();
    signal = signal ? AbortSignal.any([signal, this.ownerSignal]) : this.ownerSignal;
    signal?.throwIfAborted();
    flight.consumers += 1;
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      flight.consumers -= 1;
      if (flight.consumers === 0) flight.controller.abort();
    };
    let listener: (() => void) | undefined;
    try {
      return await Promise.race([
        flight.promise,
        new Promise<never>((_, reject) => {
          if (!signal) return;
          listener = () => {
            release();
            reject(signal.reason ?? new DOMException('View closed', 'AbortError'));
          };
          signal.addEventListener('abort', listener, { once: true });
        }),
      ]);
    } finally {
      if (listener) signal?.removeEventListener('abort', listener);
      release();
    }
  }

  private async performLoad(signal: AbortSignal, forceSnapshot: boolean): Promise<ChatSnapshot | null> {
    this.phase = 'loading';
    this.error = null;
    try {
      await this.hydrate();
      this.assertCurrent(signal);
      if (!forceSnapshot && this.store.snapshot.cursor) {
        const seen = new Set<string>();
        for (let page = 0; page < MAX_SYNC_PAGES; page += 1) {
          const cursor = this.store.snapshot.cursor;
          if (!cursor || seen.has(cursor)) throw new Error('Timeline synchronization made no progress. Try again.');
          seen.add(cursor);
          const response = await this.api.sync(this.scope, cursor, { signal });
          this.assertCurrent(signal);
          const result = this.store.applySync(response);
          if (result.outcome === 'reset_required' || result.outcome === 'cursor_mismatch') break;
          if (this.store.snapshot.syncStatus !== 'ready') break;
          if (!response.has_more) {
            this.phase = 'ready';
            this.persist();
            return null;
          }
          if (page === MAX_SYNC_PAGES - 1) throw new Error('Timeline synchronization page limit reached. Try again.');
        }
      }
      const watermark = this.store.refreshWatermark();
      const snapshot = await this.api.snapshot(this.scope, { signal, timeoutMs: 15_000 });
      await yieldBeforeProjection();
      this.assertCurrent(signal);
      if (snapshot.conversation.has_message_history && snapshot.timeline.items.length === 0 && !snapshot.timeline.has_more_before) {
        throw new Error('Conversation history is temporarily unavailable. Try again.');
      }
      // Only canonical progress can supersede a required canonical base.
      // Runtime/local admissions use applySnapshot's independent merge rules.
      const applied = this.store.snapshot.cursor === null && watermark.cursor === null
        ? this.store.replaceFromSnapshotForCanonicalBootstrap(snapshot, watermark, true)
        : this.store.replaceFromSnapshotForRecovery(snapshot, watermark);
      if (applied) this.replaceLineage();
      if (this.store.snapshot.syncStatus !== 'ready') {
        throw new Error('Timeline history changed during recovery. Try again.');
      }
      this.phase = 'ready';
      this.persist();
      return applied ? snapshot : null;
    } catch (error) {
      if (this.current && !signal.aborted) {
        this.error = error;
        this.phase = 'error';
      }
      throw error;
    }
  }

  older(before: string, signal?: AbortSignal): Promise<TimelineBackfillResponse | null> {
    this.assertCurrent();
    signal?.throwIfAborted();
    const generation = this.lineageGeneration;
    const key = `${generation}\u0000${before}`;
    let flight = this.backfills.get(key);
    if (flight?.controller.signal.aborted) {
      this.backfills.delete(key);
      flight = undefined;
    }
    if (!flight) {
      const controller = new AbortController();
      flight = { controller, consumers: 0, promise: Promise.resolve(null) };
      const owned = flight;
      this.backfills.set(key, flight);
      flight.promise = this.api.timeline(this.scope, { before, signal: controller.signal }).then((response) => {
        this.assertCurrent(controller.signal);
        // Scope/projection version alone cannot fence a cursor-lineage reset.
        if (generation !== this.lineageGeneration) return null;
        const admitted = this.store.applyBackfill(response);
        if (admitted) this.persist();
        return admitted ? response : null;
      }).finally(() => {
        if (this.backfills.get(key) === owned) this.backfills.delete(key);
        trim();
      });
    }
    return this.join(flight, signal);
  }
}

function trim(): void {
  for (const [key, controller] of registry) {
    if (registry.size <= RESIDENT_LIMIT) break;
    if (!controller.retained) {
      controller.invalidate();
      registry.delete(key);
    }
  }
}

export function clearTimelineMemory(): void {
  for (const controller of registry.values()) controller.invalidate();
  registry.clear();
}
offlineCache.onOwnerChange(clearTimelineMemory);

export class TimelineProviderConflictError extends Error {
  constructor() {
    super('This timeline is open with another API provider. Close the other view and retry.');
    this.name = 'TimelineProviderConflictError';
  }
}

export function acquireTimeline(scope: TimelineScope, api: TimelineApi = chatV2Api): {
  controller: TimelineController; release: () => void;
} {
  const owner = offlineCache.currentOwner;
  const key = `${owner}\u0000${scope.key}`;
  // Anonymous synthetic fixtures are intentionally not resident account data.
  let controller = owner ? registry.get(key) : undefined;
  if (controller && !controller.usesProvider(api)) {
    if (controller.hasConsumers) throw new TimelineProviderConflictError();
    controller.invalidate();
    registry.delete(key);
    controller = undefined;
  }
  if (!controller) controller = new TimelineController({ ...scope }, owner, api);
  if (owner) {
    registry.delete(key);
    registry.set(key, controller);
  }
  controller.retain();
  trim();
  let released = false;
  return { controller, release: () => { if (!released) { released = true; controller.release(); } } };
}

/** Explicit user recovery, never an automatic owner-change retry. Validate the
 * exact canonical namespace under a bounded lease before acquiring fresh data.
 */
export async function recoverTimeline(
  scope: TimelineScope,
  api: TimelineApi = chatV2Api,
  signal?: AbortSignal,
  previousOwner?: string | null,
): Promise<ReturnType<typeof acquireTimeline>> {
  const coordination = documentCoordination();
  const lease = coordination.capture();
  const owner = offlineCache.currentOwner;
  return withRequestDeadline(async operationSignal => {
    await lease.validate();
    operationSignal.throwIfAborted();
    if (previousOwner !== undefined && owner !== previousOwner) {
      // A view's metadata/composer belongs to its original principal too.
      // A new account/server must reopen the surface, not rebind that state.
      throw new TimelineOwnershipError('The account or server changed. Reopen this view after verifying your session.');
    }
    if (!owner || owner !== offlineCache.currentOwner
      || owner !== coordination.storageName('offline-cache', lease)) {
      throw new TimelineOwnershipError();
    }
    return acquireTimeline(scope, api);
  }, { signal: signal ? AbortSignal.any([signal, lease.signal]) : lease.signal, timeoutMs: 15_000 });
}

export function peekTimeline(scope: TimelineScope): ChatV2ClientState | null {
  return registry.get(`${offlineCache.currentOwner}\u0000${scope.key}`)?.store.snapshot ?? null;
}

export function timelineResourceCounts(): { entries: number; retained: number } {
  return { entries: registry.size, retained: [...registry.values()].filter((entry) => entry.retained).length };
}
