import { test, expect } from '@playwright/test';

test('REQ-1: Display the default home page', async ({ page }) => {
  await page.goto('/');
});
