import { defineConfig } from 'vite';

// Serve the canonical static export with its SPA fallback, not SvelteKit SSR.
export default defineConfig({
  appType: 'spa',
  build: { outDir: 'build' },
});
