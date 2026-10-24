/** Work inspector is optional; keep its results/file/tool closure off chat startup. */
export function loadWorkView() {
  return import('./WorkView.svelte').then(module => module.default);
}
