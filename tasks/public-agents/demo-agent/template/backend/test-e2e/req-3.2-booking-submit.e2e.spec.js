const { expect, test } = require('@playwright/test');

test('REQ-3.2 booking page exposes the passenger form and submit action', async ({ page }) => {
  await page.goto('/booking?trainId=1&date=2026-07-07');
  await expect(page.getByRole('button', { name: 'Submit booking' })).toBeVisible();
});
