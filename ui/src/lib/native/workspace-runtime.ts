import { get } from 'svelte/store';
import { api } from '$lib/api/client';
import { auth } from '$lib/stores/auth';
import { documentCoordination } from '$lib/document-coordination';
import { conversationWorkspace } from '$lib/dashboard/conversation-workspace';
import { pinnedAgents, pinnedConversations, pinnedBackgroundWork } from '$lib/dashboard/conversation-workspace-runtime';
import { isWorkspaceReplica, nativeConfiguration, postNative } from './host';
import { WorkspaceOwner, WorkspaceReplica, sameScope, type WorkspaceFrame, type WorkspaceProjection } from './workspace-protocol';
import type { Agent, BackgroundWorkItem } from '$lib/types/api';

export function installWorkspaceBridge(): () => void {
  const config = nativeConfiguration();
  if (!config) return () => {};
  let owner: WorkspaceOwner | null = null;
  let replica: WorkspaceReplica | null = null;
  let alive = true, ticket = 0;
  const send = (frame: WorkspaceFrame) => postNative('workspace', frame);
  const projection = (): WorkspaceProjection => ({
    workspace: conversationWorkspace.snapshot(), agents: get(pinnedAgents),
    conversations: get(pinnedConversations), background: get(pinnedBackgroundWork)
  });
  const apply = (value: WorkspaceProjection) => {
    pinnedAgents.set(value.agents as Agent[]);
    pinnedConversations.set(value.conversations);
    pinnedBackgroundWork.set(value.background as BackgroundWorkItem[]);
  };
  const reset = () => {
    owner?.stop(); owner = null; replica?.stop(); replica = null;
    conversationWorkspace.setCommand(null);
  };
  const start = async () => {
    const ownTicket = ++ticket;
    const state = get(auth);
    if (state.status !== 'authenticated' || !state.user) { reset(); return; }
    try {
      const lease = documentCoordination().capture();
      await lease.validate();
      if (!alive || ticket !== ownTicket) return;
      const scope = { profile: config.server, account: state.user.email.trim().toLowerCase(), authEpoch: lease.epoch };
      if ((owner && sameScope(owner.scope, scope)) || (replica && sameScope(replica.scope, scope))) return;
      reset();
      if (isWorkspaceReplica()) {
        replica = new WorkspaceReplica(scope, config.generation, conversationWorkspace, apply, send);
        replica.hello();
      } else {
        owner = new WorkspaceOwner(scope, config.generation, crypto.randomUUID(), conversationWorkspace,
          projection, (id) => api.conversations.detail(id, { includeState: false }), () => lease.validate(), send);
        conversationWorkspace.setCommand((intent) => owner?.submit(intent) ?? Promise.resolve({ ok: false, reason: 'owner-unavailable' }));
        owner.publish();
      }
    } catch { if (alive && ticket === ownTicket) reset(); }
  };
  const receive = (event: Event) => {
    const value = (event as CustomEvent).detail;
    if (value === null) { reset(); void start(); return; }
    owner?.receive(value as WorkspaceFrame); replica?.receive(value as WorkspaceFrame);
  };
  window.addEventListener('cognis-workspace', receive);
  const stops = [
    auth.subscribe(() => void start()),
    conversationWorkspace.subscribe(() => owner?.publish()),
    pinnedAgents.subscribe(() => owner?.publish()),
    pinnedConversations.subscribe(() => owner?.publish()),
    pinnedBackgroundWork.subscribe(() => owner?.publish()),
    documentCoordination().onInvalidated(() => { ++ticket; reset(); })
  ];
  const discovery = setInterval(() => {
    if (replica) replica.hello(); else if (!owner) void start();
  }, 2000);
  return () => {
    alive = false; ++ticket; reset(); clearInterval(discovery);
    stops.forEach((stop) => stop()); window.removeEventListener('cognis-workspace', receive);
  };
}
