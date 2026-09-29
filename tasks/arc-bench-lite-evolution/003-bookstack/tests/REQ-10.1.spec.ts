import { test } from '@playwright/test';
import * as h from './helpers';

// requirement: REQ-10.1
// fixtures: authenticated_user

test('REQ-10.1: invalid login shows feedback and stays on login page', async ({ page }) => {
  await h.openLoginPage(page);
  await h.fillField(page, 'Email address', h.FIXTURES.auth.invalidEmail);
  await h.fillField(page, 'Password', h.FIXTURES.auth.invalidPassword);
  await h.clickNamed(page, /^Login$/i);
  await h.expectTextsVisible(page, [/invalid email or password/i, /^login$/i]);
});
