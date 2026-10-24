import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'canonical-deliverable-pwa.spec.ts',
  grep: /selection copy preserves/,
  use: { baseURL: 'http://localhost:8080' },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'webkit-ipad', use: { ...devices['iPad Pro 11'] } },
  ],
});
