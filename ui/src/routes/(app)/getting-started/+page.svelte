<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api, asApiError } from '$lib/api/client';
  import { initialSetupStep, loadSetupDraft, saveSetupDraft } from '$lib/onboarding-setup';
  import OnboardingModels from '$lib/components/settings/OnboardingModels.svelte';
  import OnboardingExecutor from '$lib/components/settings/OnboardingExecutor.svelte';
  import OnboardingAgent from '$lib/components/settings/OnboardingAgent.svelte';
  import { auth } from '$lib/stores/auth';
  import LoadingState from '$lib/components/LoadingState.svelte';
  import type { SystemDiagnostics } from '$lib/types/api';

  const steps = ['Configure LLM provider', 'Setup executor', 'Create agent'];
  let step = $state(0);
  let loading = $state(true);
  let closing = $state(false);
  let error = $state('');
  let diagnostics = $state<SystemDiagnostics | null>(null);
  let executorId = $state('');
  async function refresh(): Promise<void> {
    diagnostics = await api.system.diagnostics();
  }
  async function close() {
    closing = true;
    try { await api.system.finishOnboarding('dismissed'); await goto('/'); }
    catch (caught) { error = asApiError(caught).message; }
    finally { closing = false; }
  }
  function next() { step = Math.min(2, step + 1); }
  function executorConnected(id: string) {
    try {
      saveSetupDraft(auth.getSnapshot().user!.email, { executorId: id });
      executorId = id;
      next();
    } catch { error = 'Could not save setup progress. Allow browser storage and try again.'; }
  }
  onMount(() => {
    if (auth.getSnapshot().user?.role !== 'admin') { loading = false; return; }
    executorId = loadSetupDraft(auth.getSnapshot().user!.email).executorId ?? '';
    void refresh().then(() => { step = initialSetupStep(diagnostics!.readiness); })
      .catch((caught) => { error = asApiError(caught).message; }).finally(() => { loading = false; });
  });
</script>

<svelte:head><title>Setup · Cognis</title></svelte:head>

{#if loading}
  <LoadingState label="Preparing setup" description="Loading your saved configuration." />
{:else}
  <section class="mx-auto w-full max-w-2xl py-4 md:py-10">
    <div class="mb-8 flex items-center justify-between gap-4">
      <p class="text-sm font-medium text-secondary">Set up Cognis</p>
      <button type="button" class="text-xs text-muted underline hover:text-strong" onclick={close} disabled={closing}>Close setup</button>
    </div>
    {#if error}<p role="alert" class="mb-5 text-sm text-danger">{error}</p>{/if}
    {#if diagnostics}
      <ol class="mb-8 grid grid-cols-3 gap-3" aria-label="Setup progress">
        {#each steps as label, index}
          <li aria-current={index === step ? 'step' : undefined} class={`border-t-2 pt-3 text-xs leading-5 ${index <= step ? 'border-accent text-foreground' : 'border-separator text-quiet'}`}>
            <span class="mr-1">{index < step ? '✓' : index + 1}.</span>{label}
          </li>
        {/each}
      </ol>
      <div class="rounded-2xl border border-separator bg-surface/60 p-5 md:p-8">
        <p class="mb-3 text-xs text-quiet">Step {step + 1} of 3</p>
        {#if step === 0}
          <OnboardingModels onChanged={refresh} onContinue={next} />
        {:else if step === 1}
          <OnboardingExecutor initialExecutorId={executorId} onChanged={refresh} onContinue={executorConnected} />
        {:else}
          <OnboardingAgent selectedExecutorId={executorId} onBack={() => { step = 1; }} />
        {/if}
      </div>
      {#if step > 0}
        <button type="button" class="mt-5 text-sm text-muted hover:text-strong" onclick={() => { step -= 1; }}>← Back</button>
      {/if}
      <p class="mt-6 text-xs text-quiet">Closing or finishing hides setup. You can reopen it from Settings.</p>
    {:else if !error}
      <p class="text-sm text-muted">An administrator needs to complete the initial setup.</p>
    {/if}
  </section>
{/if}
