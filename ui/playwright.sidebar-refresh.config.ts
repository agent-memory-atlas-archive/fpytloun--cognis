import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'sidebar-refresh-recovery.spec.ts',
  workers: 1,
  retries: 0,
  // Recovery uses the controlled clock; allow the whole scenario to complete.
  timeout: 120_000,
  expect: { timeout: 5_000 },
  use: { baseURL: 'http://127.0.0.1:4196', trace: 'retain-on-failure' },
  webServer: {
    command: 'npx vite preview --config vite.spa-preview.config.mjs --host 127.0.0.1 --port 4196 --strictPort',
    url: 'http://127.0.0.1:4196',
    reuseExistingServer: false,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
