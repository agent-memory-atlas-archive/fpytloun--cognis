import { get, writable } from 'svelte/store';
import { api, asApiError } from '$lib/api/client';
import { RefreshCooldown, SidebarRefreshController } from '$lib/sidebar-refresh';
import { auth } from '$lib/stores/auth';
import { wsClient, wsState } from '$lib/ws/client';
import type { Agent, BackgroundWorkItem, Conversation } from '$lib/types/api';
import { conversationWorkspace, retainedConversationId } from './conversation-workspace';
import { dashboardConversationPatch, dashboardRealtimeLoads, type DashboardConversationPatch } from './realtime';
import { hasNewPinnedNotification } from './pinned-dock';

export const pinnedConversations = writable<Record<string, Conversation>>({});
export const pinnedAgents = writable<Agent[]>([]);
export const pinnedBackgroundWork = writable<BackgroundWorkItem[]>([]);
export const pinnedActivityAt = writable<Record<string, number>>({});

const ACTIVITY_EVENTS = new Set([
  'turn_started', 'message_complete', 'workflow_step_question',
  'auth_challenge', 'credential_request', 'escalation',
]);

/** Only summaries are live while collapsed; timelines belong to visible views. */
export function startConversationWorkspace(): () => void {
  if (conversationWorkspace.isReplica) return () => {};
  let epoch = 0;
  let alive = true;
  let owner: string | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const requests = new Map<string, number>();
  const inFlightPatches = new Map<string, DashboardConversationPatch>();
  let version = 0;
  let backgroundVersion = 0;
  let backgroundQueued = false;
  let backgroundUrgent = false;
  let agentsRequested = false;
  const ids = () => new Set([
    ...conversationWorkspace.snapshot().entries.map((entry) => retainedConversationId(entry.window)),
    ...conversationWorkspace.snapshot().agents.map((agent) => agent.homeConversationId),
  ].filter((id): id is string => !!id));
  const queued = new Set<string>();
  const recordActivity = (id: string) => {
    if (!ids().has(id)) return;
    pinnedActivityAt.update((state) => ({ ...state, [id]: Date.now() }));
  };
  const observeNotification = (next: Conversation) => {
    if (hasNewPinnedNotification(get(pinnedConversations)[next.conversation_id], next)) recordActivity(next.conversation_id);
  };
  const refreshBackground = async (signal: AbortSignal) => {
    if (!owner || !conversationWorkspace.snapshot().agents.length) return;
    const generation = epoch;
    const request = ++backgroundVersion;
    const sidebar = await api.conversations.backgroundWork({ includeAgentDirect: true, signal });
    if (alive && generation === epoch && request === backgroundVersion) {
      if (sidebar.background_work_changed) pinnedBackgroundWork.set(sidebar.background_work.items);
      for (const direct of sidebar.agent_direct_chats ?? []) {
        const id = direct.agent.agent_id;
        if (!conversationWorkspace.snapshot().agents.some((agent) => agent.agentId === id)) continue;
        conversationWorkspace.setHome(id, direct.conversation);
        observeNotification(direct.conversation);
        pinnedConversations.update((state) => ({ ...state, [direct.conversation.conversation_id]: direct.conversation }));
      }
    }
  };
  const backgroundRefresh = new SidebarRefreshController(
    ({ signal }) => refreshBackground(signal), new RefreshCooldown(),
  );

  const refresh = async (id: string) => {
    const generation = epoch;
    const request = ++version;
    requests.set(id, request);
    inFlightPatches.delete(id);
    try {
      const conversation = await api.conversations.detail(id, { includeState: false });
      if (!alive || epoch !== generation || requests.get(id) !== request
        || !ids().has(id)) return;
      const result = { ...conversation, ...inFlightPatches.get(id) };
      observeNotification(result);
      pinnedConversations.update((state) => ({ ...state, [id]: result }));
      conversationWorkspace.updateConversation(result);
    } catch (error) {
      if (alive && generation === epoch && requests.get(id) === request
        && [403, 404].includes(asApiError(error).status ?? 0)) {
        for (const entry of conversationWorkspace.snapshot().entries) {
          if (retainedConversationId(entry.window) === id) conversationWorkspace.unpin(entry.window.key);
        }
        pinnedConversations.update((state) => {
          const next = { ...state }; delete next[id]; return next;
        });
      }
    } finally {
      if (requests.get(id) === request) { requests.delete(id); inFlightPatches.delete(id); }
    }
  };
  const schedule = () => {
    if (timer !== null) return;
    timer = setTimeout(() => {
      timer = null;
      const ids = [...queued]; queued.clear();
      for (const id of ids) void refresh(id);
      if (backgroundQueued) {
        backgroundQueued = false;
        if (owner) void backgroundRefresh.request(owner, { urgent: backgroundUrgent });
        backgroundUrgent = false;
      }
    }, 100);
  };
  const queue = (id: string) => {
    queued.add(id); backgroundQueued = true; schedule();
  };
  const loadAgents = () => {
    if (!owner || agentsRequested || !conversationWorkspace.snapshot().agents.length) return;
    agentsRequested = true;
    const current = epoch;
    void api.agents.listAll({ include_hidden: true }).then((agents) => {
      if (alive && current === epoch) pinnedAgents.set(agents);
    }).catch(() => { if (current === epoch) agentsRequested = false; });
  };
  const refreshAll = () => {
    if (!owner) return;
    for (const id of ids()) queue(id);
    backgroundQueued = true; schedule();
  };
  const stopAuth = auth.subscribe((state) => {
    const email = state.status === 'authenticated' ? state.user?.email ?? null : null;
    if (email === owner) return;
    owner = email; epoch++;
    backgroundRefresh.setLifecycle({ scope: email, eligible: Boolean(email) });
    backgroundUrgent = false;
    requests.clear(); inFlightPatches.clear(); queued.clear(); backgroundQueued = false; agentsRequested = false;
    pinnedConversations.set({}); pinnedAgents.set([]); pinnedBackgroundWork.set([]); pinnedActivityAt.set({});
    let storage: Storage | null = null;
    try { storage = window.localStorage; } catch { /* Optional storage. */ }
    conversationWorkspace.setOwner(email, storage);
    if (email) {
      loadAgents();
      refreshAll();
    }
  });
  const stopPins = conversationWorkspace.subscribe((state) => {
    if (!owner) return;
    loadAgents();
    const retained = ids();
    pinnedActivityAt.update((current) => Object.fromEntries(Object.entries(current).filter(([id]) => retained.has(id))));
    pinnedConversations.update((current) => Object.fromEntries(Object.entries(current).filter(([id]) => retained.has(id))));
    for (const id of retained) if (!get(pinnedConversations)[id] && !requests.has(id)) queue(id);
    if (state.agents.some((agent) => !agent.homeConversationId)) { backgroundQueued = true; schedule(); }
  });
  const stopEvents = wsClient.subscribe((event) => {
    if (ACTIVITY_EVENTS.has(event.type) && 'conversation_id' in event && typeof event.conversation_id === 'string') {
      recordActivity(event.conversation_id);
    }
    const patch = dashboardConversationPatch(event);
    if (patch && get(pinnedConversations)[patch.conversation_id]) {
      observeNotification({ ...get(pinnedConversations)[patch.conversation_id], ...patch });
      if (requests.has(patch.conversation_id)) inFlightPatches.set(patch.conversation_id, {
        ...inFlightPatches.get(patch.conversation_id), ...patch,
      });
      pinnedConversations.update((state) => ({
        ...state, [patch.conversation_id]: { ...state[patch.conversation_id], ...patch },
      }));
    }
    if (dashboardRealtimeLoads(event.type, 'reason' in event ? event.reason : undefined).includes('conversations')) {
      const id = 'conversation_id' in event && typeof event.conversation_id === 'string' ? event.conversation_id : null;
      if (id && ids().has(id)) queue(id);
      else if (!id) refreshAll();
    }
    if (['work_invalidated', 'conversation_runtime_snapshot'].includes(event.type)) {
      backgroundQueued = true; schedule();
    }
  });
  let connected = false;
  const stopSocket = wsState.subscribe((state) => {
    if (state.status === 'connected' && !connected) { backgroundUrgent = true; refreshAll(); }
    connected = state.status === 'connected';
  });
  const onVisible = () => {
    if (document.visibilityState === 'visible') { backgroundUrgent = true; refreshAll(); }
  };
  window.addEventListener('focus', onVisible);
  document.addEventListener('visibilitychange', onVisible);
  const reconcile = setInterval(onVisible, 60_000);
  return () => {
    backgroundRefresh.dispose();
    alive = false; epoch++; owner = null;
    stopPins(); stopAuth(); stopEvents(); stopSocket();
    if (timer !== null) clearTimeout(timer);
    clearInterval(reconcile);
    window.removeEventListener('focus', onVisible);
    document.removeEventListener('visibilitychange', onVisible);
    conversationWorkspace.setOwner(null, null);
    pinnedConversations.set({}); pinnedAgents.set([]); pinnedBackgroundWork.set([]); pinnedActivityAt.set({});
  };
}
