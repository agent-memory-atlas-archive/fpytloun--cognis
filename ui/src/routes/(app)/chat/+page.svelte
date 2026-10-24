<script lang="ts">
  import { afterNavigate, goto } from '$app/navigation';
  import { onMount } from 'svelte';

  import LoadingState from '$lib/components/LoadingState.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { api } from '$lib/api/client';
  import { isOfflineError } from '$lib/offline/cache';
  import {
    CHAT_STORAGE_KEYS,
    dedupeLastOpenedConversationEntries,
    lastOpenedConversationEntry,
    lastOpenedConversationStorageKey,
    parseLastOpenedConversationEntry,
    serializeLastOpenedConversationEntry,
  } from '$lib/chat-page';
  import type { Agent, Conversation, LastOpenedConversationCandidate } from '$lib/types/api';

  let loading = true;
  let error = '';
  let noAgents = false;
  let loadingSlow = false;
  let loadingSlowTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;
  let resolution = 0;
  let requestedLocation: string | null = null;

  function storedAgentIds(value: string | null): string[] {
    if (!value || value === 'all') return [];
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.filter((item): item is string => typeof item === 'string' && item.length > 0);
      }
    } catch {
      // Backwards-compatible single selected-agent storage.
    }
    return [value];
  }

  function getSelectedAgentId(agents: Agent[]): string {
    const primary = agents.filter((a) => a.agent_type === 'primary');
    if (typeof window !== 'undefined') {
      const stored = window.localStorage.getItem(CHAT_STORAGE_KEYS.selectedAgent);
      const selected = storedAgentIds(stored);
      if (selected.length === 1 && primary.some((a) => a.agent_id === selected[0] && a.status === 'active')) {
        return selected[0];
      }
    }
    return primary.find((a) => a.status === 'active')?.agent_id ?? primary[0]?.agent_id ?? '';
  }

  /**
   * Read the global last-opened entry from localStorage (survives PWA relaunches).
   * This is the conversation-first restore path: we prefer the last-opened
   * conversation's agent over the UI-selected agent so PWA cold-starts always
   * land on the genuinely last-active chat.
   */
  function globalLastOpenedEntry(): LastOpenedConversationCandidate | null {
    if (typeof window === 'undefined') return null;
    return parseLastOpenedConversationEntry(
      window.localStorage.getItem(CHAT_STORAGE_KEYS.lastOpenedConversation),
    );
  }

  function lastOpenedConversationCandidates(selectedAgentId: string): LastOpenedConversationCandidate[] {
    if (typeof window === 'undefined') return [];
    const agentKey = lastOpenedConversationStorageKey(selectedAgentId);
    return dedupeLastOpenedConversationEntries([
      window.sessionStorage.getItem(agentKey),
      window.localStorage.getItem(agentKey),
      window.sessionStorage.getItem(CHAT_STORAGE_KEYS.lastOpenedConversation),
      window.localStorage.getItem(CHAT_STORAGE_KEYS.lastOpenedConversation),
    ].map(parseLastOpenedConversationEntry).filter((value): value is LastOpenedConversationCandidate => value !== null));
  }

  function rememberOpenedConversation(conversation: Conversation): void {
    if (typeof window === 'undefined') return;
    const entry = serializeLastOpenedConversationEntry(lastOpenedConversationEntry(conversation));
    window.sessionStorage.setItem(CHAT_STORAGE_KEYS.lastOpenedConversation, entry);
    window.sessionStorage.setItem(lastOpenedConversationStorageKey(conversation.agent_id), entry);
    window.localStorage.setItem(CHAT_STORAGE_KEYS.lastOpenedConversation, entry);
    window.localStorage.setItem(lastOpenedConversationStorageKey(conversation.agent_id), entry);
  }

  function clearLoadingSlowTimer(): void {
    if (loadingSlowTimer !== null) {
      clearTimeout(loadingSlowTimer);
      loadingSlowTimer = null;
    }
  }

  function startLoadingSlowTimer(): void {
    clearLoadingSlowTimer();
    loadingSlow = false;
    loadingSlowTimer = setTimeout(() => {
      loadingSlowTimer = null;
      loadingSlow = true;
    }, 10_000);
  }

  async function openDefaultConversation(): Promise<void> {
    const request = ++resolution;
    const isCurrent = () => !disposed && request === resolution;
    loading = true;
    error = '';
    noAgents = false;
    startLoadingSlowTimer();
    const params = new URLSearchParams(window.location.search);
    const directAgent = params.get('scope') === 'agent_direct' ? params.get('agent_id') : null;
    try {
      // Explicit main-agent navigation must not restore an arbitrary topic,
      // including when the canonical link opens in a new browser tab.
      if (directAgent) {
        const conversation = await api.conversations.resolve({
          agent_id: directAgent, context_type: 'web', scope: 'agent_direct',
        });
        if (!isCurrent()) return;
        rememberOpenedConversation(conversation);
        await goto(`/chat/${conversation.conversation_id}`, { replaceState: true });
        return;
      }
      // Conversation-first restore: use the last-opened conversation's agent
      // as the primary agent for the open request. This ensures PWA cold-starts
      // (where sessionStorage is empty) always restore the genuinely last-active
      // chat rather than defaulting to the first primary agent's latest conversation.
      const globalEntry = globalLastOpenedEntry();
      const globalAgentId = globalEntry?.agent_id ?? null;

      const openFor = (agentId: string): Promise<Conversation> => {
        const candidates = lastOpenedConversationCandidates(agentId);
        return api.conversations.open({
          agent_id: agentId,
          context_type: 'web',
          include_state: false,
          candidate_conversations: candidates,
          candidate_conversation_ids: candidates.map((candidate) => candidate.conversation_id),
        });
      };

      // On slow links the agents -> open waterfall costs a full round trip.
      // When a last-opened agent is known, open its conversation in parallel
      // and keep the result only if the agent is still an active primary.
      const speculativeOpen = globalAgentId
        ? openFor(globalAgentId).then(
            (conversation) => conversation,
            () => null,
          )
        : null;

      const agents = await api.agents.listAll();
      if (!isCurrent()) return;
      const primary = agents.filter((a) => a.agent_type === 'primary');

      // Resolve the agent to request: prefer the last-opened conversation's
      // agent if it is still active, otherwise fall back to the UI selection.
      const globalAgentValid = Boolean(
        globalAgentId && primary.some((a) => a.agent_id === globalAgentId && a.status === 'active')
      );
      const resolvedAgentId = globalAgentValid && globalAgentId
        ? globalAgentId
        : getSelectedAgentId(agents);

      if (!resolvedAgentId) {
        noAgents = true;
        loading = false;
        return;
      }

      const speculative = globalAgentValid && speculativeOpen ? await speculativeOpen : null;
      const conversation = speculative ?? await openFor(resolvedAgentId);
      if (!isCurrent()) return;
      rememberOpenedConversation(conversation);
      await goto(`/chat/${conversation.conversation_id}`, { replaceState: true });
    } catch (caughtError) {
      if (!isCurrent()) return;
      // Offline cold start: open the last conversation from the device cache
      // instead of failing on the server-side resolution.
      const lastEntry = globalLastOpenedEntry();
      if (!directAgent && isOfflineError(caughtError) && lastEntry?.conversation_id) {
        await goto(`/chat/${lastEntry.conversation_id}`, { replaceState: true });
        return;
      }
      error = caughtError instanceof Error ? caughtError.message : 'Unable to load conversations.';
    } finally {
      if (isCurrent()) {
        loading = false;
        clearLoadingSlowTimer();
      }
    }
  }

  function openRequestedConversation(): void {
    const location = window.location.href;
    if (disposed || requestedLocation === location) return;
    requestedLocation = location;
    void openDefaultConversation();
  }

  onMount(() => {
    // Auth and device-storage gates may mount this page after navigation finished.
    // Do not rely on afterNavigate to deliver that already-completed navigation.
    openRequestedConversation();
    return () => {
      disposed = true;
      resolution++;
      clearLoadingSlowTimer();
    };
  });
  // SvelteKit reuses this page when only the requested main agent changes.
  afterNavigate(openRequestedConversation);
</script>

<svelte:head>
  <title>Chat · Cognis</title>
</svelte:head>

{#if loading}
  {#if loadingSlow}
    <section class="rounded-3xl border border-info-border bg-info-subtle px-6 py-10 text-center text-sm text-info">
      <p class="font-medium">Chat is still opening.</p>
      <p class="mt-2 text-secondary">Resolving your default conversation is taking longer than expected.</p>
      <div class="mt-4 flex justify-center gap-3">
        <Button variant="secondary" onclick={() => void openDefaultConversation()}>Retry</Button>
        <Button onclick={() => goto('/chat/new')}>Start a new conversation</Button>
      </div>
    </section>
  {:else}
    <LoadingState label="Opening chat" description="Resolving your default conversation." />
  {/if}
{:else if noAgents}
  <section class="rounded-3xl border border-info-border bg-info-subtle px-6 py-10 text-center text-sm text-info">
    <p>Create an agent first before starting a conversation.</p>
    <div class="mt-4 flex justify-center gap-3">
      <Button onclick={() => goto('/agents')}>Open agents</Button>
    </div>
  </section>
{:else if error}
  <section class="rounded-3xl border border-danger-border bg-danger-subtle px-6 py-10 text-center text-sm text-danger">
    <p>{error}</p>
    <div class="mt-4 flex justify-center gap-3">
      <Button onclick={() => goto('/agents')}>Open agents</Button>
      <Button variant="secondary" onclick={() => goto('/chat/new')}>Start a new conversation</Button>
    </div>
  </section>
{/if}
