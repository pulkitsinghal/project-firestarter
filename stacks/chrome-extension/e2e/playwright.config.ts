import { defineConfig } from '@playwright/test';

// MV3 e2e: an extension must be loaded into a real (headed) Chromium via a
// persistent context — so this runs on the host, never in a headless container.
export default defineConfig({
  testDir: './specs',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
