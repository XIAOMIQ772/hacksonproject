import { test, expect } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-8.1
// fixtures: public_homepage

test('REQ-8.1: create and complete a checklist note', async ({ page }) => {
  await h.openHome(page);
  await h.openComposer(page);
  await h.clickFirstAvailable(page, [[/checklist/i, /checkbox/i, /new list/i]]);
  await h.fillField(page, [/title/i], h.FIXTURES.evolution.checklistTitle);
  await h.fillField(page, [/list item|item/i], h.FIXTURES.evolution.checklistFirstItem);
  await page.keyboard.press('Enter');
  await h.fillField(page, [/list item|item/i], h.FIXTURES.evolution.checklistSecondItem);
  await h.clickFirstAvailable(page, [[/^close$/i, /^done$/i, /^save$/i]]);

  const card = await h.noteCard(page, h.FIXTURES.evolution.checklistTitle);
  await expect(card.getByText(h.FIXTURES.evolution.checklistFirstItem, { exact: true })).toBeVisible();
  await expect(card.getByText(h.FIXTURES.evolution.checklistSecondItem, { exact: true })).toBeVisible();
  const passport = card.getByRole('checkbox', { name: h.FIXTURES.evolution.checklistFirstItem }).first();
  await passport.check();
  await expect(passport).toBeChecked();
});
