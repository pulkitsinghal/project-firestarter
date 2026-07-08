import { expect, test } from '../fixtures/extension';

test('the extension loads and the side panel renders', async ({ extensionId, sidebarPage }) => {
  // MV3 extension ids are 32 characters in a–p.
  expect(extensionId).toMatch(/^[a-p]{32}$/);
  await expect(sidebarPage.getByTestId('greeting')).toContainText('hello from');
});
