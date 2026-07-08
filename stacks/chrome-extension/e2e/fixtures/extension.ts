import path from 'node:path';

import { chromium, test as base, type BrowserContext, type Page } from '@playwright/test';

// Path to the built extension (run `make build` first). Override with EXTENSION_PATH.
const EXTENSION_PATH =
  process.env.EXTENSION_PATH || path.resolve(process.cwd(), '..', 'extension', 'dist');
// A throwaway Chrome profile for the run (gitignored). Override with E2E_USER_DATA_DIR.
const USER_DATA_DIR =
  process.env.E2E_USER_DATA_DIR || path.resolve(process.cwd(), '.auth', 'chrome-profile');

// An MV3 extension's id is the hostname of its background service worker's URL.
async function resolveExtensionId(context: BrowserContext): Promise<string> {
  let [sw] = context.serviceWorkers();
  if (!sw) {
    sw = await context.waitForEvent('serviceworker', { timeout: 30_000 });
  }
  return new URL(sw.url()).hostname;
}

type Fixtures = {
  context: BrowserContext;
  extensionId: string;
  sidebarPage: Page;
};

export const test = base.extend<Fixtures>({
  context: async ({}, use) => {
    // Extensions only load into a persistent context (not the default one).
    const context = await chromium.launchPersistentContext(USER_DATA_DIR, {
      channel: 'chromium',
      headless: false,
      args: [
        `--disable-extensions-except=${EXTENSION_PATH}`,
        `--load-extension=${EXTENSION_PATH}`,
        // Container/CI-safe: no sandbox (unavailable in an unprivileged CI
        // container) and don't rely on /dev/shm (often tiny in CI → Chromium
        // crashes). Harmless on a real desktop; needed under Xvfb in CI.
        '--no-sandbox',
        '--disable-dev-shm-usage',
      ],
    });
    await use(context);
    await context.close();
  },

  extensionId: async ({ context }, use) => {
    await use(await resolveExtensionId(context));
  },

  // Open the side panel page directly (chrome-extension://<id>/sidebar.html).
  sidebarPage: async ({ context, extensionId }, use) => {
    const page = await context.newPage();
    await page.goto(`chrome-extension://${extensionId}/sidebar.html`);
    await use(page);
    await page.close();
  },
});

export { expect } from '@playwright/test';
