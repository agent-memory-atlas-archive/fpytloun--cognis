<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';

  import { cn } from '$lib/utils';
  import { findTarget, type FindOptions } from '$lib/find';

  /**
   * Input primitive. Mobile font-size is 16px to prevent iOS Safari from zooming
   * the viewport on focus; desktop scales back down to 14px at md+. Minimum
   * height is 44px mobile, 36px at md+.
   */

  let {
    type = 'text',
    value = $bindable(''),
    placeholder = '',
    class: className = '',
    disabled = false,
    name,
    element = $bindable<HTMLInputElement | null>(null),
    find = false,
    ...rest
  } = $props<{
    type?: string;
    value?: string | number;
    placeholder?: string;
    class?: string;
    disabled?: boolean;
    name?: string;
    element?: HTMLInputElement | null;
    find?: boolean | FindOptions;
  } & HTMLInputAttributes>();
</script>

<input
  bind:this={element}
  use:findTarget={find}
  class={cn(
    'w-full rounded-xl border border-control-border bg-inset px-3 text-base text-foreground placeholder:text-quiet focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent min-h-[44px] py-2.5 md:min-h-[36px] md:py-2 md:text-sm',
    className
  )}
  {type}
  bind:value
  {placeholder}
  {disabled}
  {name}
  {...rest}
/>
