import { test, expect, type Page } from '@playwright/test';

// Every visible label must resolve to exactly one control (getByLabel strictness).
async function assertLabelsUnique(page: Page) {
  const texts = await page.locator('label').allInnerTexts();
  for (const text of [...new Set(texts.map((t) => t.trim()).filter(Boolean))]) {
    await expect(page.getByLabel(text, { exact: true }), `label "${text}"`).toHaveCount(1);
  }
}

test('dialog labels resolve to a single control', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'New blank workbook' }).click();
  await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('gridcell', { name: 'A1', exact: true }).click();
  await page.getByRole('textbox', { name: 'Formula bar' }).fill('Region');
  await page.keyboard.press('Enter');
  for (const item of ['Sort range', 'Data validation', 'Create pivot table']) {
    await page.getByRole('gridcell', { name: 'A1', exact: true }).click();
    await page.getByRole('button', { name: 'Data' }).click();
    await page.getByRole('menuitem', { name: item }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await assertLabelsUnique(page);
    if (item === 'Create pivot table') {
      await page.getByRole('dialog').getByRole('button', { name: 'Create' }).click();
      await assertLabelsUnique(page);
      break;
    }
    await page.keyboard.press('Escape');
  }
});
