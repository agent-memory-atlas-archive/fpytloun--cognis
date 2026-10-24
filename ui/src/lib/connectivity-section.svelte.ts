// Section-level side of the notice precedence in $lib/connectivity.
//
// A section (dashboard card, panel, list) shows its own load/refresh error
// only when the connection is healthy. While the connection is degraded the
// global ConnectionBanner owns the notice; when it is restored the section
// retries its failed load, keeping the error hidden until that retry settles.
//
// Usage (component init):
//   const net = useSectionConnectivity({ hasError: () => Boolean(error), retry: load });
//   {#if error && !net.hideErrors} … {/if}

import { fromStore } from 'svelte/store';
import { connectivity, onConnectivityRestored } from '$lib/connectivity';

const connectivityState = fromStore(connectivity);

export interface SectionConnectivityOptions {
  /** Whether the section currently shows a load/refresh error. */
  hasError: () => boolean;
  /** Reload the section's data (called after the connection is restored). */
  retry: () => unknown;
}

export interface SectionConnectivity {
  /** True while the section must not show its own load/refresh error. */
  readonly hideErrors: boolean;
  /** True while the connection is degraded (global banner owns notices). */
  readonly degraded: boolean;
}

export function useSectionConnectivity(options: SectionConnectivityOptions): SectionConnectivity {
  let retrying = $state(false);

  $effect(() => onConnectivityRestored(() => {
    if (!options.hasError()) return;
    retrying = true;
    void Promise.resolve()
      .then(() => options.retry())
      .catch(() => undefined)
      .finally(() => { retrying = false; });
  }));

  return {
    get hideErrors() {
      return connectivityState.current.degraded || retrying;
    },
    get degraded() {
      return connectivityState.current.degraded;
    },
  };
}
