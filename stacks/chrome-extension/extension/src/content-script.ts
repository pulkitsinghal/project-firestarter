import {
  parseNavigationResolveMessage,
  resolveVisiblePageNavigation,
} from './browser-assistant';

// {{ project_name }} — content script. Runs only on the pages matched in
// manifest.json. It exposes a narrow, read-only resolution boundary: callers
// receive status metadata, never page text, selectors, or destination URLs.
console.debug('{{ project_slug }} content script active');

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const request = parseNavigationResolveMessage(message);
  if (!request) return;

  const resolution = resolveVisiblePageNavigation(request.target);
  switch (resolution.status) {
    case 'matched':
    case 'already-current':
      sendResponse({ status: resolution.status });
      break;
    case 'ambiguous':
      sendResponse({
        status: resolution.status,
        count: resolution.count,
      });
      break;
    case 'not-found':
      sendResponse({ status: resolution.status });
      break;
  }
});
