<script lang="ts">
  import { projectIcon, projectIconForeground, safeProjectColor } from '$lib/projects/icons';
  let { name, avatarUrl = null, icon = null, color = null, class: className = 'h-12 w-12' } = $props<{
    name: string; avatarUrl?: string | null; icon?: unknown; color?: string | null; class?: string;
  }>();
  const Icon = $derived(projectIcon(icon) ?? projectIcon('briefcase')!);
  const background = $derived(safeProjectColor(color));
  let failedAvatar = $state<string | null>(null);
</script>

{#if !avatarUrl || failedAvatar === avatarUrl}
  <span class={`relative inline-flex shrink-0 items-center justify-center rounded-[22%] ${className}`}
    style:background-color={background} style:color={projectIconForeground(background)}
    role="img" aria-label={name} data-testid="project-library-icon">
    <Icon class="h-[70%] w-[70%]" strokeWidth={1.8} />
  </span>
{:else}
  <img src={avatarUrl} alt={name} class={`shrink-0 rounded-[22%] object-cover ${className}`}
    onerror={() => { failedAvatar = avatarUrl; }} />
{/if}
