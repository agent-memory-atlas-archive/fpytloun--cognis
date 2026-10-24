<script lang="ts">
  import { untrack } from 'svelte';

  import Button from '$lib/components/ui/Button.svelte';
  import type { ExecutorConfig, ExecutorRuntimeConfig } from '$lib/types/api';

  type LocalInferenceForm = {
    enabled: boolean;
    managementEnabled: boolean;
    port: number | undefined;
    maxConcurrentPulls: number | undefined;
    diskHeadroomGiB: number | undefined;
    requestTimeoutSeconds: number | undefined;
    modelStorePath: string;
  };

  let {
    executor,
    editable,
    saving = false,
    onSave,
    onDirtyChange
  } = $props<{
    executor: ExecutorConfig;
    editable: boolean;
    saving?: boolean;
    onSave: (config: ExecutorRuntimeConfig) => Promise<void>;
    onDirtyChange?: (dirty: boolean) => void;
  }>();

  function createForm(value: ExecutorConfig): LocalInferenceForm {
    const runtime = value.config.ollama_runtime ?? {};
    return {
      enabled: value.local_inference_enabled,
      managementEnabled: runtime.management_enabled ?? value.ollama_management_enabled,
      port: runtime.port ?? value.ollama_port ?? 11434,
      maxConcurrentPulls: runtime.max_concurrent_pulls ?? 1,
      diskHeadroomGiB: (runtime.disk_headroom_bytes ?? 5 * 1024 ** 3) / 1024 ** 3,
      requestTimeoutSeconds: runtime.request_timeout_seconds ?? 1800,
      modelStorePath: runtime.model_store_path ?? ''
    };
  }

  function formSignature(value: LocalInferenceForm): string {
    return JSON.stringify(value);
  }

  const initialForm = untrack(() => createForm(executor));
  let form = $state<LocalInferenceForm>(initialForm);
  let sourceSignature = $state(formSignature(initialForm));
  let error = $state('');
  let saved = $state(false);
  let saveSequence = 0;

  $effect(() => {
    const next = createForm(executor);
    const nextSignature = formSignature(next);
    if (!saving && nextSignature !== sourceSignature) {
      form = next;
      sourceSignature = nextSignature;
      error = '';
    }
  });

  const dirty = $derived(formSignature(form) !== sourceSignature);
  $effect(() => { onDirtyChange?.(dirty); });
  const validationError = $derived(validateForm(form));
  const reachability = $derived(executor.resource_snapshot?.ollama);
  const statusLabel = $derived(
    executor.local_inference_config_status === 'confirmed'
      ? 'Executor confirmed'
      : executor.local_inference_config_status === 'applying'
        ? 'Applying'
        : 'Not confirmed'
  );

  function validateInteger(
    value: number | undefined,
    label: string,
    minimum: number,
    maximum: number
  ): string | null {
    if (value == null || !Number.isInteger(value) || value < minimum || value > maximum) {
      return `${label} must be an integer from ${minimum} to ${maximum}.`;
    }
    return null;
  }

  function validateForm(value: LocalInferenceForm): string | null {
    return (
      validateInteger(value.port, 'Ollama port', 1, 65535)
      ?? validateInteger(value.maxConcurrentPulls, 'Max concurrent pulls', 1, 8)
      ?? validateInteger(value.diskHeadroomGiB, 'Disk headroom', 0, 1048576)
      ?? validateInteger(value.requestTimeoutSeconds, 'Request timeout', 30, 86400)
    );
  }

  async function save(): Promise<void> {
    const currentError = validateForm(form);
    if (currentError || !editable || saving) {
      error = currentError ?? '';
      return;
    }
    const sequence = ++saveSequence;
    error = '';
    saved = false;
    const runtime = { ...(executor.config.ollama_runtime ?? {}) };
    delete runtime.endpoint;
    const config: ExecutorRuntimeConfig = {
      ...executor.config,
      local_inference_enabled: form.enabled,
      ollama_runtime: {
        ...runtime,
        port: form.port,
        management_enabled: form.managementEnabled,
        max_concurrent_pulls: form.maxConcurrentPulls,
        disk_headroom_bytes: form.diskHeadroomGiB! * 1024 ** 3,
        request_timeout_seconds: form.requestTimeoutSeconds,
        model_store_path: form.modelStorePath.trim() || null
      }
    };
    try {
      await onSave(config);
      if (sequence !== saveSequence) return;
      sourceSignature = formSignature(form);
      saved = true;
    } catch (caughtError) {
      if (sequence !== saveSequence) return;
      error = caughtError instanceof Error ? caughtError.message : 'Unable to save local inference settings.';
    }
  }
</script>

<section
  class="space-y-4 rounded-2xl border border-accent/20 bg-accent-subtle p-4"
  aria-labelledby={`local-inference-${executor.executor_id}`}
  data-testid="local-inference-settings"
>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    <div>
      <h4 id={`local-inference-${executor.executor_id}`} class="font-medium text-strong">
        Local inference
      </h4>
      <p class="mt-1 text-xs text-muted">
        Ollama is always restricted to the executor loopback interface.
      </p>
    </div>
    <span
      class={`w-fit rounded-full border px-2.5 py-1 text-xs ${
        executor.local_inference_config_status === 'confirmed'
          ? 'border-success-border bg-success-subtle text-success'
          : executor.local_inference_config_status === 'applying'
            ? 'border-accent/30 bg-accent-subtle text-accent'
            : 'border-warning-border bg-warning-subtle text-warning'
      }`}
      aria-live="polite"
    >
      {statusLabel}
    </span>
  </div>

  <div class="grid gap-3 md:grid-cols-2">
    <label class="flex min-h-12 items-start gap-3 rounded-xl border border-separator bg-canvas/45 px-3 py-3 text-sm text-foreground">
      <input
        bind:checked={form.enabled}
        type="checkbox"
        role="switch"
        disabled={!editable || saving}
        class="mt-0.5 rounded border-control-border bg-canvas text-accent focus:ring-accent disabled:opacity-50"
      />
      <span>
        <span class="block font-medium text-strong">Enable local inference</span>
        <span class="mt-1 block text-xs text-quiet">Routes inference, discovery, and media work here.</span>
      </span>
    </label>

    <label class="flex min-h-12 items-start gap-3 rounded-xl border border-separator bg-canvas/45 px-3 py-3 text-sm text-foreground">
      <input
        bind:checked={form.managementEnabled}
        type="checkbox"
        role="switch"
        disabled={!editable || saving || !form.enabled}
        class="mt-0.5 rounded border-control-border bg-canvas text-accent focus:ring-accent disabled:opacity-50"
      />
      <span>
        <span class="block font-medium text-strong">Allow Cognis to manage Ollama models</span>
        <span class="mt-1 block text-xs text-quiet">Permits managed pull and delete operations.</span>
      </span>
    </label>
  </div>

  <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
    <label class="space-y-1 text-sm text-foreground">
      <span>Ollama port</span>
      <input
        bind:value={form.port}
        type="number"
        min="1"
        max="65535"
        step="1"
        inputmode="numeric"
        disabled={!editable || saving}
        aria-describedby={`ollama-port-help-${executor.executor_id}`}
        class="min-h-10 w-full rounded-xl border border-control-border bg-canvas/80 px-3 py-2 text-sm text-foreground disabled:opacity-60"
      />
    </label>
    <div class="rounded-xl border border-separator bg-canvas/45 px-3 py-2 text-xs text-muted">
      <p class="font-mono text-foreground">{executor.ollama_endpoint}</p>
      <p id={`ollama-port-help-${executor.executor_id}`} class="mt-1">
        Set <code>OLLAMA_HOST=127.0.0.1:{form.port ?? 11434}</code> before <code>ollama serve</code>.
        Ollama must listen on this exact loopback port.
      </p>
    </div>
  </div>

  <dl class="grid gap-2 text-xs sm:grid-cols-3">
    <div class="rounded-xl border border-separator bg-canvas/45 px-3 py-2">
      <dt class="text-quiet">Desired</dt>
      <dd class="mt-1 text-foreground">
        {form.enabled ? 'Inference on' : 'Inference off'} · port {form.port ?? 'invalid'}
      </dd>
    </div>
    <div class="rounded-xl border border-separator bg-canvas/45 px-3 py-2">
      <dt class="text-quiet">Applied generation</dt>
      <dd class="mt-1 text-foreground">v{executor.applied_config_version} / desired v{executor.desired_config_version}</dd>
    </div>
    <div class="rounded-xl border border-separator bg-canvas/45 px-3 py-2">
      <dt class="text-quiet">Detected Ollama</dt>
      <dd class="mt-1 text-foreground">
        {reachability?.status === 'reachable'
          ? `Reachable${reachability.version ? ` · v${reachability.version}` : ''}`
          : reachability?.status === 'unreachable'
            ? 'Not reachable'
            : 'Unknown'}
      </dd>
    </div>
  </dl>

  <details class="rounded-xl border border-separator bg-canvas/35 px-3 py-3">
    <summary class="cursor-pointer text-sm font-medium text-secondary">Advanced settings</summary>
    <div class="mt-3 grid gap-3 sm:grid-cols-2">
      <label class="space-y-1 text-xs text-secondary">
        <span>Max concurrent pulls</span>
        <input bind:value={form.maxConcurrentPulls} type="number" min="1" max="8" step="1" disabled={!editable || saving} class="min-h-10 w-full rounded-xl border border-control-border bg-canvas/80 px-3 py-2 text-sm text-foreground disabled:opacity-60" />
      </label>
      <label class="space-y-1 text-xs text-secondary">
        <span>Disk headroom GiB</span>
        <input bind:value={form.diskHeadroomGiB} type="number" min="0" max="1048576" step="1" disabled={!editable || saving} class="min-h-10 w-full rounded-xl border border-control-border bg-canvas/80 px-3 py-2 text-sm text-foreground disabled:opacity-60" />
      </label>
      <label class="space-y-1 text-xs text-secondary">
        <span>Request timeout seconds</span>
        <input bind:value={form.requestTimeoutSeconds} type="number" min="30" max="86400" step="1" disabled={!editable || saving} class="min-h-10 w-full rounded-xl border border-control-border bg-canvas/80 px-3 py-2 text-sm text-foreground disabled:opacity-60" />
      </label>
      <label class="space-y-1 text-xs text-secondary">
        <span>Optional model-store path</span>
        <input bind:value={form.modelStorePath} type="text" placeholder="/absolute/path/to/models" disabled={!editable || saving} class="min-h-10 w-full rounded-xl border border-control-border bg-canvas/80 px-3 py-2 text-sm text-foreground disabled:opacity-60" />
      </label>
    </div>
  </details>

  {#if validationError || error}
    <p class="text-sm text-danger" role="alert">{validationError ?? error}</p>
  {:else if saved}
    <p class="text-sm text-success" role="status">Local inference settings saved.</p>
  {:else if !editable}
    <p class="text-xs text-quiet">Read-only. Only the executor owner or an administrator can edit these settings.</p>
  {/if}

  {#if editable}
    <div class="flex justify-end">
      <Button
        variant="primary"
        size="sm"
        disabled={saving || !dirty || validationError !== null}
        onclick={save}
      >
        {saving ? 'Saving…' : 'Save'}
      </Button>
    </div>
  {/if}
</section>
