/** Session details are optional; load their renderer only when mounted. */
export function loadSessionDetails() {
  return import('./SessionDetailsBody.svelte').then(module => module.default);
}
