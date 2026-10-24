import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'attachment-idb.spec.ts',
  workers: 1, retries: 0, reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:4197' },
  webServer: {
    command: 'npx vite build --config vite.attachment-idb.config.ts && npx vite preview --config vite.attachment-idb.config.ts --host 127.0.0.1 --port 4197 --strictPort',
    url: 'http://127.0.0.1:4197', reuseExistingServer: false, timeout: 180_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } }],
});
