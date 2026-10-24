<script lang="ts">
  import { chatV2Api } from '$lib/chat-v2/api';
  import type { CommandV2Response, RetryProviderOption, RetryProviderOptionsResponse } from '$lib/chat-v2/types';

  let {
    conversationId,
    turnId,
    providerId,
    model,
    retryAt = null,
    onResponse
  }: {
    conversationId: string;
    turnId: string;
    providerId: string | null;
    model: string | null;
    retryAt?: string | null;
    onResponse: (response: CommandV2Response) => Promise<void>;
  } = $props();

  let options = $state<RetryProviderOption[]>([]);
  let busy = $state(false);
  let error = $state('');
  let selected = $state('');
  let switched = $state(false);

  function matches(response: RetryProviderOptionsResponse): boolean {
    return response.turn_id === turnId && response.provider_id === providerId && response.model === model;
  }

  $effect(() => {
    const id = conversationId;
    // Same turn ID can survive several retry generations.
    const identity = [turnId, providerId, model, retryAt];
    const controller = new AbortController();
    options = [];
    error = '';
    selected = '';
    switched = false;
    async function refresh() {
      try {
        const response = await chatV2Api.retryProviderOptions(id, {
          signal: controller.signal, turnId: identity[0] ?? undefined,
          providerId: identity[1], model: identity[2]
        });
        if (!controller.signal.aborted && identity.every((value, index) => value === [turnId, providerId, model, retryAt][index])) {
          options = matches(response) ? response.options : [];
        }
      } catch {
        if (!controller.signal.aborted) options = [];
      }
    }
    void refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void refresh();
    }, 30_000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  });

  async function switchProvider(option: RetryProviderOption) {
    if (busy) return;
    const id = conversationId;
    const identity = [turnId, providerId, model, retryAt];
    const applyResponse = onResponse;
    busy = true;
    error = '';
    try {
      const fresh = await chatV2Api.retryProviderOptions(id, { turnId, providerId, model });
      if (id !== conversationId || !identity.every((value, index) => value === [turnId, providerId, model, retryAt][index])) return;
      options = matches(fresh) ? fresh.options : [];
      if (!options.some((candidate) => candidate.provider_id === option.provider_id && candidate.model === option.model)) {
        error = 'This provider is no longer available.';
        return;
      }
      const txn = crypto.randomUUID();
      const content = `/model ${option.provider_id}/${option.model}`;
      let response: CommandV2Response;
      try {
        response = await chatV2Api.executeCommand(id, txn, content);
      } catch {
        // Reuse the command transaction when delivery is uncertain.
        response = await chatV2Api.executeCommand(id, txn, content);
      }
      await applyResponse(response);
      const selection = response.data.runtime_selection as { provider_id?: string; model?: string } | undefined;
      if (id === conversationId) {
        switched = response.result_type !== 'error' &&
          selection?.provider_id === option.provider_id && selection?.model === option.model;
        if (!switched) error = response.text || 'The provider was not switched.';
      }
    } catch (caught) {
      if (id === conversationId) error = caught instanceof Error ? caught.message : 'Unable to switch provider.';
    } finally {
      busy = false;
      selected = '';
    }
  }
</script>

{#if busy}
  <span class="inline-flex min-h-11 items-center text-xs opacity-80" role="status">Switching provider…</span>
{:else if !switched && options.length === 1}
  <button
    type="button"
    class="inline-flex min-h-11 items-center rounded-sm text-xs opacity-80 underline decoration-current underline-offset-4 hover:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current"
    title="Keep the same model and select this provider"
    onclick={() => void switchProvider(options[0])}
  >Switch to {options[0].display_name}</button>
{:else if !switched && options.length > 1}
  <select
    aria-label="Switch provider for the same model"
    class="min-h-11 max-w-full rounded-sm border-0 bg-transparent text-xs opacity-80 underline decoration-current underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-current"
    bind:value={selected}
    onchange={() => {
      const option = options.find((candidate) => candidate.provider_id === selected);
      if (option) void switchProvider(option);
    }}
  >
    <option value="" disabled>Switch provider…</option>
    {#each options as option (option.provider_id)}
      <option class="bg-surface text-foreground" value={option.provider_id}>Switch to {option.display_name}</option>
    {/each}
  </select>
{/if}
{#if error}
  <p class="text-xs" role="alert">{error}</p>
{/if}
