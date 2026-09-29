const { expect, test } = require('@playwright/test');

test('REQ-1.1 registration page is reachable from the public shell', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Create account' }).click();
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible();
});
