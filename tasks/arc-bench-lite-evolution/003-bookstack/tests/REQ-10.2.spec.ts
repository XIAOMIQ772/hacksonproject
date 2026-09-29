import { expect, test } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-10.2
// fixtures: sortable_book

test('REQ-10.2: sort pages and chapters inside a book', async ({ page }) => {
  await h.openBookDetailsFromList(page, h.FIXTURES.sorting.bookName);
  await h.expectTextsVisible(page, [h.FIXTURES.sorting.bookName, h.FIXTURES.sorting.pageName, h.FIXTURES.sorting.chapterName]);
  await h.clickNamed(page, /sort|reorder/i);
  await h.clickNamed(page, /alphabetical|name/i);
  await h.clickNamed(page, /^save|save sort|apply/i);
  await h.expectTextsVisible(page, [h.FIXTURES.sorting.bookName, h.FIXTURES.sorting.pageName, h.FIXTURES.sorting.chapterName]);
  const sortedEntries = await page.getByText(
    new RegExp(`${h.FIXTURES.sorting.pageName}|${h.FIXTURES.sorting.chapterName}`),
    { exact: true },
  ).allTextContents();
  expect(sortedEntries.indexOf(h.FIXTURES.sorting.pageName)).toBeLessThan(
    sortedEntries.indexOf(h.FIXTURES.sorting.chapterName),
  );
});
