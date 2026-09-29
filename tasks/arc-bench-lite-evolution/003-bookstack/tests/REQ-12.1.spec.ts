import { expect, test } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-12.1
// fixtures: searchable_book

test('REQ-12.1: search within the current book', async ({ page }) => {
  await h.openBookDetailsFromList(page, h.FIXTURES.search.bookName);
  await h.fillField(page, 'Search', h.FIXTURES.search.keyword);
  await page.keyboard.press('Enter');
  await h.expectTextsVisible(page, [h.FIXTURES.search.matchingPageName, h.FIXTURES.search.bookName]);
  await expect(page.getByText(h.FIXTURES.search.outsidePageName, { exact: true })).toHaveCount(0);
});

