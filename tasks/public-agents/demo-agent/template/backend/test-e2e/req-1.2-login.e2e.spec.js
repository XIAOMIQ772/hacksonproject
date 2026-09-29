const { expect, test } = require('@playwright/test');

test('REQ-1.2 login page is reachable from the public shell', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Sign in to your account' })).toBeVisible();
});
