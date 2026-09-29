import { test } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-8.2
// fixtures: reminder_candidate

test('REQ-8.2: set a Tomorrow reminder and show it in Reminders', async ({ page }) => {
  await h.openHome(page);
  const title = h.FIXTURES.evolution.reminderTitle;
  const card = await h.noteCard(page, title);
  await h.hoverNamed(card, title);
  await h.clickFirstAvailable(card, [[/remind me/i, /reminder/i, /bell/i]]);
  await h.clickFirstAvailable(page, [[new RegExp(`^${h.FIXTURES.evolution.reminderValue}$`, 'i')]]);
  await h.expectNoteVisible(page, title);
  await h.expectTextsVisible(page, [h.FIXTURES.evolution.reminderValue]);

  await h.openSidebar(page);
  await h.clickFirstAvailable(page, [[/^reminders$/i]]);
  await h.expectNoteVisible(page, title);
});
