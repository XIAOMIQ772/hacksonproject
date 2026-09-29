import { test, expect } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-7.1
// fixtures: typed_notes

test('REQ-7.1: search filters notes by type', async ({ page }) => {
  await h.openHome(page);
  await h.clickFirstAvailable(page, [[/search/i]]);
  await h.clickFirstAvailable(page, [[/^lists$/i, /checklists/i]]);
  await h.expectTextsVisible(page, [h.FIXTURES.evolution.checklistTitle]);
  await expect(page.getByText(h.FIXTURES.notes.regularTitle)).toHaveCount(0);

  await h.clickFirstAvailable(page, [[/search/i]]);
  await h.clickFirstAvailable(page, [[/^reminders$/i, /reminder/i]]);
  await h.expectTextsVisible(page, [h.FIXTURES.evolution.reminderTitle, h.FIXTURES.evolution.reminderValue]);
});
