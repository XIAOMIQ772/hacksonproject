import { test, expect } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-7.2
// fixtures: checklist_note, settings_state

test('REQ-7.2: checked checklist items can stay in place', async ({ page }) => {
  await h.openHome(page);
  await h.openSettingsMenu(page);
  await h.clickFirstAvailable(page, [[/^settings$/i]]);
  const moveChecked = page.getByRole('checkbox', { name: /move checked items to bottom/i });
  if (await moveChecked.isChecked().catch(() => false)) {
    await moveChecked.uncheck();
  }
  await h.clickFirstAvailable(page, [[/^save$/i, /^done$/i]]);

  await h.expectNoteVisible(page, h.FIXTURES.evolution.checklistTitle);
  const firstItem = page.getByRole('checkbox', { name: h.FIXTURES.evolution.checklistFirstItem }).first();
  const secondText = page.getByText(h.FIXTURES.evolution.checklistSecondItem, { exact: true }).first();
  await firstItem.check();
  await expect(firstItem).toBeChecked();
  await expect(firstItem).toBeVisible();
  await expect(secondText).toBeVisible();
  await expect.poll(async () => {
    const firstBox = await firstItem.boundingBox();
    const secondBox = await secondText.boundingBox();
    return firstBox !== null && secondBox !== null && firstBox.y <= secondBox.y;
  }).toBe(true);
});
