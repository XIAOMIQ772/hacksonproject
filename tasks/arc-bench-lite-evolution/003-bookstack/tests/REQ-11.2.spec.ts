import { test, expect } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-11.2
// fixtures: exportable_book

test('REQ-11.2: export a book as Markdown', async ({ page }) => {
  await h.openBookDetailsFromList(page, h.FIXTURES.export.bookName);
  const downloadPromise = page.waitForEvent('download');
  await h.clickNamed(page, /export markdown|download markdown/i);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.md$/i);
  await h.expectTextsVisible(page, [h.FIXTURES.export.bookName]);
});
