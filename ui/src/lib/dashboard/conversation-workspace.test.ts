import { describe, it, expect, vi } from 'vitest';
vi.mock('$lib/api/client', () => ({ api: { conversations: { detail: async (id: string) => conversation(id) } } }));
import type { Conversation } from '$lib/types/api';
import { ConversationWorkspace, conversationWorkspaceStorageKey, retainedConversationId } from './conversation-workspace';
import { WorkspaceManager, serializeWorkspaceWindows, dashboardWorkspaceStorageKey } from './workspace';

const safe = { x: 0, y: 0, width: 1440, height: 900 };
const email = 'owner@cognis.test';
function conversation(id: string, project: string | null = null): Conversation {
  return { conversation_id: id, project_id: project, title: `Chat ${id}`, agent_id: 'agent-one', status: 'active' } as Conversation;
}
function setup() {
  const workspace = new ConversationWorkspace();
  localStorage.clear();
  workspace.setOwner(email, localStorage);
  return workspace;
}
function manager() { return new WorkspaceManager('desktop', safe); }

describe('shared retained conversations', () => {
  it('defaults half-hide only when unset and preserves an explicit stored false', () => {
    expect(setup().snapshot().tucked).toBe(true);
    localStorage.setItem(conversationWorkspaceStorageKey('explicit@cognis.test'),
      JSON.stringify({ version: 1, entries: [], agents: [], tucked: false }));
    const explicit = new ConversationWorkspace();
    explicit.setOwner('explicit@cognis.test', localStorage);
    expect(explicit.snapshot().tucked).toBe(false);
    localStorage.setItem(conversationWorkspaceStorageKey('unset@cognis.test'),
      JSON.stringify({ version: 1, entries: [], agents: [] }));
    const unset = new ConversationWorkspace();
    unset.setOwner('unset@cognis.test', localStorage);
    expect(unset.snapshot().tucked).toBe(true);
  });
  it('projects pin/unpin into dashboards without losing native task windows', async () => {
    const workspace = setup();
    const main = manager();
    main.open({ kind: 'task', entityId: 'task-one', title: 'Task', canonicalHref: '/tasks/task-one' });
    const stop = workspace.bind(main, null, dashboardWorkspaceStorageKey(email));
    expect(await workspace.pin(conversation('chat-one'))).toBe(true);
    expect(main.snapshot().map((window) => window.kind)).toEqual(['task', 'conversation']);
    main.minimize('conversation:chat-one');
    expect(workspace.snapshot().entries).toHaveLength(1);
    await main.close('conversation:chat-one');
    expect(workspace.snapshot().entries).toHaveLength(0);
    expect(main.snapshot()[0].kind).toBe('task');
    stop();
  });

  it('retains window chats when navigating out and closes from either presentation', async () => {
    const workspace = setup();
    const main = manager();
    const stop = workspace.bind(main, null, dashboardWorkspaceStorageKey(email));
    await main.requestOpen({ kind: 'conversation', entityId: 'chat-one', title: 'Chat', agentId: 'agent-one', canonicalHref: '/chat/chat-one' });
    expect(workspace.snapshot().entries).toHaveLength(1);
    stop();
    const project = manager();
    workspace.updateConversation(conversation('chat-one', 'project-one'));
    const stopProject = workspace.bind(project, 'project-one', 'project-one-layout');
    expect(project.snapshot()).toHaveLength(1);
    await workspace.unpin('conversation:chat-one');
    expect(project.snapshot()).toHaveLength(0);
    stopProject();
  });

  it('filters projects without removing unrelated pins and retains layouts per scope', async () => {
    const workspace = setup();
    await workspace.pin(conversation('chat-one', 'project-one'));
    await workspace.pin(conversation('chat-two', 'project-two'));
    const first = manager();
    const stop = workspace.bind(first, 'project-one', 'project-one-layout');
    expect(first.snapshot().map((window) => window.entityId)).toEqual(['chat-one']);
    first.minimize('conversation:chat-one');
    stop();
    const second = manager();
    const stopSecond = workspace.bind(second, 'project-two', 'project-two-layout');
    await second.close('conversation:chat-two');
    expect(workspace.snapshot().entries.map((entry) => entry.window.entityId)).toEqual(['chat-one']);
    stopSecond();
    const restored = manager();
    const stopRestored = workspace.bind(restored, 'project-one', 'project-one-layout');
    expect(restored.snapshot()[0].minimized).toBe(true);
    stopRestored();
  });

  it('deduplicates resolved agent and explicit conversation windows', async () => {
    const workspace = setup();
    await workspace.pin(conversation('chat-one'));
    const main = manager();
    const stop = workspace.bind(main, null, 'main-layout');
    await main.requestOpen({ kind: 'agent', entityId: 'agent-one', agentId: 'agent-one', title: 'Agent', canonicalHref: '/agents/agent-one' });
    await main.setResolvedConversation('agent:agent-one', 'chat-one');
    expect(workspace.snapshot().entries).toHaveLength(1);
    expect(main.snapshot()).toHaveLength(1);
    expect(retainedConversationId(main.snapshot()[0])).toBe('chat-one');
    stop();
  });

  it('persists per account, fences account switches, and clamps dock position', async () => {
    const workspace = setup();
    await workspace.pin(conversation('chat-one'));
    workspace.setPosition(5);
    const restored = new ConversationWorkspace();
    restored.setOwner(email, localStorage);
    expect(restored.snapshot().entries).toHaveLength(1);
    expect(restored.snapshot().position).toBe(1);
    restored.setOwner('other@cognis.test', localStorage);
    expect(restored.snapshot().entries).toEqual([]);
    restored.setOwner(null, null);
    expect(await restored.pin(conversation('chat-two'))).toBe(false);
    expect(localStorage.getItem(conversationWorkspaceStorageKey(email))).toContain('chat-one');
  });

  it('migrates main windows once while leaving project windows independent', async () => {
    localStorage.clear();
    const legacy = manager();
    legacy.open({ kind: 'conversation', entityId: 'chat-one', title: 'Chat', canonicalHref: '/chat/chat-one' });
    legacy.minimize('conversation:chat-one');
    localStorage.setItem(dashboardWorkspaceStorageKey(email), serializeWorkspaceWindows(legacy.snapshot()));
    const projectKey = `cognis-project-workspace:${encodeURIComponent(email)}:project-one`;
    localStorage.setItem(projectKey, serializeWorkspaceWindows(legacy.snapshot()));
    const workspace = new ConversationWorkspace();
    workspace.setOwner(email, localStorage);
    expect(workspace.snapshot().entries).toHaveLength(1);
    expect(Object.keys(workspace.snapshot().entries[0].layouts)).toEqual(['dashboard']);
    expect(localStorage.getItem(projectKey)).toBe(serializeWorkspaceWindows(legacy.snapshot()));
    expect(workspace.snapshot().entries[0].window.minimized).toBe(true);
    await workspace.unpin('conversation:chat-one');
    const restored = new ConversationWorkspace();
    restored.setOwner(email, localStorage);
    expect(restored.snapshot().entries).toEqual([]);
  });

  it('remembers selection per agent across reloads without accepting another agent tab', async () => {
    const workspace = setup();
    await workspace.pin(conversation('chat-one'));
    await workspace.pin({ ...conversation('chat-two'), agent_id: 'agent-two' });
    await workspace.rememberSelection('agent-one', 'conversation:chat-one');
    await workspace.rememberSelection('agent-one', 'conversation:chat-two');
    await workspace.rememberSelection('agent-two', 'home:agent-two');
    const restored = new ConversationWorkspace();
    restored.setOwner(email, localStorage);
    expect(restored.snapshot().agents.map((agent) => agent.lastSelectedKey))
      .toEqual(['conversation:chat-one', 'home:agent-two']);
    await restored.unpin('conversation:chat-one');
    restored.setOwner('other@cognis.test', localStorage);
    expect(restored.snapshot().agents).toEqual([]);
  });

  it('retains agent Home independently of closing its dashboard windows or final tab', async () => {
    const workspace = setup();
    await workspace.pin(conversation('chat-one'));
    workspace.setHome('agent-one', conversation('home-one'));
    const main = manager();
    const stop = workspace.bind(main, null, 'main-layout');
    await workspace.unpin('conversation:chat-one');
    expect(workspace.snapshot().entries).toEqual([]);
    expect(workspace.snapshot().agents).toEqual([{ agentId: 'agent-one', homeConversationId: 'home-one' }]);
    expect(main.snapshot()).toEqual([]);
    workspace.setTucked(true);
    const restored = new ConversationWorkspace();
    restored.setOwner(email, localStorage);
    expect(restored.snapshot().agents).toEqual(workspace.snapshot().agents);
    expect(restored.snapshot().tucked).toBe(true);
    await workspace.pin(conversation('home-one'));
    await main.close('conversation:home-one');
    expect(workspace.snapshot().agents[0].homeConversationId).toBe('home-one');
    await workspace.unpinAgent('agent-one');
    expect(workspace.snapshot().agents).toEqual([]);
    expect(workspace.snapshot().entries).toEqual([]);
    stop();
  });

  it('minimizes excess dashboard projections instead of losing pins', async () => {
    const workspace = setup();
    for (let index = 0; index < 7; index++) await workspace.pin(conversation(`chat-${index}`));
    const main = manager();
    const stop = workspace.bind(main, null, 'main-layout');
    expect(main.snapshot()).toHaveLength(7);
    expect(main.snapshot().filter((window) => !window.minimized)).toHaveLength(5);
    main.minimize(main.snapshot()[0].key);
    expect(workspace.snapshot().entries).toHaveLength(7);
    stop();
  });

  it('preserves per-scope stacking and switcher ordering after reload', async () => {
    const workspace = setup();
    for (let index = 0; index < 3; index++) await workspace.pin(conversation(`chat-${index}`));
    const main = manager();
    const stop = workspace.bind(main, null, 'main-layout');
    main.focus('conversation:chat-0');
    main.reorderSwitcher('conversation:chat-2', 'conversation:chat-0', 'before');
    const before = main.snapshot();
    stop();
    const restored = new ConversationWorkspace();
    restored.setOwner(email, localStorage);
    const projected = manager();
    const stopRestored = restored.bind(projected, null, 'main-layout');
    expect(projected.snapshot().map(({ key, zOrder, switcherOrder }) => ({ key, zOrder, switcherOrder })))
      .toEqual(before.map(({ key, zOrder, switcherOrder }) => ({ key, zOrder, switcherOrder })));
    stopRestored();
  });

  it('preserves temporary show-dashboard visibility during canonical metadata updates', async () => {
    const workspace = setup();
    await workspace.pin(conversation('chat-one'));
    const main = manager();
    const stop = workspace.bind(main, null, 'main-layout');
    main.showDashboard();
    workspace.updateConversation({ ...conversation('chat-one'), title: 'Updated title', status: 'closed' });
    expect(main.hasDashboardSnapshot()).toBe(true);
    expect(main.snapshot()[0].minimized).toBe(true);
    main.restoreDashboard();
    expect(main.snapshot()[0].minimized).toBe(false);
    expect(main.snapshot()[0].title).toBe('Updated title');
    stop();
  });
});
