import type { Conversation } from '$lib/types/api';
import { ConversationWorkspace, type ConversationWorkspaceState, type LocalWorkspaceIntent, type WorkspaceIntent, type WorkspaceResult } from '$lib/dashboard/conversation-workspace';

export interface WorkspaceScope { profile: string; account: string; authEpoch: string }
export interface WorkspaceProjection {
  workspace: ConversationWorkspaceState;
  agents: unknown[];
  conversations: Record<string, Conversation>;
  background: unknown[];
}
export interface WorkspaceFrame extends WorkspaceScope {
  kind: 'hello' | 'command' | 'query' | 'projection' | 'result';
  document: string;
  ownerEpoch: string | null;
  target: string;
  revision: number;
  id: number;
  intent?: WorkspaceIntent;
  result?: WorkspaceResult;
  projection?: WorkspaceProjection;
}
export const sameScope = (a: WorkspaceScope, b: WorkspaceScope): boolean =>
  a.profile === b.profile && a.account === b.account && a.authEpoch === b.authEpoch;
const empty = (): ConversationWorkspaceState => ({ owner: null, entries: [], agents: [], tucked: false, position: 0.65 });

/** One resident web document, never a native reducer. All commands are serialized. */
export class WorkspaceOwner {
  private revision = 0;
  private stopped = false;
  private queue: Promise<void> = Promise.resolve();
  private highWater = new Map<string, number>();
  private results = new Map<string, WorkspaceResult>();
  private reducing = false;
  private sequence = 0;
  private local = new Map<number, { resolve: (result: WorkspaceResult) => void; timer: ReturnType<typeof setTimeout> }>();
  constructor(
    readonly scope: WorkspaceScope, readonly document: string, readonly epoch: string,
    private readonly workspace: ConversationWorkspace,
    private readonly projection: () => WorkspaceProjection,
    private readonly resolve: (id: string) => Promise<Conversation>,
    private readonly validate: () => Promise<void>,
    private readonly send: (frame: WorkspaceFrame) => void
  ) {}
  submit(intent: LocalWorkspaceIntent): Promise<WorkspaceResult> {
    if (this.stopped) return Promise.resolve({ ok: false, reason: 'owner-unavailable' });
    const id = ++this.sequence;
    return new Promise((resolve) => {
      const timer = setTimeout(() => { this.local.delete(id); resolve({ ok: false, reason: 'uncertain' }); }, 8000);
      this.local.set(id, { resolve, timer });
      this.admit({ ...this.scope, document: this.document, ownerEpoch: this.epoch,
        target: '', kind: 'command', id, revision: 0 }, intent);
    });
  }
  publish(target = '*', id = 0, result?: WorkspaceResult): void {
    if (this.stopped || this.reducing) return;
    if (target === this.document && result) {
      const pending = this.local.get(id);
      if (pending) { clearTimeout(pending.timer); this.local.delete(id); pending.resolve(result); }
    }
    this.send({ ...this.scope, document: this.document, ownerEpoch: this.epoch,
      target, id, revision: ++this.revision, kind: result ? 'result' : 'projection',
      ...(result ? { result } : {}), projection: structuredClone(this.projection()) });
  }
  receive(frame: WorkspaceFrame): void {
    this.admit(frame, frame.intent);
  }
  private admit(frame: WorkspaceFrame, intent?: LocalWorkspaceIntent): void {
    if (this.stopped || !sameScope(frame, this.scope)
        || (frame.kind !== 'hello' && frame.ownerEpoch !== this.epoch)) return;
    if (frame.kind === 'hello') { this.publish(frame.document); return; }
    if (!['command', 'query'].includes(frame.kind) || !Number.isSafeInteger(frame.id) || frame.id < 1) return;
    const key = `${frame.document}:${frame.id}`;
    // Register before enqueueing: a timeout query can never report "not seen"
    // while a command is awaiting server resolution.
    const previous = this.highWater.get(frame.document) ?? 0;
    const admitted = frame.kind === 'command' && frame.id > previous;
    if (admitted) this.highWater.set(frame.document, frame.id);
    const scopeRevision = this.workspace.scopeRevision;
    const current = () => !this.stopped && this.workspace.scopeRevision === scopeRevision
      && this.workspace.snapshot().owner === this.scope.account;
    this.queue = this.queue.then(async () => {
      if (this.stopped) return;
      await this.validate();
      if (this.stopped) return;
      let result = this.results.get(key);
      if (!result && admitted && intent) {
        if (!current()) { this.publish(frame.document, frame.id, { ok: false, reason: 'scope-changed' }); return; }
        if (intent.type === 'pin') result = this.workspace.selectRetained(intent) ?? undefined;
        // Resolve metadata through the owner API and validate its lease after
        // every await, before the synchronous reducer/persistence boundary.
        let conversation: Conversation | undefined;
        if (!result && (intent.type === 'pin' || intent.type === 'home' || intent.type === 'resolve')) {
          conversation = await this.resolve(intent.conversationId);
          await this.validate();
          if (this.stopped) return;
          if (!current()) { this.publish(frame.document, frame.id, { ok: false, reason: 'scope-changed' }); return; }
        }
        this.reducing = true;
        try {
          result ??= conversation && (intent.type === 'pin' || intent.type === 'home')
            ? this.workspace.applyConversationIntent(intent, conversation)
            : await this.workspace.reduce(intent, conversation ? async () => conversation! : undefined);
        } finally { this.reducing = false; }
        if (this.stopped) return;
        this.results.set(key, result);
        if (this.results.size > 512) this.results.delete(this.results.keys().next().value!);
      }
      this.publish(frame.document, frame.id, result ?? {
        ok: false, reason: frame.id <= (this.highWater.get(frame.document) ?? 0) ? 'outcome-expired' : 'not-applied'
      });
      this.publish();
    }).catch(() => {
      // Once admitted, an exception is an uncertain result, not permission to
      // retry. Its high-water tombstone remains until this owner epoch retires.
      if (!this.stopped) this.publish(frame.document, frame.id, { ok: false, reason: 'uncertain' });
    });
  }
  stop(): void {
    this.stopped = true; this.results.clear(); this.highWater.clear();
    for (const pending of this.local.values()) { clearTimeout(pending.timer); pending.resolve({ ok: false, reason: 'uncertain' }); }
    this.local.clear();
  }
}

interface Pending {
  resolve: (result: WorkspaceResult) => void;
  timer: ReturnType<typeof setTimeout>;
}
/** No optimistic mutation, persistence, fallback writer or replay. */
export class WorkspaceReplica {
  private epoch: string | null = null;
  private revision = 0;
  private sequence = 0;
  private pending = new Map<number, Pending>();
  private retired = new Set<string>();
  constructor(
    readonly scope: WorkspaceScope, readonly document: string,
    private readonly workspace: ConversationWorkspace,
    private readonly apply: (projection: WorkspaceProjection) => void,
    private readonly send: (frame: WorkspaceFrame) => void,
    private readonly timeout = 4000
  ) {
    workspace.setCommand((intent) => {
      if (intent.type === 'migrate' || intent.type === 'resolve' || intent.type === 'open-agent') {
        return Promise.resolve({ ok: false, reason: 'not-owner' });
      }
      return this.execute(intent);
    });
    this.workspace.applyProjection(empty());
  }
  hello(): void { this.send(this.frame('hello', 0)); }
  private frame(kind: WorkspaceFrame['kind'], id: number, intent?: WorkspaceIntent): WorkspaceFrame {
    return { ...this.scope, document: this.document, ownerEpoch: this.epoch,
      target: '', revision: this.revision, kind, id, ...(intent ? { intent } : {}) };
  }
  execute(intent: WorkspaceIntent): Promise<WorkspaceResult> {
    if (!this.epoch) return Promise.resolve({ ok: false, reason: 'owner-unavailable' });
    const id = ++this.sequence;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        // Reconcile the exact command, never retransmit its mutation.
        this.send(this.frame('query', id));
        const pending = this.pending.get(id);
        if (pending) pending.timer = setTimeout(() => {
          this.pending.delete(id); resolve({ ok: false, reason: 'uncertain' });
          this.hello();
        }, this.timeout);
      }, this.timeout);
      this.pending.set(id, { resolve, timer });
      this.send(this.frame('command', id, intent));
    });
  }
  receive(frame: WorkspaceFrame): void {
    if (!sameScope(frame, this.scope) || !frame.ownerEpoch || this.retired.has(frame.ownerEpoch)
        || !['projection', 'result'].includes(frame.kind)
        || (frame.target !== '*' && frame.target !== this.document)) return;
    // Owner changes are admitted only after an explicit native reset.
    if (this.epoch && this.epoch !== frame.ownerEpoch) return;
    if (!this.epoch) this.epoch = frame.ownerEpoch;
    if (frame.revision > this.revision && frame.projection
        && frame.projection.workspace.owner === this.scope.account) {
      this.revision = frame.revision;
      this.workspace.applyProjection(frame.projection.workspace);
      this.apply(frame.projection);
    }
    // A reordered ack may settle its command, but never roll back projection.
    if (frame.kind === 'result' && frame.target === this.document && frame.result) {
      const pending = this.pending.get(frame.id);
      if (pending) { clearTimeout(pending.timer); this.pending.delete(frame.id); pending.resolve(frame.result); }
    }
  }
  reset(): void {
    if (this.epoch) this.retired.add(this.epoch);
    this.epoch = null; this.revision = 0;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer); pending.resolve({ ok: false, reason: 'uncertain' });
    }
    this.pending.clear();
    const workspace = empty();
    this.workspace.applyProjection(workspace);
    this.apply({ workspace, agents: [], conversations: {}, background: [] });
  }
  stop(): void { this.reset(); this.workspace.setCommand(null); }
}
