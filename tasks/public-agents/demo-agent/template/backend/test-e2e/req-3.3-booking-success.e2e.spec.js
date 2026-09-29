const { expect, test } = require('@playwright/test');

test('REQ-3.3 booking success route is reachable', async ({ page }) => {
  await page.goto('/booking/success/1');
  await expect(page.getByRole('heading', { name: 'Booking success' })).toBeVisible();
});
