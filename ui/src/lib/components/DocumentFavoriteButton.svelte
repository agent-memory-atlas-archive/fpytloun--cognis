<script lang="ts">
  import Star from 'lucide-svelte/icons/star';
  import { auth } from '$lib/stores/auth';
  import { favoriteItems, favoriteKey, loadFavorite, saveFavorite } from '$lib/document-favorites';
  import type { LibraryItem, LibraryKind } from '$lib/library';
  let { kind, id, initial, showLabel = false }: { kind: LibraryKind; id: string; initial?: LibraryItem; showLabel?: boolean } = $props();
  let busy = $state(false);
  let error = $state('');
  const item = $derived($favoriteItems[favoriteKey(kind, id)]);
  $effect(() => {
    if (!$auth.user?.email) return;
    const currentKind = kind, currentId = id, seed = initial;
    let cancelled = false;
    error = '';
    void loadFavorite(currentKind, currentId, seed).catch(() => { if (!cancelled) error = 'Could not load favorite state. Click to retry.'; });
    return () => { cancelled = true; };
  });
  async function toggle() {
    busy = true; error = '';
    try {
      if (!item) await loadFavorite(kind, id, initial);
      else await saveFavorite(kind, id, !item.is_favorite);
    } catch { error = 'Could not update favorite. Please retry.'; }
    finally { busy = false; }
  }
</script>
{#if $auth.user?.email}
  <button type="button" class="document-favorite-action" class:favorite={item?.is_favorite}
    aria-label={item?.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
    aria-pressed={item?.is_favorite ?? false} disabled={busy || (!item && !error)}
    title={error || (item?.is_favorite ? 'Remove from favorites' : 'Add to favorites')} onclick={toggle}>
    <Star size={14} fill={item?.is_favorite ? 'currentColor' : 'none'} />
    {#if showLabel}<span>{item?.is_favorite ? 'Remove from favorites' : 'Add to favorites'}</span>{/if}
  </button>
  {#if error}<span role="status" class="sr-only">{error}</span>{/if}
{/if}
<style>
  .document-favorite-action {
    display: inline-flex; align-items: center; justify-content: center; flex: none;
    width: 2rem; height: 2rem; padding: 0; border: 0; border-radius: .5rem;
    background: transparent; color: var(--rich-text-secondary, rgb(var(--color-secondary)));
    cursor: pointer; transition: color 120ms, background 120ms;
  }
  .document-favorite-action:hover:not(:disabled) {
    background: var(--rich-control-active, rgb(var(--color-surface-hover)));
    color: var(--rich-text, rgb(var(--color-foreground)));
  }
  .document-favorite-action.favorite { color: rgb(var(--color-orange-tone)); }
  .document-favorite-action:focus-visible {
    outline: 2px solid var(--rich-accent, rgb(var(--color-accent))); outline-offset: 2px;
  }
  .document-favorite-action:disabled { opacity: .45; cursor: default; }
  @media (pointer: coarse) {
    .document-favorite-action { width: 2.75rem; height: 2.75rem; }
  }
  @media (prefers-reduced-motion: reduce) {
    .document-favorite-action { transition: none; }
  }
</style>
