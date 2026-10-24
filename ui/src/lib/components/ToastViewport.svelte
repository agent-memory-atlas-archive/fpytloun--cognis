<script lang="ts">
  import AlertCircle from 'lucide-svelte/icons/alert-circle';
import CheckCircle2 from 'lucide-svelte/icons/check-circle-2';
import Info from 'lucide-svelte/icons/info';
import TriangleAlert from 'lucide-svelte/icons/triangle-alert';

  import { removeToast, toastStore, type ToastItem } from '$lib/stores/toasts';

  const variants = {
    success: {
      className: 'border-success-border bg-success-subtle text-success',
      icon: CheckCircle2
    },
    error: {
      className: 'border-danger-border bg-danger-subtle text-danger',
      icon: AlertCircle
    },
    warning: {
      className: 'border-accent/40 bg-accent-subtle text-accent',
      icon: TriangleAlert
    },
    info: {
      className: 'border-accent/40 bg-accent-subtle text-accent',
      icon: Info
    }
  } as const;

  function variantConfig(toast: ToastItem) {
    return variants[toast.variant];
  }
</script>

{#if $toastStore.length > 0}
  <div
    aria-live="polite"
    class="app-floating-top-overlay pointer-events-none z-[80] flex w-auto max-w-[22rem] flex-col gap-3 sm:left-auto sm:w-[22rem]"
  >
    {#each $toastStore as toast (toast.id)}
      {@const config = variantConfig(toast)}
      <button
        class={`pointer-events-auto flex w-full items-start gap-3 rounded-2xl border px-4 py-3 text-left shadow-card backdrop-blur transition hover:translate-y-[-1px] ${config.className}`}
        data-toast-variant={toast.variant}
        onclick={() => removeToast(toast.id)}
        type="button"
      >
        <svelte:component this={config.icon} class="mt-0.5 h-5 w-5 shrink-0" />
        <div class="min-w-0 flex-1">
          {#if toast.title}
            <p class="font-medium">{toast.title}</p>
          {/if}
          <p class={`text-sm leading-6 ${toast.title ? 'mt-1 opacity-90' : ''}`}>{toast.message}</p>
        </div>
      </button>
    {/each}
  </div>
{/if}
