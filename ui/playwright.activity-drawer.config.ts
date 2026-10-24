import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  testMatch: 'activity-drawer.spec.ts',
  use: { baseURL: 'http://127.0.0.1:18175', viewport: { width: 390, height: 844 }, hasTouch: true },
  webServer: {
    command: 'npx vite --config vite.activity-drawer.config.ts --host 127.0.0.1 --port 18175 --strictPort',
    url: 'http://127.0.0.1:18175',
    reuseExistingServer: false,
  },
});
