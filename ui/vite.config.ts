import { fileURLToPath } from 'node:url';

import { sveltekit } from '@sveltejs/kit/vite';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vitest/config';
import { viteStaticCopy } from 'vite-plugin-static-copy';

export default defineConfig({
  plugins: [sveltekit(), svelteTesting(), viteStaticCopy({
    targets: [
      { src: 'node_modules/pdfjs-dist/cmaps/*', dest: 'pdfjs/cmaps', rename: { stripBase: true } },
      { src: 'node_modules/pdfjs-dist/standard_fonts/*', dest: 'pdfjs/standard_fonts', rename: { stripBase: true } },
      { src: 'node_modules/pdfjs-dist/wasm/*', dest: 'pdfjs/wasm', rename: { stripBase: true } },
    ],
  })],
  server: {
    fs: {
      allow: [fileURLToPath(new URL('../docs', import.meta.url))]
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: true
      },
      '/.well-known': {
        target: 'http://localhost:8080',
        changeOrigin: true
      }
    }
  },
  build: {
    ...(process.env.COGNIS_APPLE_BUNDLE === '1' ? { assetsInlineLimit: Infinity } : {}),
    // Warn when a chunk exceeds 250KB (uncompressed). Initial-load chunks
    // should stay well below this to keep mobile time-to-interactive low.
    chunkSizeWarningLimit: 250
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{ts,js}'],
    setupFiles: ['./src/test/setup.ts']
  }
});
