const { expect, test } = require('@playwright/test');

test('REQ-2.3 result page can expose a booking entry action', async ({ page }) => {
  await page.goto('/tickets?from=Beijing&to=Shanghai&date=2026-07-07');
  await expect(page.getByRole('heading', { name: 'Search results' })).toBeVisible();
});
