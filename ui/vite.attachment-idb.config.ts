import { fileURLToPath, URL } from 'node:url';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

// Isolated synthetic app. Never exported by the production SvelteKit build.
export default defineConfig({
  root: fileURLToPath(new URL('./e2e/fixtures/attachment-idb', import.meta.url)),
  plugins: [svelte({ configFile: false })],
  resolve: { alias: [
    { find: '$app/environment', replacement: fileURLToPath(new URL('./e2e/fixtures/attachment-idb/environment.ts', import.meta.url)) },
    { find: '$env/dynamic/public', replacement: fileURLToPath(new URL('./e2e/fixtures/attachment-idb/environment.ts', import.meta.url)) },
    { find: '$lib', replacement: fileURLToPath(new URL('./src/lib', import.meta.url)) },
  ] },
  server: { host: '127.0.0.1', fs: { allow: [fileURLToPath(new URL('.', import.meta.url))] } },
});
