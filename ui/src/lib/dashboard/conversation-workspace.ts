import { get, writable } from 'svelte/store';
import type { Conversation } from '$lib/types/api';
import { isAgentDirectConversationSummary } from '$lib/chat-page';
import { isNativeHost, isWorkspaceReplica } from '$lib/native/host';
import { workspaceCapacityReason, workspaceOpenFailure, workspaceOpenErrorReason } from './workspace-open-result';
import {
  WorkspaceManager, parseWorkspaceWindows, serializeWorkspaceWindows,
  dashboardWorkspaceStorageKey, MAX_RETAINED_WORKSPACE_WINDOWS,
  type WorkspaceWindowState, type WorkspaceWindowInput, type WorkspaceOpenResult,
} from './workspace';

export interface RetainedConversation {
  window: WorkspaceWindowState;
  projectId: string | null;
  layouts: Record<string, WorkspaceWindowState>;
}
export interface PinnedAgent { agentId: string; homeConversationId?: string; lastSelectedKey?: string }
export function isAgentHome(conversation: Conversation): boolean {
  return isAgentDirectConversationSummary(conversation);
}

export interface ConversationWorkspaceState {
  entries: RetainedConversation[];
  agents: PinnedAgent[];
  tucked: boolean;
  position: number;
  owner: string | null;
}

export type WorkspaceIntent =
  | { type: 'pin'; conversationId: string; select: boolean; replaceKey?: string }
  | { type: 'home'; agentId: string; conversationId: string; pin: boolean }
  | { type: 'unpin'; key: string }
  | { type: 'agent'; agentId: string; pinned: boolean }
  | { type: 'select'; agentId: string; key: string }
  | { type: 'tucked'; value: boolean }
  | { type: 'position'; value: number };
/** Owner-local actions are never admitted from the native replica bridge. */
export type LocalWorkspaceIntent = WorkspaceIntent
  | { type: 'open-agent'; agentId: string; title: string; projectId: string | null }
  | { type: 'resolve'; key: string; conversationId: string }
  | { type: 'migrate'; key: string; projectId: string | null };
export interface WorkspaceResult { ok: boolean; key?: string; reason?: string }

const safe = { x: 0, y: 0, width: 1440, height: 900 };
const scopeKey = (projectId: string | null) => projectId ? `project:${projectId}` : 'dashboard';
function restoreWindow(value: WorkspaceWindowState): WorkspaceWindowState | null {
  const [window] = parseWorkspaceWindows(serializeWorkspaceWindows([value]), safe);
  if (!window) return null;
  // The legacy parser normalizes a collection's ordering. Here each layout is
  // validated separately, so retain its already persisted relative orders.
  return {
    ...window,
    zOrder: Number.isFinite(value.zOrder) ? Math.max(1, Math.round(value.zOrder)) : window.zOrder,
    switcherOrder: Number.isFinite(value.switcherOrder) ? Math.max(1, Math.round(value.switcherOrder)) : window.switcherOrder,
  };
}
export const retainedConversationId = (window: WorkspaceWindowState): string | null =>
  window.kind === 'conversation' ? window.entityId : window.resolvedConversationId ?? null;
export const isConversationWindow = (window: WorkspaceWindowState): boolean =>
  window.kind === 'conversation' || window.kind === 'agent';

function identity(window: WorkspaceWindowState): string {
  const id = retainedConversationId(window);
  return id ? `conversation:${id}` : window.key;
}

export function conversationWorkspaceStorageKey(email: string): string {
  return `cognis.conversation-workspace.v1:${encodeURIComponent(email.trim().toLowerCase())}`;
}

/** Membership has one owner; dashboard managers are scoped layout projections. */
export class ConversationWorkspace {
  constructor(private readonly replica = false, private readonly coordinated = false) {}
  private command: ((intent: LocalWorkspaceIntent) => Promise<WorkspaceResult>) | null = null;
  private queue: Promise<unknown> = Promise.resolve();
  private scope = 0;
  get scopeRevision(): number { return this.scope; }
  private bindings = new WeakMap<WorkspaceManager, symbol>();
  setCommand(command: ((intent: LocalWorkspaceIntent) => Promise<WorkspaceResult>) | null): void { this.command = command; }
  get isReplica(): boolean { return this.replica; }
  async execute(intent: LocalWorkspaceIntent, resolve?: (id: string) => Promise<Conversation>): Promise<WorkspaceResult> {
    if (this.command) return this.command(intent);
    if (this.replica || this.coordinated) return { ok: false, reason: 'owner-unavailable' };
    const scope = this.scope;
    const result = this.queue.then(() => scope === this.scope
      ? this.reduce(intent, resolve ?? (async (id) =>
        (await import('$lib/api/client')).api.conversations.detail(id, { includeState: false })))
      : { ok: false, reason: 'scope-changed' });
    this.queue = result.catch(() => {});
    return result;
  }
  async reduce(intent: LocalWorkspaceIntent, resolve?: (id: string) => Promise<Conversation>): Promise<WorkspaceResult> {
    if (this.replica) return { ok: false, reason: 'not-owner' };
    const owner = this.snapshot().owner;
    if (!owner) return { ok: false, reason: 'owner-unavailable' };
    const scope = this.scope;
    if (intent.type === 'pin' || intent.type === 'home' || intent.type === 'resolve') {
      if (intent.type === 'pin') {
        const retained = this.selectRetained(intent);
        if (retained) return retained;
      }
      if (!resolve) return { ok: false, reason: 'unresolved' };
      const conversation = await resolve(intent.conversationId);
      if (scope !== this.scope || owner !== this.snapshot().owner) return { ok: false, reason: 'scope-changed' };
      if (intent.type === 'resolve') return this.resolveAgentNow(intent.key, conversation);
      return this.applyConversationIntent(intent, conversation);
    }
    switch (intent.type) {
      case 'unpin': this.unpinNow(intent.key); break;
      case 'agent':
        if (intent.pinned && !this.pinAgentNow(intent.agentId)) return { ok: false, reason: workspaceCapacityReason.agents };
        if (!intent.pinned) this.unpinAgentNow(intent.agentId);
        break;
      case 'select': {
        const state = this.snapshot();
        if (!state.agents.some((agent) => agent.agentId === intent.agentId)
            || (intent.key !== `home:${intent.agentId}` && !state.entries.some((entry) =>
              entry.window.key === intent.key && (entry.window.agentId
                ?? (entry.window.kind === 'agent' ? entry.window.entityId : null)) === intent.agentId))) {
          return { ok: false, reason: 'missing-selection' };
        }
        this.rememberSelectionNow(intent.agentId, intent.key);
        break;
      }
      case 'tucked': this.setTucked(intent.value); break;
      case 'position': this.setPosition(intent.value); break;
      case 'migrate': this.migrateNow(intent.key, intent.projectId); break;
      case 'open-agent': {
        const key = `agent:${intent.agentId}`;
        if (this.snapshot().entries.some((entry) => entry.window.key === key)) return { ok: true, key };
        if (this.snapshot().entries.length >= MAX_RETAINED_WORKSPACE_WINDOWS) return { ok: false, reason: workspaceCapacityReason.retained };
        if (!this.pinAgentNow(intent.agentId)) return { ok: false, reason: workspaceCapacityReason.agents };
        const manager = new WorkspaceManager('desktop', safe);
        manager.open({ kind: 'agent', entityId: intent.agentId, title: intent.title,
          canonicalHref: `/chat/new?agent=${encodeURIComponent(intent.agentId)}` });
        this.publish([...this.snapshot().entries, { window: manager.snapshot()[0], projectId: intent.projectId, layouts: {} }]);
        return { ok: true, key };
      }
    }
    return { ok: true };
  }
  /** Layout reuse only: chat snapshots and server authorization remain canonical. */
  selectRetained(intent: Extract<WorkspaceIntent, { type: 'pin' }>): WorkspaceResult | null {
    if (this.replica || !this.snapshot().owner || intent.replaceKey) return null;
    const entry = this.snapshot().entries.find((item) =>
      retainedConversationId(item.window) === intent.conversationId);
    if (!entry) return null;
    const agentId = entry.window.agentId ?? (entry.window.kind === 'agent' ? entry.window.entityId : null);
    if (intent.select && agentId) this.rememberSelectionNow(agentId, entry.window.key);
    return { ok: true, key: entry.window.key };
  }
  /** Local/browser callers already have a verified conversation, replicas send only its ID. */
  async pinAndSelect(conversation: Conversation, select = true, replaceKey?: string): Promise<WorkspaceResult> {
    const intent: Extract<WorkspaceIntent, { type: 'pin' }> = {
      type: 'pin', conversationId: conversation.conversation_id, select, ...(replaceKey ? { replaceKey } : {})
    };
    return this.execute(intent, async () => conversation);
  }
  async home(conversation: Conversation, pin = false): Promise<WorkspaceResult> {
    const intent: Extract<WorkspaceIntent, { type: 'home' }> = {
      type: 'home', agentId: conversation.agent_id, conversationId: conversation.conversation_id, pin
    };
    return this.execute(intent, async () => conversation);
  }
  applyConversationIntent(intent: Extract<WorkspaceIntent, { type: 'pin' | 'home' }>, conversation: Conversation): WorkspaceResult {
    if (this.replica) return { ok: false, reason: 'not-owner' };
    if (!this.snapshot().owner || conversation.conversation_id !== intent.conversationId) return { ok: false, reason: 'scope-changed' };
    if (intent.type === 'home') {
      if (intent.pin && conversation.agent_id === intent.agentId && isAgentHome(conversation)
          && !this.pinAgentNow(intent.agentId)) return { ok: false, reason: workspaceCapacityReason.agents };
      if (conversation.agent_id !== intent.agentId || !isAgentHome(conversation)
          || !this.snapshot().agents.some((agent) => agent.agentId === intent.agentId)) return { ok: false, reason: 'invalid-home' };
      this.setHome(intent.agentId, conversation);
      return { ok: true, key: `home:${intent.agentId}` };
    }
    // Validate capacity before replacing anything. The owner serializes the whole operation.
    const entries = this.snapshot().entries;
    const replace = entries.find((entry) => entry.window.key === intent.replaceKey);
    if (!this.snapshot().agents.some((agent) => agent.agentId === conversation.agent_id)
        && this.snapshot().agents.length >= MAX_RETAINED_WORKSPACE_WINDOWS) return { ok: false, reason: workspaceCapacityReason.agents };
    if (!entries.some((entry) => retainedConversationId(entry.window) === conversation.conversation_id)
        && entries.length >= MAX_RETAINED_WORKSPACE_WINDOWS && !replace) return { ok: false, reason: workspaceCapacityReason.retained };
    if (replace) this.unpinNow(replace.window.key);
    if (!this.pinNow(conversation)) return { ok: false, reason: workspaceCapacityReason.retained };
    const key = this.snapshot().entries.find((entry) => retainedConversationId(entry.window) === conversation.conversation_id)?.window.key;
    if (key && intent.select) this.rememberSelectionNow(conversation.agent_id, key);
    return { ok: !!key, key };
  }
  /** Only a validated, monotonically admitted owner projection may hydrate replicas. */
  applyProjection(state: ConversationWorkspaceState): void {
    if (!this.replica) throw new Error('Cannot hydrate the workspace owner');
    this.store.set(structuredClone(state));
  }
  private store = writable<ConversationWorkspaceState>({ entries: [], agents: [], tucked: false, position: 0.65, owner: null });
  subscribe = this.store.subscribe;
  private storage: Storage | null = null;
  private migrated = new Set<string>();

  snapshot(): ConversationWorkspaceState { return get(this.store); }

  setOwner(email: string | null, storage: Storage | null): void {
    if (this.replica) return;
    if (email === this.snapshot().owner) return;
    ++this.scope;
    this.storage = storage;
    this.migrated.clear();
    let entries: RetainedConversation[] = [];
    let position = 0.65;
    let agents: PinnedAgent[] = [];
    let tucked = true;
    if (email && storage) {
      try {
        const parsed = JSON.parse(storage.getItem(conversationWorkspaceStorageKey(email)) ?? 'null');
        if (parsed?.version === 1 && Array.isArray(parsed.entries)) {
          for (const entry of parsed.entries.slice(0, MAX_RETAINED_WORKSPACE_WINDOWS)) {
            const window = restoreWindow(entry.window);
            if (!window || !isConversationWindow(window)) continue;
            const layouts: Record<string, WorkspaceWindowState> = {};
            for (const [key, value] of Object.entries(entry.layouts ?? {})) {
              const layout = restoreWindow(value as WorkspaceWindowState);
              if (layout && layout.key === window.key) layouts[key] = layout;
            }
            if (!entries.some((item) => identity(item.window) === identity(window))) {
              entries.push({ window, layouts, projectId: typeof entry.projectId === 'string' ? entry.projectId : null });
            }
          }
          if (Number.isFinite(parsed.position)) position = Math.min(1, Math.max(0, parsed.position));
          if (Array.isArray(parsed.agents)) agents = parsed.agents.filter((item: PinnedAgent) =>
            item && typeof item.agentId === 'string' && item.agentId.length > 0).slice(0, MAX_RETAINED_WORKSPACE_WINDOWS)
            .map((item: PinnedAgent) => ({ agentId: item.agentId,
              ...(typeof item.homeConversationId === 'string' ? { homeConversationId: item.homeConversationId } : {}),
              ...(typeof item.lastSelectedKey === 'string' ? { lastSelectedKey: item.lastSelectedKey } : {}) }));
          tucked = typeof parsed.tucked === 'boolean' ? parsed.tucked : true;
          if (Array.isArray(parsed.migrated)) {
            this.migrated = new Set(parsed.migrated.filter((key: unknown) => typeof key === 'string'));
          }
        }
      } catch { /* Browser storage is optional; invalid saved state is ignored. */ }
    }
    for (const entry of entries) {
      const id = entry.window.agentId ?? (entry.window.kind === 'agent' ? entry.window.entityId : null);
      if (id && !agents.some((item) => item.agentId === id)) agents.push({ agentId: id });
    }
    this.store.set({ owner: email, entries, agents, tucked, position });
    if (email && storage) {
      this.migrateNow(dashboardWorkspaceStorageKey(email), null);
    }
  }

  private save(): void {
    if (this.replica) throw new Error('Replica cannot persist workspace state');
    const state = this.snapshot();
    if (!state.owner || !this.storage) return;
    try {
      this.storage.setItem(conversationWorkspaceStorageKey(state.owner), JSON.stringify({
        version: 1, entries: state.entries, agents: state.agents, tucked: state.tucked,
        position: state.position, migrated: [...this.migrated],
      }));
    } catch { /* Persistence must never block chat. */ }
  }

  private publish(entries: RetainedConversation[]): void {
    const unique = new Map<string, RetainedConversation>();
    for (const entry of entries) {
      const key = identity(entry.window);
      const previous = unique.get(key);
      if (!previous || (previous.window.kind === 'agent' && entry.window.kind === 'conversation')) unique.set(key, entry);
    }
    this.store.update((state) => {
      const agents = [...state.agents];
      for (const entry of unique.values()) {
        const id = entry.window.agentId ?? (entry.window.kind === 'agent' ? entry.window.entityId : null);
        if (id && !agents.some((item) => item.agentId === id)) agents.push({ agentId: id });
      }
      return { ...state, agents, entries: [...unique.values()] };
    });
    this.save();
  }

  migrate(key: string, projectId: string | null): Promise<WorkspaceResult> {
    return this.execute({ type: 'migrate', key, projectId });
  }
  private migrateNow(key: string, projectId: string | null): void {
    if (this.replica) return;
    if (this.migrated.has(key) || !this.storage) return;
    let windows: WorkspaceWindowState[] = [];
    try { windows = parseWorkspaceWindows(this.storage.getItem(key), safe); } catch { return; }
    this.migrated.add(key);
    const entries = [...this.snapshot().entries];
    for (const window of windows.filter(isConversationWindow)) {
      const existing = entries.find((entry) => identity(entry.window) === identity(window));
      if (existing) existing.layouts = { ...existing.layouts, [scopeKey(projectId)]: window };
      else if (entries.length < MAX_RETAINED_WORKSPACE_WINDOWS) {
        entries.push({ window, projectId, layouts: { [scopeKey(projectId)]: window } });
      }
    }
    this.publish(entries);
  }

  async pin(conversation: Conversation): Promise<boolean> { return (await this.pinAndSelect(conversation, false)).ok; }
  private pinNow(conversation: Conversation): boolean {
    if (this.replica) return false;
    if (!this.snapshot().owner) return false;
    const entries = this.snapshot().entries;
    const existing = entries.find((entry) => retainedConversationId(entry.window) === conversation.conversation_id);
    if (!existing && entries.length >= MAX_RETAINED_WORKSPACE_WINDOWS) return false;
    if (!this.pinAgentNow(conversation.agent_id)) return false;
    if (!existing) {
      const manager = new WorkspaceManager('desktop', safe);
      manager.open({
        kind: 'conversation', entityId: conversation.conversation_id,
        title: conversation.title || 'Conversation', agentId: conversation.agent_id,
        canonicalHref: `/chat/${encodeURIComponent(conversation.conversation_id)}`,
      });
      this.publish([...entries, {
        window: manager.snapshot()[0], projectId: conversation.project_id ?? null, layouts: {},
      }]);
    }
    this.updateConversation(conversation);
    return true;
  }

  unpin(key: string): Promise<WorkspaceResult> { return this.execute({ type: 'unpin', key }); }
  private unpinNow(key: string): void {
    if (this.replica) return;
    this.publish(this.snapshot().entries.filter((entry) => entry.window.key !== key));
  }

  async pinAgent(agentId: string): Promise<boolean> { return (await this.execute({ type: 'agent', agentId, pinned: true })).ok; }
  private pinAgentNow(agentId: string): boolean {
    if (this.replica) return false;
    const state = this.snapshot();
    if (!state.owner || !agentId) return false;
    if (state.agents.some((agent) => agent.agentId === agentId)) return true;
    if (state.agents.length >= MAX_RETAINED_WORKSPACE_WINDOWS) return false;
    this.store.update((current) => ({ ...current, agents: [...current.agents, { agentId }] }));
    this.save();
    return true;
  }

  setHome(agentId: string, conversation: Conversation): void {
    if (this.replica) return;
    if (conversation.agent_id !== agentId || !this.snapshot().agents.some((item) => item.agentId === agentId)) return;
    if (this.snapshot().agents.find((item) => item.agentId === agentId)?.homeConversationId === conversation.conversation_id) return;
    this.store.update((state) => ({ ...state, agents: state.agents.map((item) =>
      item.agentId === agentId ? { ...item, homeConversationId: conversation.conversation_id } : item) }));
    this.save();
  }

  rememberSelection(agentId: string, key: string): Promise<WorkspaceResult> { return this.execute({ type: 'select', agentId, key }); }
  private rememberSelectionNow(agentId: string, key: string): void {
    if (this.replica) return;
    const state = this.snapshot();
    const agent = state.agents.find((item) => item.agentId === agentId);
    if (!agent || agent.lastSelectedKey === key) return;
    if (key !== `home:${agentId}` && !state.entries.some((entry) => entry.window.key === key
      && (entry.window.agentId ?? (entry.window.kind === 'agent' ? entry.window.entityId : null)) === agentId)) return;
    this.store.update((current) => ({ ...current, agents: current.agents.map((item) =>
      item.agentId === agentId ? { ...item, lastSelectedKey: key } : item) }));
    this.save();
  }

  unpinAgent(agentId: string): Promise<WorkspaceResult> { return this.execute({ type: 'agent', agentId, pinned: false }); }
  private unpinAgentNow(agentId: string): void {
    if (this.replica) return;
    this.store.update((state) => ({ ...state,
      agents: state.agents.filter((item) => item.agentId !== agentId),
      entries: state.entries.filter((entry) => (entry.window.agentId
        ?? (entry.window.kind === 'agent' ? entry.window.entityId : null)) !== agentId),
    }));
    this.save();
  }

  setTucked(tucked: boolean): void {
    if (this.replica) return;
    this.store.update((state) => ({ ...state, tucked })); this.save();
  }

  setPosition(position: number): void {
    if (this.replica) return;
    if (!Number.isFinite(position)) return;
    this.store.update((state) => ({ ...state, position: Math.min(1, Math.max(0, position)) }));
    this.save();
  }

  updateConversation(conversation: Conversation): void {
    if (this.replica) return;
    if (isAgentHome(conversation)) this.setHome(conversation.agent_id, conversation);
    const entries = this.snapshot().entries;
    let changed = false;
    const next = entries.map((entry) => {
      if (retainedConversationId(entry.window) !== conversation.conversation_id) return entry;
      const title = conversation.title || entry.window.title;
      if (entry.projectId === (conversation.project_id ?? null) && entry.window.title === title
        && entry.window.agentId === conversation.agent_id && entry.window.status === conversation.status) return entry;
      changed = true;
      return { ...entry, projectId: conversation.project_id ?? null, window: {
        ...entry.window, title, agentId: conversation.agent_id, status: conversation.status,
      } };
    });
    if (changed) this.publish(next);
  }

  resolveAgent(key: string, conversation: Conversation): Promise<WorkspaceResult> {
    return this.execute({ type: 'resolve', key, conversationId: conversation.conversation_id }, async () => conversation);
  }
  private resolveAgentNow(key: string, conversation: Conversation): WorkspaceResult {
    if (this.replica) return { ok: false, reason: 'not-owner' };
    const entries = this.snapshot().entries;
    const entry = entries.find((item) => item.window.key === key);
    if (!entry) return { ok: false, reason: 'missing-selection' };
    const existing = entries.find((item) => item !== entry
      && retainedConversationId(item.window) === conversation.conversation_id);
    if (existing) this.unpinNow(key);
    else {
      this.publish(entries.map((item) => item === entry ? { ...item, window: {
        ...item.window, resolvedConversationId: conversation.conversation_id,
        canonicalHref: `/chat/${encodeURIComponent(conversation.conversation_id)}`,
      } } : item));
      this.updateConversation(conversation);
    }
    return { ok: true, key: existing?.window.key ?? key };
  }

  /** Closing a filtered projection never removes another project's retained chat. */
  bind(manager: WorkspaceManager, projectId: string | null, legacyKey: string): () => void {
    if (this.replica) return () => {};
    void this.migrate(legacyKey, projectId);
    let applying = false;
    const binding = Symbol('workspace-binding');
    this.bindings.set(manager, binding);
    let active = true;
    const live = () => active && this.bindings.get(manager) === binding;
    const pending = new Map<string, Promise<WorkspaceOpenResult>>();
    const project = scopeKey(projectId);
    const matches = (entry: RetainedConversation) => !projectId || entry.projectId === projectId;
    const open = async (input: WorkspaceWindowInput): Promise<WorkspaceOpenResult> => {
      const scope = this.scope;
      const existing = manager.snapshot().some((window) => input.kind === 'conversation'
        ? retainedConversationId(window) === input.entityId : window.key === `agent:${input.entityId}`);
      try {
        const result = await this.execute(input.kind === 'agent'
          ? { type: 'open-agent', agentId: input.entityId, title: input.title, projectId }
          : { type: 'pin', conversationId: input.entityId, select: true });
        if (!live() || scope !== this.scope) return { status: 'failed', reason: 'scope-changed' };
        if (!result.ok) return workspaceOpenFailure(result.reason ?? 'open-failed');
        if (!result.key) return { status: 'failed', reason: 'missing-key' };
        const projected = manager.snapshot().find((window) => window.key === result.key
          && (input.kind === 'conversation' ? retainedConversationId(window) === input.entityId
            : window.kind === 'agent' && window.entityId === input.entityId));
        if (!projected) return { status: 'failed', reason: 'not-projected' };
        if (projected.minimized) {
          const restored = manager.restore(result.key);
          if (restored.status === 'capped') return { ...restored, scope: 'visible' };
        }
        manager.focus(result.key);
        return { status: existing ? 'focused' : 'opened', key: result.key };
      } catch (error) {
        return { status: 'failed', reason: workspaceOpenErrorReason(error) };
      }
    };
    manager.setMembershipActions({
      open: (input) => {
        const id = `${this.scope}:${input.kind}:${input.entityId}`;
        const current = pending.get(id);
        if (current) return current;
        const request = open(input).finally(() => { if (pending.get(id) === request) pending.delete(id); });
        pending.set(id, request);
        return request;
      },
      close: async (key) => { await this.execute({ type: 'unpin', key }); },
      resolve: async (key, conversationId) => { await this.execute({ type: 'resolve', key, conversationId }); },
    });
    const apply = () => {
      if (applying || !live()) return;
      applying = true;
      const entries = this.snapshot().entries.filter(matches);
      const current = manager.snapshot();
      const native = current.filter((window) => !isConversationWindow(window));
      const projected = entries.map((entry) => ({
        ...(entry.layouts[project] ?? entry.window),
        // Metadata and resolved identity belong to membership, not saved layout.
        ...entry.window,
        ...(entry.layouts[project] ? {
          rect: entry.layouts[project].rect, restoreRect: entry.layouts[project].restoreRect,
          minimized: entry.layouts[project].minimized, zOrder: entry.layouts[project].zOrder,
          switcherOrder: entry.layouts[project].switcherOrder,
        } : {}),
      }));
      const windows = [...native, ...projected.map((window) => {
        const existing = current.find((item) => item.key === window.key);
        return existing ? {
          ...window, refreshToken: existing.refreshToken, focusRevision: existing.focusRevision,
          ...(manager.hasDashboardSnapshot() ? { minimized: existing.minimized } : {}),
        } : window;
      })];
      if (JSON.stringify(windows) !== JSON.stringify(manager.snapshot())) {
        manager.replaceProjection(windows);
      }
      applying = false;
    };
    const stopWorkspace = this.subscribe(apply);
    const stopManager = manager.subscribe(() => {
      if (applying || !live()) return;
      const windows = manager.persistentSnapshot().filter(isConversationWindow);
      let entries = this.snapshot().entries;
      for (const window of windows) {
        const existing = entries.find((entry) => entry.window.key === window.key && identity(entry.window) === identity(window));
        if (existing && matches(existing)) {
          const layout = { ...existing.window, rect: window.rect, restoreRect: window.restoreRect,
            minimized: window.minimized, zOrder: window.zOrder, switcherOrder: window.switcherOrder };
          entries = entries.map((entry) => entry === existing ? {
            ...entry, layouts: { ...entry.layouts, [project]: layout },
          } : entry);
        }
      }
      if (JSON.stringify(entries) !== JSON.stringify(this.snapshot().entries)) {
        this.store.update((state) => ({ ...state, entries }));
        this.save();
      }
      apply();
    });
    return () => {
      if (live()) { manager.setMembershipActions(null); this.bindings.delete(manager); }
      active = false;
      pending.clear();
      stopManager(); stopWorkspace();
    };
  }
}

export const conversationWorkspace = new ConversationWorkspace(isWorkspaceReplica(), isNativeHost());
