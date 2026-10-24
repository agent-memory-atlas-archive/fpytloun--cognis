import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    ...(process.env.COGNIS_APPLE_BUNDLE === '1' ? {
      paths: { assets: 'cognisbundle://app' },
      // WK HTTPS documents cannot fetch custom-scheme executable modules.
      // Use SvelteKit's canonical self-contained export, not a second UI build.
      output: { bundleStrategy: 'inline' },
      alias: { '$env/dynamic/public': './src/lib/native/build-env.ts' },
      // The native host serves the one SPA fallback at every validated route.
      // Do not duplicate the complete inline graph into every prerendered page.
      // This host has no service-worker entry point; all code ships in the bundle.
      files: { serviceWorker: 'src/lib/native/service-worker' }
    } : {}),
    // The PWA store owns module-worker registration and update handling.
    serviceWorker: { register: false },
    adapter: adapter({
      pages: process.env.COGNIS_APPLE_BUNDLE === '1' ? 'build-apple' : 'build',
      assets: process.env.COGNIS_APPLE_BUNDLE === '1' ? 'build-apple' : 'build',
      fallback: 'index.html'
    }),
    prerender: {
      ...(process.env.COGNIS_APPLE_BUNDLE === '1' ? { entries: [] } : {}),
      handleUnseenRoutes: 'ignore'
    }
  }
};

export default config;
