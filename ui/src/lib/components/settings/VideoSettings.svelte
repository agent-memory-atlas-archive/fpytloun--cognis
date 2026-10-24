<script lang="ts">
  import { api } from '$lib/api/client';
  import Button from '$lib/components/ui/Button.svelte';
  import type { VideoPolicy } from '$lib/video';

  let open = $state(false);
  let policy = $state<VideoPolicy | null>(null);
  let bounds = $state<{ model: string; amount: string | number }[]>([]);
  let models = $state<{ value: string; label: string }[]>([]);
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');

  async function load() {
    if ((policy && !error) || busy) return;
    busy = true; error = '';
    try {
      if (!policy) {
        const value = await api.videos.policy();
        bounds = Object.entries(value.model_max_cost_usd).map(([model, amount]) => ({ model, amount }));
        policy = value;
      }
      const page = await api.llmProviders.list();
      models = page.items.flatMap((provider) => {
        const entries = provider.models;
        if (!Array.isArray(entries)) return [];
        return entries.flatMap((entry) => {
          if (!entry || typeof entry !== 'object' || typeof entry.model_id !== 'string') return [];
          if (!['video', 'video_generation'].includes(entry.model_mode ?? '') && !entry.supports_video_generation) return [];
          return [{ value: `${provider.provider_id}/${entry.model_id}`, label: `${entry.display_name || entry.model_id} · ${provider.display_name}` }];
        });
      });
    } catch (reason) { error = String(reason); }
    finally { busy = false; }
  }

  async function save() {
    if (!policy || busy) return;
    busy = true; error = ''; notice = '';
    try {
      const costs: Record<string, string | number> = policy.enabled ? {} : policy.model_max_cost_usd;
      for (const row of policy.enabled ? bounds : []) {
        if (!row.model || !Number.isFinite(Number(row.amount)) || Number(row.amount) <= 0) {
          throw new Error('Choose a model and enter a positive estimate for each row.');
        }
        if (row.model in costs) throw new Error('Each model may have only one estimate.');
        costs[row.model] = row.amount;
      }
      policy = await api.videos.savePolicy({ ...policy, model_max_cost_usd: costs });
      notice = 'Video spending limits saved.';
    } catch (reason) { error = String(reason); }
    finally { busy = false; }
  }
</script>

<details class="border-t border-separator pt-4" bind:open ontoggle={(event) => { if (event.currentTarget.open) void load(); }}>
  <summary class="cursor-pointer py-2 text-sm font-medium text-foreground">Advanced: video spending limits</summary>
  <div class="mt-3 space-y-4">
    <p class="text-sm text-muted">Optional limits for your account. Off by default. Video tools work without them; provider charges still apply.</p>
    {#if error}
      <p role="alert" class="text-sm text-danger">{error}</p>
      <Button variant="secondary" onclick={load} disabled={busy}>Retry loading models</Button>
    {/if}
    {#if notice}<p role="status" class="text-sm text-success">{notice}</p>{/if}
    {#if policy}
      <label class="flex min-h-11 items-center gap-3 text-sm">
        <input type="checkbox" bind:checked={policy.enabled} disabled={busy} />
        Apply video spending limits
      </label>
      {#if policy.enabled}
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="text-sm">Per video (USD)<input class="mt-1 block w-full rounded-xl border border-control-border bg-canvas p-3" type="number" min="0.01" max="1000" step="0.01" bind:value={policy.per_job_usd} disabled={busy} /></label>
          <label class="text-sm">Per day (USD)<input class="mt-1 block w-full rounded-xl border border-control-border bg-canvas p-3" type="number" min="0.01" max="10000" step="0.01" bind:value={policy.daily_usd} disabled={busy} /></label>
        </div>
        <p class="text-sm text-muted">Add a conservative cost estimate for each model you use. Cognis reserves that amount before starting a video. These limits are not provider-enforced price caps.</p>
        {#each bounds as row, index}
          <div class="grid gap-2 sm:grid-cols-[minmax(0,1fr)_7rem_auto] sm:items-end">
            <label class="min-w-0 text-sm">Video model
              <select class="mt-1 block w-full min-w-0 rounded-xl border border-control-border bg-canvas p-3" bind:value={row.model} disabled={busy}>
                <option value="">Select model</option>
                {#if row.model && !models.some((model) => model.value === row.model)}
                  <option value={row.model}>{row.model}</option>
                {/if}
                {#each models as model}<option value={model.value}>{model.label}</option>{/each}
              </select>
            </label>
            <label class="text-sm">Estimate (USD)<input class="mt-1 w-full rounded-xl border border-control-border bg-canvas p-3" type="number" min="0.01" step="0.01" bind:value={row.amount} disabled={busy} /></label>
            <Button variant="secondary" disabled={busy} onclick={() => bounds = bounds.filter((_, i) => i !== index)}>Remove</Button>
          </div>
        {/each}
        <Button variant="secondary" disabled={busy || !models.length} onclick={() => bounds = [...bounds, { model: '', amount: '' }]}>Add model estimate</Button>
        {#if !models.length}<p class="text-sm text-muted">Add or discover a video model under Providers first.</p>{/if}
      {/if}
      <div><Button onclick={save} disabled={busy}>{busy ? 'Saving…' : 'Save limits'}</Button></div>
    {:else if busy}
      <p class="text-sm text-muted">Loading…</p>
    {:else}
      <Button variant="secondary" onclick={load}>Retry</Button>
    {/if}
  </div>
</details>
