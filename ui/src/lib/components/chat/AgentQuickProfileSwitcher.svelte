<script lang="ts">
  import SlidersHorizontal from 'lucide-svelte/icons/sliders-horizontal';
  import ChevronDown from 'lucide-svelte/icons/chevron-down';
  import { agentQuickProfileSelection, quickProfileColors, quickProfileOverrides } from '$lib/agent-quick-switch';
  import type { Agent, RuntimeSelection } from '$lib/types/api';

  let { agent, profileId, runtimeSelection, disabled = false, busy = false, hasDraft = false, iconOnly = false, conversationId, onSelect } = $props<{
    agent: Pick<Agent, 'agent_profiles' | 'default_agent_profile_id'>;
    profileId?: string | null;
    runtimeSelection?: RuntimeSelection | null;
    disabled?: boolean;
    busy?: boolean;
    hasDraft?: boolean;
    iconOnly?: boolean;
    conversationId?: string;
    onSelect: (profileId: string) => void;
  }>();
  const panelId = $props.id();
  let panel = $state<HTMLDivElement>();
  let trigger = $state<HTMLButtonElement>();
  let track = $state<HTMLDivElement>();
  let expanded = $state(false);
  $effect(() => {
    void conversationId;
    panel?.hidePopover?.();
  });
  $effect(() => {
    if (hasDraft && window.matchMedia('(max-width: 639px)').matches) panel?.hidePopover?.();
  });
  const selection = $derived(agentQuickProfileSelection(agent));
  const currentId = $derived(profileId || selection.defaultId);
  const selectedIndex = $derived(selection.options.findIndex((option) => option.id === currentId));
  const active = $derived(selection.options[selectedIndex]);
  const alternativeIndex = $derived(selection.options.findIndex((option) => !option.isDefault));
  const defaultIndex = $derived(selection.options.findIndex((option) => option.isDefault));
  const alternative = $derived(selection.options[alternativeIndex]);
  const label = $derived(active
    ? `${active.label}${active.isDefault && active.label !== 'Default' ? ' · Default' : ''}`
    : `${currentId} · Custom`);
  let previewIndex = $state<number | null>(null);
  let pendingIndex = $state<number | null>(null);
  let pointerId: number | null = null;
  let startX = 0;
  let moved = false;
  const visualIndex = $derived(previewIndex ?? (busy ? pendingIndex : null) ?? selectedIndex);
  const visualOption = $derived(selection.options[visualIndex]);
  const accent = $derived(quickProfileColors[visualOption?.color ?? 'neutral']);
  const overrides = $derived(runtimeSelection?.profile_id === currentId
    ? quickProfileOverrides(runtimeSelection) : []);
  const hasOverrides = $derived(overrides.length > 0);
  let previousBusy = false;
  let previousProfile: string | undefined;
  let previousConversation: string | undefined;
  $effect(() => {
    if (disabled || busy || !expanded) cancelDrag();
    if (previousBusy && !busy) pendingIndex = null;
    previousBusy = busy;
  });
  $effect(() => {
    if (previousProfile !== currentId || previousConversation !== conversationId) {
      cancelDrag();
      pendingIndex = null;
      previousProfile = currentId;
      previousConversation = conversationId;
    }
  });

  function pointIndex(event: PointerEvent): number {
    const rail = event.currentTarget as HTMLDivElement;
    const rect = rail.getBoundingClientRect();
    const width = rect.width / selection.options.length;
    return Math.max(0, Math.min(selection.options.length - 1,
      Math.round((event.clientX - rect.left - width / 2) / width)));
  }
  function beginDrag(event: PointerEvent): void {
    if (disabled || busy || event.button !== 0 || pointerId !== null) return;
    pointerId = event.pointerId;
    startX = event.clientX;
    moved = false;
    (event.currentTarget as HTMLDivElement).setPointerCapture(event.pointerId);
  }
  function drag(event: PointerEvent): void {
    if (event.pointerId !== pointerId || disabled || busy || !expanded) return;
    if (Math.abs(event.clientX - startX) > 4) moved = true;
    if (moved) previewIndex = pointIndex(event);
  }
  function finishDrag(event: PointerEvent): void {
    if (event.pointerId !== pointerId) return;
    pointerId = null;
    const next = previewIndex;
    previewIndex = null;
    if (expanded) select(moved && next !== null ? next : pointIndex(event));
  }
  function cancelDrag(): void {
    pointerId = null;
    previewIndex = null;
  }

  function select(index: number): void {
    const option = selection.options[index];
    if (!disabled && !busy && option && (option.id !== currentId || hasOverrides)) {
      pendingIndex = index;
      onSelect(option.id);
    }
  }

  // The current profile need not be a quick option (it may come from
  // /profile), so restore by ID rather than by quick-option index.
  function restoreCurrent(): void {
    if (disabled || busy || !hasOverrides) return;
    pendingIndex = selectedIndex >= 0 ? selectedIndex : null;
    onSelect(currentId);
  }

  function navigate(event: KeyboardEvent, index: number): void {
    const keys = ['ArrowLeft', 'ArrowDown', 'ArrowRight', 'ArrowUp', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    let next = index;
    if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = selection.options.length - 1;
    else next = Math.min(selection.options.length - 1, Math.max(0,
      next + (event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1)));
    select(next);
    const button = event.currentTarget as HTMLButtonElement;
    button.parentElement?.querySelectorAll<HTMLButtonElement>('button')[next]?.focus();
  }
</script>

{#if selection.options.length}
  <div class="profile-settings" style={`--profile-accent: ${accent}`} class:has-draft={hasDraft} class:icon-only={iconOnly} data-testid="agent-quick-profile-switcher">
    <button
      bind:this={trigger}
      type="button"
      class="settings-trigger"
      aria-label="Chat settings"
      aria-expanded={expanded}
      aria-controls={panelId}
      popovertarget={panelId}
      disabled={disabled}
      title={`Profile: ${label}`}
    >
      <SlidersHorizontal class="settings-icon" size={17} />
      <span class="trigger-accent" aria-hidden="true"></span>
      <span class="trigger-label">{busy ? 'Switching…' : active?.label ?? currentId}</span>
      {#if hasOverrides}<span class="override-badge" title={overrides.join('; ')} aria-label="Profile settings overridden">!</span>{/if}
      <ChevronDown class="trigger-chevron" size={13} />
    </button>
    <div
      bind:this={panel}
      id={panelId}
      popover="auto"
      class="settings-panel"
      role="dialog"
      aria-label="Chat settings"
      ontoggle={(event) => {
        expanded = event.newState === 'open';
        if (expanded && trigger && panel) {
          const rect = trigger.getBoundingClientRect();
          panel.style.right = `${Math.max(12, Math.min(window.innerWidth - rect.right, window.innerWidth - panel.offsetWidth - 12))}px`;
          panel.style.bottom = `${Math.max(12, window.innerHeight - rect.top + 10)}px`;
        }
      }}
    >
    <div class="quick-profile">
    <div class="profile-label" aria-live="polite">
      <span class="profile-heading">Agent profile</span>
       <span class="profile-value">{previewIndex !== null ? visualOption?.label : busy ? 'Switching…' : label}</span>
    </div>
    {#if hasOverrides}
      <p class="override-detail">Profile settings overridden: {overrides.join(' · ')}.</p>
      <button type="button" class="reset-overrides" disabled={disabled || busy}
        onclick={restoreCurrent}>Restore profile settings</button>
    {/if}
    {#if selection.toggle}
      <button
        type="button"
        role="switch"
        aria-label={`Use ${alternative.label} profile`}
        aria-checked={currentId === alternative.id}
        disabled={disabled}
        aria-disabled={disabled || busy}
        class="profile-toggle"
        onclick={() => select(currentId === alternative.id ? defaultIndex : alternativeIndex)}
        title={alternative.description}
      >
        <span class:enabled={currentId === alternative.id} class="toggle-thumb">{hasOverrides ? '!' : ''}</span>
      </button>
    {:else}
      <div class="track-controls">
      {#if selection.options.length > 5}
        <button type="button" class="scroll-control" aria-label="Scroll profiles left"
          onclick={() => track?.scrollBy({ left: -176, behavior: 'instant' })}>‹</button>
      {/if}
      <div
        bind:this={track}
        class="profile-track"
      >
        <div
          class="profile-rail"
          class:dragging={previewIndex !== null}
          style={`--stops: ${selection.options.length}; --position: ${Math.max(0, visualIndex)}`}
          role="radiogroup"
          tabindex="-1"
          aria-label="Agent profile"
          aria-disabled={disabled || busy}
          onpointerdown={beginDrag}
          onpointermove={drag}
          onpointerup={finishDrag}
          onpointercancel={cancelDrag}
          onlostpointercapture={cancelDrag}
        >
        {#if visualIndex >= 0}
          <span class="profile-fill" aria-hidden="true"></span>
          <span class="profile-thumb" class:overridden={hasOverrides && visualIndex === selectedIndex} aria-hidden="true"></span>
        {/if}
        {#each selection.options as option, index (option.id)}
          <button
            type="button"
            role="radio"
            tabindex={selectedIndex === index || (selectedIndex < 0 && index === 0) ? 0 : -1}
            aria-label={`${option.label}${option.isDefault ? ' (Default)' : ''}`}
            aria-checked={selectedIndex === index}
            disabled={disabled}
            aria-disabled={disabled || busy}
            title={`${option.label}${option.isDefault ? ' · Default' : ''}${option.description ? ` — ${option.description}` : ''}`}
            class="profile-stop"
            class:selected={visualIndex === index}
            onclick={(event) => { if (event.detail === 0) select(index); }}
            onkeydown={(event) => navigate(event, index)}
          >
            <span class="profile-dot"></span>
          </button>
        {/each}
        </div>
      </div>
      {#if selection.options.length > 5}
        <button type="button" class="scroll-control" aria-label="Scroll profiles right"
          onclick={() => track?.scrollBy({ left: 176, behavior: 'instant' })}>›</button>
      {/if}
      </div>
    {/if}
    </div>
    </div>
  </div>
{/if}

<style>
  .profile-settings { flex-shrink: 0; }
  .settings-trigger { display: flex; align-items: center; gap: 6px; height: 36px; max-width: 160px; padding: 0 10px; border-radius: 12px; color: rgb(var(--color-muted)); background: rgb(var(--color-inset) / .6); }
  .settings-trigger:hover, .settings-trigger[aria-expanded="true"] { background: rgb(var(--color-surface-hover)); color: rgb(var(--color-foreground)); }
  .trigger-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
  .trigger-accent { width: 5px; height: 5px; flex-shrink: 0; border-radius: 50%; background: var(--profile-accent); transition: background 200ms ease; }
  .settings-trigger:focus-visible { outline: 2px solid rgb(var(--color-accent)); outline-offset: 2px; }
  :global(.settings-icon) { display: none; }
  .icon-only .settings-trigger { width: 36px; padding: 0; justify-content: center; background: transparent; }
  .icon-only :global(.settings-icon) { display: block; }
  .icon-only .trigger-label, .icon-only .trigger-accent, .icon-only :global(.trigger-chevron) { display: none; }
  .settings-panel { position: fixed; inset: auto 24px 88px auto; margin: 0; width: 304px; max-width: calc(100vw - 24px); padding: 18px; border: 1px solid rgb(var(--color-control-border)); border-radius: 18px; color: rgb(var(--color-foreground)); background: rgb(var(--color-elevated)); box-shadow: 0 12px 40px rgb(0 0 0 / .35); }
  .quick-profile { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .profile-label { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-width: 0; }
  .profile-heading { font-size: 12px; color: rgb(var(--color-muted)); }
  .override-badge { color: rgb(var(--color-warning)); font-size: 12px; font-weight: 700; }
  .override-detail { margin: 0; font-size: 11px; color: rgb(var(--color-warning)); line-height: 1.5; }
  .reset-overrides { font-size: 11px; color: rgb(var(--color-secondary)); text-decoration: underline; text-align: left; }
  .profile-thumb.overridden::after { content: '!'; display: grid; place-items: center; color: rgb(var(--color-warning)); font-weight: 800; }
  .toggle-thumb { color: rgb(var(--color-warning)); font-weight: 800; text-align: center; line-height: 32px; }
  .profile-value { font-size: 13px; overflow-wrap: anywhere; text-align: right; }
  .profile-track { min-width: 0; max-width: 100%; overflow-x: auto; padding: 2px; border: 1px solid rgb(var(--color-control-border)); border-radius: 999px; background: rgb(var(--color-inset)); }
  .track-controls { display: flex; align-items: center; gap: 4px; min-width: 0; }
  .profile-track { flex: 1; }
  .scroll-control { flex-shrink: 0; width: 24px; height: 44px; font-size: 24px; color: rgb(var(--color-secondary)); border-radius: 8px; }
  .scroll-control:hover { background: rgb(var(--color-surface-hover)); }
  .profile-rail { position: relative; display: flex; min-width: calc(var(--stops) * 44px); isolation: isolate; touch-action: pan-y; }
  .profile-fill { position: absolute; inset: 0 auto 0 0; width: calc((var(--position) + 1) * 100% / var(--stops)); border-radius: 999px; background: color-mix(in srgb, var(--profile-accent) 65%, transparent); transition: width 220ms cubic-bezier(.2,.8,.2,1), background 220ms ease; pointer-events: none; z-index: -1; }
  .profile-thumb { position: absolute; top: 4px; bottom: 4px; left: 0; width: calc(100% / var(--stops)); transform: translateX(calc(var(--position) * 100%)); transition: transform 220ms cubic-bezier(.2,.8,.2,1); pointer-events: none; display: grid; place-items: center; }
  .profile-thumb::after { content: ''; width: 32px; height: 32px; border-radius: 50%; background: rgb(var(--color-surface)); box-shadow: 0 2px 8px rgb(0 0 0 / .25); transition: scale 140ms ease; }
  .dragging .profile-thumb, .dragging .profile-fill { transition-duration: 70ms; }
  .dragging .profile-thumb::after { scale: 1.06; }
  .profile-stop { display: grid; place-items: center; width: 44px; height: 44px; flex-shrink: 0; border-radius: 999px; }
  .profile-dot { width: 6px; height: 6px; border-radius: 50%; background: rgb(var(--color-secondary)); opacity: .65; }
  .profile-stop { flex: 1 0 44px; }
  .selected .profile-dot { opacity: 0; }
  .profile-stop:not(.selected):hover:not(:disabled) { background: rgb(var(--color-surface-hover)); }
  .profile-toggle { width: 66px; height: 44px; flex-shrink: 0; padding: 5px; border: 1px solid rgb(var(--color-control-border)); border-radius: 999px; background: rgb(var(--color-inset)); }
  .profile-toggle { transition: background 220ms ease; }
  .profile-toggle[aria-checked="true"] { background: var(--profile-accent); }
  .toggle-thumb { display: block; width: 32px; height: 32px; border-radius: 50%; background: rgb(var(--color-surface)); transition: transform 220ms cubic-bezier(.2,.8,.2,1); }
  .toggle-thumb.enabled { transform: translateX(22px); }
  .profile-stop:focus-visible, .profile-toggle:focus-visible { outline: 2px solid rgb(var(--color-accent)); outline-offset: 2px; }
  button:disabled, button[aria-disabled="true"] { cursor: not-allowed; opacity: 0.45; }
  @container chat-composer (max-width: 639px) {
    .settings-trigger { width: 36px; padding: 0; justify-content: center; background: transparent; }
    :global(.settings-icon) { display: block; }
    .trigger-label, .trigger-accent, :global(.trigger-chevron) { display: none; }
  }
  @media (max-width: 639px) {
    .profile-settings.has-draft { display: none; }
    .settings-trigger { width: 36px; padding: 0; justify-content: center; background: transparent; }
    :global(.settings-icon) { display: block; }
    .trigger-label, .trigger-accent, :global(.trigger-chevron) { display: none; }
    .settings-panel { right: 12px; bottom: 84px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .profile-thumb, .profile-fill, .profile-thumb::after, .profile-toggle, .toggle-thumb, .trigger-accent { transition: none; }
  }
</style>
