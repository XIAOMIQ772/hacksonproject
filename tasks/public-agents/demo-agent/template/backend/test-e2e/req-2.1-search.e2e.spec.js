const { expect, test } = require('@playwright/test');

test('REQ-2.1 homepage exposes the search panel', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Search' })).toBeVisible();
});
