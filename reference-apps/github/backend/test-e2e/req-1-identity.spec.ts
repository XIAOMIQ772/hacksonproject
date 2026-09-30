import { test, expect } from '@playwright/test';
import { PASSWORD, SEED, login, register, signOut, unique } from './helpers';

test.describe('REQ-1-1-1 Register', () => {
  test('S1 registers and signs in with the new account', async ({ page }) => {
    const { username, email } = await register(page, 'reg');
    await page.getByLabel('Username or email').fill(email);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('button', { name: 'Account menu' })).toBeVisible();
    await expect(page.getByText(username)).toBeVisible();
    await page.reload();
    await expect(page.getByText(username)).toBeVisible();
    await expect(page.getByText(PASSWORD)).toHaveCount(0);
  });

  test('S2 shows all field errors together and keeps input', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Sign in' }).click();
    await page.getByRole('link', { name: 'Create an account' }).click();
    const bad = `-${unique('bad')}`;
    await page.getByLabel('Username').fill(bad);
    await page.getByLabel('Email').fill('not-an-email');
    await page.getByLabel('Password', { exact: true }).fill('short');
    await page.getByLabel('Confirm password').fill('different');
    await expect(page.getByRole('checkbox', { name: 'Agree to the terms' })).not.toBeChecked();
    await page.getByRole('button', { name: 'Create account' }).click();
    for (const msg of ['Username format is invalid', 'Email format is invalid', 'Password requirements are not satisfied', 'Agree to terms is required']) {
      await expect(page.getByText(msg)).toBeVisible();
    }
    await expect(page.getByLabel('Username')).toHaveValue(bad);
    await expect(page.getByLabel('Email')).toHaveValue('not-an-email');
    await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
    await expect(page.getByRole('button', { name: 'Create account' })).toBeEnabled();
  });

  test('S3 duplicate username is rejected and values retained', async ({ page }) => {
    await page.goto('/signup');
    const email = `${unique('dup')}@example.test`;
    await page.getByLabel('Username').fill(SEED.alice.username);
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
    await page.getByLabel('Confirm password').fill(PASSWORD);
    await page.getByRole('checkbox', { name: 'Agree to the terms' }).check();
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page.getByText('Username already exists')).toBeVisible();
    await expect(page.getByLabel('Username')).toHaveValue(SEED.alice.username);
    await expect(page.getByLabel('Email')).toHaveValue(email);
  });
});

test.describe('REQ-1-1-2 Sign in', () => {
  test('S1 signs in by username and session survives reload', async ({ page }) => {
    await login(page, SEED.alice.username);
    await page.reload();
    await expect(page.getByRole('button', { name: 'Account menu' })).toContainText('alice-dev');
  });
  test('S2 signs in by email', async ({ page }) => {
    await login(page, SEED.alice.email);
    await expect(page.getByRole('button', { name: 'Account menu' })).toContainText('alice-dev');
  });
  test('S3 wrong password shows generic error', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Sign in' }).click();
    await page.getByLabel('Username or email').fill(SEED.alice.username);
    await page.getByLabel('Password').fill('Wrong-password-000!');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByText('Invalid credentials')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Account menu' })).toHaveCount(0);
  });
  test('S4 unknown account shows the same error and protected page needs sign in', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username or email').fill(`${unique('ghost')}@example.test`);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByText('Invalid credentials')).toBeVisible();
    await page.goto('/settings/security');
    await expect(page.getByText('Sign in required')).toBeVisible();
  });
});

async function startReset(page, email: string) {
  await page.goto('/');
  await page.getByRole('link', { name: 'Sign in' }).click();
  await page.getByRole('link', { name: 'Forgot password' }).click();
  await page.getByLabel('Email').fill(email);
  await page.getByRole('button', { name: 'Send reset link' }).click();
  await expect(page.getByText('123456', { exact: true })).toBeVisible();
}

test.describe('REQ-1-1-3 Password recovery', () => {
  test('S1 resets password with the fixed code', async ({ page }) => {
    const { email } = await register(page, 'reset');
    await startReset(page, email);
    await page.getByLabel('Verification code').fill('123456');
    await page.getByLabel('New password').fill('Replacement-password-456!');
    await page.getByLabel('Confirm password').fill('Replacement-password-456!');
    await page.getByRole('button', { name: 'Reset password' }).click();
    await expect(page.getByText('Password updated')).toBeVisible();
    await page.goto('/login');
    await page.getByLabel('Username or email').fill(email);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByText('Invalid credentials')).toBeVisible();
    await login(page, email, 'Replacement-password-456!');
  });
  test('S2 wrong code is rejected and old password still works', async ({ page }) => {
    const { email } = await register(page, 'resetbad');
    await startReset(page, email);
    await page.getByLabel('Verification code').fill('000000');
    await page.getByLabel('New password').fill('Replacement-password-456!');
    await page.getByLabel('Confirm password').fill('Replacement-password-456!');
    await page.getByRole('button', { name: 'Reset password' }).click();
    await expect(page.getByText('Verification code is invalid')).toBeVisible();
    await login(page, email);
  });
  test('S3 unknown email gets the same step but no change', async ({ page }) => {
    await startReset(page, `${unique('nobody')}@example.test`);
    await expect(page.getByLabel('Verification code')).toBeVisible();
    await page.getByLabel('Verification code').fill('123456');
    await page.getByLabel('New password').fill('Replacement-password-456!');
    await page.getByLabel('Confirm password').fill('Replacement-password-456!');
    await page.getByRole('button', { name: 'Reset password' }).click();
    await expect(page.getByText('Password updated')).toHaveCount(0);
    await expect(page.getByRole('alert')).toBeVisible();
  });
});

test.describe('REQ-1-2 Sign out', () => {
  test('S1 confirm sign out ends the session', async ({ page }) => {
    await login(page, SEED.alice.username);
    await page.goto('/settings/security');
    await expect(page.getByRole('heading', { name: 'Password and authentication' })).toBeVisible();
    await signOut(page);
    await page.goBack();
    await page.reload();
    await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Password and authentication' })).toHaveCount(0);
  });
  test('S2 cancel keeps the session', async ({ page }) => {
    await login(page, SEED.alice.username);
    await page.getByRole('button', { name: 'Account menu' }).click();
    await page.getByRole('link', { name: 'Sign out' }).click();
    await expect(page.getByRole('dialog', { name: 'Sign out' })).toBeVisible();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await page.reload();
    await expect(page.getByRole('button', { name: 'Account menu' })).toBeVisible();
  });
});

async function openSecurity(page) {
  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.getByRole('link', { name: 'Settings' }).click();
  await page.getByRole('link', { name: 'Password and authentication' }).click();
}

test.describe('REQ-1-3 Change password', () => {
  test('S1 updates the password', async ({ page }) => {
    const { username } = await register(page, 'chg');
    await login(page, username);
    await openSecurity(page);
    await page.getByLabel('Current password').fill(PASSWORD);
    await page.getByLabel('New password').fill('New-password-456!');
    await page.getByLabel('Confirm password').fill('New-password-456!');
    await page.getByRole('button', { name: 'Update password' }).click();
    await expect(page.getByText('Password updated')).toBeVisible();
    await signOut(page);
    await page.getByRole('link', { name: 'Sign in' }).click();
    await page.getByLabel('Username or email').fill(username);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByText('Invalid credentials')).toBeVisible();
    await login(page, username, 'New-password-456!');
  });
  test('S2 wrong current password and mismatch are rejected', async ({ page }) => {
    const { username } = await register(page, 'chgbad');
    await login(page, username);
    await openSecurity(page);
    await page.getByLabel('Current password').fill('Incorrect-password-1!');
    await page.getByLabel('New password').fill('New-password-456!');
    await page.getByLabel('Confirm password').fill('does-not-match');
    await page.getByRole('button', { name: 'Update password' }).click();
    await expect(page.getByText('Current password is incorrect')).toBeVisible();
    await expect(page.getByText('Password confirmation does not match')).toBeVisible();
    await signOut(page);
    await login(page, username);
  });
  test('S3 empty current password is required', async ({ page }) => {
    const { username } = await register(page, 'chgempty');
    await login(page, username);
    await openSecurity(page);
    await page.getByLabel('New password').fill('Required-password-789!');
    await page.getByLabel('Confirm password').fill('Required-password-789!');
    await page.getByRole('button', { name: 'Update password' }).click();
    await expect(page.getByText('Current password is required')).toBeVisible();
    await signOut(page);
    await login(page, username);
  });
});
