import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    // The PWA store owns module-worker registration and update handling.
    serviceWorker: { register: false },
    adapter: adapter({
      pages: 'build',
      assets: 'build',
      fallback: 'index.html'
    }),
    prerender: {
      handleUnseenRoutes: 'ignore'
    }
  }
};

export default config;
