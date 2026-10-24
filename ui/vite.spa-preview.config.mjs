import { defineConfig } from 'vite';

// Exercise the compiled static export with SPA routing, not SvelteKit SSR.
export default defineConfig({ appType: 'spa', build: { outDir: 'build' } });
