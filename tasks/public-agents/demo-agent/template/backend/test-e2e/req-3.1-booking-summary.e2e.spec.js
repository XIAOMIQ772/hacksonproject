const { expect, test } = require('@playwright/test');

test('REQ-3.1 booking page route is reachable with train context', async ({ page }) => {
  await page.goto('/booking?trainId=1&date=2026-07-07');
  await expect(page.getByRole('heading', { name: 'Booking page' })).toBeVisible();
});
