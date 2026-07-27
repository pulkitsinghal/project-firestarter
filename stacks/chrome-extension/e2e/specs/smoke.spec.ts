import { expect, test } from '../fixtures/extension';

test('the extension loads and the side panel renders', async ({ extensionId, sidebarPage }) => {
  // MV3 extension ids are 32 characters in a–p.
  expect(extensionId).toMatch(/^[a-p]{32}$/);
  await expect(sidebarPage.getByTestId('greeting')).toContainText('hello from');
});

test('the content script resolves exact safe labels and fails closed', async ({
  fixturePage,
  serviceWorker,
}) => {
  await fixturePage.bringToFront();

  const resolve = (target: string) =>
    serviceWorker.evaluate(async (requestedTarget) => {
      const [fixtureTab] = await chrome.tabs.query({
        active: true,
        currentWindow: true,
      });
      if (typeof fixtureTab?.id !== 'number') {
        throw new Error('Active synthetic navigation fixture tab was not found.');
      }
      return chrome.tabs.sendMessage(fixtureTab.id, {
        type: 'firestarter:navigation:resolve',
        target: requestedTarget,
      });
    }, target);

  await expect(resolve('Cardiology')).resolves.toEqual({
    status: 'matched',
  });
  await expect(resolve('Ambiguous')).resolves.toEqual({
    status: 'ambiguous',
    count: 2,
  });
  await expect(resolve('Administrator')).resolves.toEqual({
    status: 'not-found',
  });
  await expect(resolve('Unsafe protocol')).resolves.toEqual({
    status: 'not-found',
  });

  await fixturePage.evaluate(() => {
    const fragment = document.createDocumentFragment();
    for (let index = 0; index < 2_000; index += 1) {
      const link = document.createElement('a');
      link.hidden = true;
      link.href = `/navigation/decoy-${index}.html`;
      link.textContent = `Decoy ${index}`;
      fragment.append(link);
    }
    const beyondBound = document.createElement('a');
    beyondBound.href = '/navigation/beyond-bound.html';
    beyondBound.textContent = 'Beyond Bound';
    fragment.append(beyondBound);
    document.body.append(fragment);
  });
  await expect(resolve('Beyond Bound')).resolves.toEqual({
    status: 'not-found',
  });

  await expect(fixturePage).toHaveURL(
    'http://127.0.0.1:4175/navigation/index.html',
  );
});
