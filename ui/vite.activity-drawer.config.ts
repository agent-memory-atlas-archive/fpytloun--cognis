import { fileURLToPath, URL } from 'node:url';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';
export default defineConfig({
  root: fileURLToPath(new URL('./e2e/fixtures/activity-drawer', import.meta.url)),
  plugins: [svelte({ configFile: false })],
  resolve: {
    alias: [
      { find: '$lib/api/client', replacement: fileURLToPath(new URL('./e2e/fixtures/activity-drawer/api.ts', import.meta.url)) },
      { find: '$lib', replacement: fileURLToPath(new URL('./src/lib', import.meta.url)) },
    ],
  },
  server: { fs: { allow: [fileURLToPath(new URL('.', import.meta.url))] } },
});
