<script lang="ts">
  import BlockingDialog from '$lib/components/ui/BlockingDialog.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import X from 'lucide-svelte/icons/x';
  import Link from 'lucide-svelte/icons/link';
  import type { ShareLinkOptions } from './share-options';
  let { createLink, onClose, allowModeChoice = true, defaultMode = 'view', onCopied }: {
    createLink: (options: ShareLinkOptions) => Promise<string>; onClose: () => void;
    allowModeChoice?: boolean; defaultMode?: 'view' | 'download'; onCopied?: () => void;
  } = $props();
  let mode = $state<'view' | 'download'>('view');
  $effect(() => { mode = defaultMode; });
  let expiration = $state('7');
  let custom = $state('');
  let busy = $state(false);
  let url = $state('');
  let error = $state('');
  let copied = $state(false);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  function close() { if (!busy) onClose(); }
  async function copy() {
    try { await navigator.clipboard.writeText(url); copied = true; onCopied?.(); }
    catch { error = 'Select the link below and copy it manually.'; }
  }
  async function create() {
    let options: ShareLinkOptions;
    if (expiration === 'custom') {
      const date = new Date(custom);
      const duration = date.getTime() - Date.now();
      if (!custom || !Number.isFinite(duration) || duration < 60000 || duration > 90 * 86400000) {
        error = 'Choose an expiration between one minute and 90 days from now.'; return;
      }
      options = { expires_at: date.toISOString() };
    } else options = { ttl_seconds: Number(expiration) * 86400 };
    if (allowModeChoice) options.mode = mode;
    busy = true; error = ''; url = ''; copied = false;
    try { url = await createLink(options); await copy(); }
    catch (caught) { error = caught instanceof Error ? caught.message : 'Could not create a public link.'; }
    finally { busy = false; }
  }
</script>

<BlockingDialog label="Public link" onClose={close} dismissible={!busy} class="z-[2147483100]" panelClass="max-w-lg" bodyClass="space-y-5">
  {#snippet header()}
    <div class="flex items-center justify-between gap-4"><h2 class="text-lg font-semibold text-strong">Public link</h2>
      <Button variant="ghost" size="icon" aria-label="Close public link" onclick={close} disabled={busy}><X size={18} /></Button>
    </div>
  {/snippet}
  <p class="text-sm leading-6 text-secondary">Anyone with the link can access this revision until it expires. Agent access is managed separately.</p>
  {#if allowModeChoice}
    <label class="block space-y-2 text-sm text-secondary">Link behavior
      <select aria-label="Link behavior" class="min-h-11 w-full rounded-xl border border-control-border bg-surface px-3 text-foreground focus:border-accent focus:outline-none" bind:value={mode} disabled={busy}>
        <option value="view">View in browser</option><option value="download">Download file</option>
      </select>
    </label>
  {/if}
  <label class="block space-y-2 text-sm text-secondary">Expires in
    <select aria-label="Public link validity" class="min-h-11 w-full rounded-xl border border-control-border bg-surface px-3 text-foreground focus:border-accent focus:outline-none" bind:value={expiration} disabled={busy}>
      <option value="1">1 day</option><option value="7">7 days (default)</option><option value="30">30 days</option><option value="90">90 days</option><option value="custom">Custom date and time</option>
    </select>
  </label>
  {#if expiration === 'custom'}
    <label class="block space-y-2 text-sm text-secondary">Expiration date and time
      <input type="datetime-local" class="min-h-11 w-full rounded-xl border border-control-border bg-surface px-3 text-foreground" bind:value={custom} disabled={busy} />
      <span class="block text-xs text-quiet">{timezone} · up to 90 days</span>
    </label>
  {/if}
  {#if url}
    <div class="space-y-2 border-t border-separator pt-4">
      <label class="block text-xs text-secondary" for="public-link-result">Public link · {copied ? 'Copied' : 'Ready to copy'}</label>
      <div class="flex items-center gap-2">
        <input id="public-link-result" aria-label="Public link URL" readonly value={url} onfocus={(event) => event.currentTarget.select()} class="min-h-11 min-w-0 flex-1 rounded-xl border border-control-border bg-surface px-3 text-xs text-foreground" />
        <Button variant="secondary" size="icon-mobile" aria-label="Copy public link" onclick={copy}><Link size={17} /></Button>
      </div>
    </div>
  {/if}
  {#if error}<p role="alert" class="text-sm text-danger">{error}</p>{/if}
  <p class="text-xs leading-5 text-quiet">Links stay valid until expiry and cannot be revoked individually. New revisions do not change existing links.</p>
  {#snippet footer()}
    <div class="flex justify-end gap-2">
      <Button variant="ghost" onclick={close} disabled={busy}>Done</Button>
      <Button onclick={create} disabled={busy}>{busy ? 'Creating…' : url ? 'Create another link' : 'Create public link'}</Button>
    </div>
  {/snippet}
</BlockingDialog>
