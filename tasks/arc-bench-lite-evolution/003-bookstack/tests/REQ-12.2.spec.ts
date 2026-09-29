import { test } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-12.2
// fixtures: revisioned_page

test('REQ-12.2: open page revision history', async ({ page }) => {
  await h.openPageReading(page, h.FIXTURES.revisions.bookName, h.FIXTURES.revisions.pageName);
  await h.clickNamed(page, /revisions|revision history/i);
  await h.expectTextsVisible(page, [/revisions|revision history/i, h.FIXTURES.revisions.pageName, h.FIXTURES.revisions.revisionLabel]);
  await h.clickNamed(page, /back|return|view page/i);
  await h.expectTextsVisible(page, [h.FIXTURES.revisions.pageName]);
});
