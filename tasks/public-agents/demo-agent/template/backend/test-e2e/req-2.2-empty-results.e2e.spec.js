const { expect, test } = require('@playwright/test');

test('REQ-2.2 result page can render an empty state', async ({ page }) => {
  await page.goto('/tickets?from=Beijing&to=Kunming&date=2026-07-07');
  await expect(page.getByRole('heading', { name: 'Search results' })).toBeVisible();
});
