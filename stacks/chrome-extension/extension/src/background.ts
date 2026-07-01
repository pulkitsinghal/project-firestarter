// {{ project_name }} — background service worker (MV3).
// Kept minimal: wire the toolbar action to open the side panel. Grow this into
// your real background logic (message routing, context menus, alarms).

chrome.runtime.onInstalled.addListener(() => {
  // Clicking the toolbar icon opens the side panel for the current window.
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((err) => {
    console.error('{{ project_slug }}: setPanelBehavior failed', err);
  });
  console.log('{{ project_name }} installed');
});
