// A pure-logic module — no chrome.* / DOM. This is the unit-test layer that
// Vitest covers; keep testable logic here (out of the chrome.* modules) and the
// browser/cross-world behaviour in the Playwright e2e suite.
export function greeting(who = '{{ project_name }}'): string {
  return `hello from ${who}`;
}
