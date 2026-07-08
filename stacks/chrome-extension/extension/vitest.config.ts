import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Unit layer: pure-logic modules only (no chrome.* / DOM at import time).
    // Cross-world / real-browser behaviour is covered by the Playwright e2e
    // suite (host-only). Keep unit-testable logic out of the chrome.* modules.
    include: ['src/**/*.test.ts'],
    environment: 'node',
  },
});
