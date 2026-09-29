import { test } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-11.1
// fixtures: commentable_page

test('REQ-11.1: add a comment to a readable page', async ({ page }) => {
  await h.openPageReading(page, h.FIXTURES.comments.bookName, h.FIXTURES.comments.pageName);
  await h.expectTextsVisible(page, [h.FIXTURES.comments.pageName]);
  await h.fillField(page, 'Comment', h.FIXTURES.comments.text);
  await h.clickNamed(page, /submit comment|add comment|comment/i);
  await h.expectTextsVisible(page, [h.FIXTURES.comments.text, h.FIXTURES.comments.pageName]);
});
