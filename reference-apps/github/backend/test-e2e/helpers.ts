import { expect, Page } from '@playwright/test';

export const PASSWORD = 'Valid-password-123!';
export const SEED = {
  alice: { username: 'alice-dev', email: 'alice.dev@example.test' },
  bob: { username: 'bob-reviewer', email: 'bob.reviewer@example.test' },
  carol: { username: 'carol-reader' },
  org: 'acme-demo',
  repo: 'acme-docs',
  privateRepo: 'secret-research',
};

export function unique(purpose: string): string {
  return `${purpose}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

export async function login(page: Page, user: string, password = PASSWORD) {
  await page.goto('/');
  await page.getByRole('link', { name: 'Sign in' }).click();
  await page.getByLabel('Username or email').fill(user);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('button', { name: 'Account menu' })).toBeVisible();
}

export async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.getByRole('link', { name: 'Sign out' }).click();
  await page.getByRole('button', { name: 'Confirm sign out' }).click();
  await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible();
}

export async function register(page: Page, purpose = 'user') {
  const username = unique(purpose).toLowerCase();
  const email = `${username}@example.test`;
  await page.goto('/');
  await page.getByRole('link', { name: 'Sign in' }).click();
  await page.getByRole('link', { name: 'Create an account' }).click();
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByLabel('Confirm password').fill(PASSWORD);
  await page.getByRole('checkbox', { name: 'Agree to the terms' }).check();
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
  return { username, email };
}

export async function openRepo(page: Page, owner = SEED.org, repo = SEED.repo) {
  await page.goto(`/${owner}/${repo}`);
  await expect(page.getByRole('heading', { name: `${owner}/${repo}` })).toBeVisible();
}

export async function createRepo(page: Page, name: string, opts: { private?: boolean; readme?: boolean } = {}) {
  await page.goto('/');
  await page.getByRole('link', { name: 'New repository' }).click();
  await page.getByLabel('Repository name').fill(name);
  if (opts.private) await page.getByRole('radio', { name: 'Private' }).check();
  if (opts.readme !== false) await page.getByRole('checkbox', { name: 'Add a README file' }).check();
  await page.getByRole('button', { name: 'Create repository' }).click();
  await expect(page.getByRole('heading', { name })).toBeVisible();
}

export async function openIssue(page: Page, title: string, state: 'Open' | 'Closed' = 'Open') {
  await openRepo(page);
  await page.getByRole('link', { name: 'Issues', exact: true }).click();
  await page.getByRole('link', { name: state, exact: true }).click();
  await page.getByRole('searchbox', { name: 'Search issues' }).fill(title);
  await page.getByRole('link', { name: title, exact: true }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
}

export async function createIssue(page: Page, title: string, body = 'Issue body') {
  await openRepo(page);
  await page.getByRole('link', { name: 'Issues', exact: true }).click();
  await page.getByRole('link', { name: 'New issue' }).click();
  await page.getByLabel('Title').fill(title);
  await page.getByLabel('Description').fill(body);
  await page.getByRole('button', { name: 'Submit new issue' }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
}

export async function openPull(page: Page, title: string, state = 'Open') {
  await openRepo(page);
  await page.getByRole('link', { name: 'Pull requests', exact: true }).click();
  await page.getByRole('link', { name: state, exact: true }).click();
  await page.getByRole('link', { name: title, exact: true }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
}
