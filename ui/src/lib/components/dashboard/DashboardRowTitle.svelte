<script lang="ts">
  import ExternalLink from 'lucide-svelte/icons/external-link';
  let { title, linkLabel, linkTestId, onOpenLink } = $props<{
    title: string;
    linkLabel: string;
    linkTestId: string;
    onOpenLink: (event: MouseEvent) => void;
  }>();
</script>

<div class="flex min-w-0 items-start gap-1" data-testid="dashboard-row-title">
  <p class="min-w-0 line-clamp-2 text-sm font-medium leading-5 text-strong">{title}</p>
  <button type="button" aria-label={linkLabel} title={linkLabel} data-testid={linkTestId}
    class="flex h-5 w-5 shrink-0 items-center justify-center rounded text-quiet hover:bg-raised hover:text-strong"
    onclick={(event) => { event.stopPropagation(); onOpenLink(event); }}
    onkeydown={(event) => event.stopPropagation()}>
    <ExternalLink class="h-3.5 w-3.5" />
  </button>
</div>
