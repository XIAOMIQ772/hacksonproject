import { test, expect } from '@playwright/test';
import { SEED, createRepo, login, openRepo, unique } from './helpers';

async function search(page, q: string) {
  const box = page.getByRole('searchbox', { name: 'Search' });
  await box.fill(q);
  await box.press('Enter');
}

test.describe('REQ-3-1 Repository search', () => {
  test('S1 visitor finds the public repository', async ({ page }) => {
    await page.goto('/');
    await search(page, SEED.repo);
    await expect(page.getByText(`${SEED.org}/${SEED.repo}`, { exact: true })).toBeVisible();
    await page.getByRole('link', { name: SEED.repo, exact: true }).click();
    await expect(page.getByRole('heading', { name: SEED.repo })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: SEED.repo })).toBeVisible();
  });
  test('S2 private repository is hidden from visitors', async ({ page }) => {
    await page.goto('/');
    await search(page, SEED.privateRepo);
    await expect(page.getByText('No results')).toBeVisible();
    await expect(page.getByRole('link', { name: SEED.privateRepo })).toHaveCount(0);
  });
  test('S3 no match shows No results again after returning home', async ({ page }) => {
    const q = unique('nothing');
    await page.goto('/');
    await search(page, q);
    await expect(page.getByText('No results')).toBeVisible();
    await page.getByRole('link', { name: 'Homepage' }).click();
    await search(page, q);
    await expect(page.getByText('No results')).toBeVisible();
  });
  test('S4 owner finds the private repository', async ({ page }) => {
    await login(page, SEED.alice.username);
    await search(page, SEED.privateRepo);
    await page.getByRole('link', { name: SEED.privateRepo, exact: true }).click();
    await expect(page.getByRole('heading', { name: SEED.privateRepo })).toBeVisible();
  });
});

test.describe('REQ-3-2-1 Create repository', () => {
  test('S1 creates a private repository with README', async ({ page }) => {
    await login(page, SEED.alice.username);
    const name = unique('repo');
    await page.getByRole('link', { name: 'New repository' }).click();
    await page.getByLabel('Repository name').fill(name);
    await page.getByLabel('Description').fill('Repository created by Playwright');
    await page.getByRole('radio', { name: 'Private' }).check();
    await page.getByRole('checkbox', { name: 'Add a README file' }).check();
    await page.getByRole('button', { name: 'Create repository' }).click();
    await expect(page.getByRole('heading', { name })).toBeVisible();
    await expect(page.getByText('Private', { exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'README.md' })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name })).toBeVisible();
    await expect(page.getByText('Repository created by Playwright', { exact: true })).toBeVisible();
  });
  test('S2 duplicate name stays on the form', async ({ page }) => {
    await login(page, SEED.alice.username);
    await page.getByRole('link', { name: 'New repository' }).click();
    await page.getByLabel('Repository name').fill('acme-docs-fork');
    await page.getByRole('button', { name: 'Create repository' }).click();
    await expect(page.getByText('Repository name already exists')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'alice-dev/acme-docs-fork' })).toHaveCount(0);
  });
  test('S3 empty name is rejected', async ({ page }) => {
    await login(page, SEED.alice.username);
    await page.getByRole('link', { name: 'New repository' }).click();
    await page.getByRole('button', { name: 'Create repository' }).click();
    await expect(page.getByText('Repository name is required')).toBeVisible();
  });
});

test.describe('REQ-3-2-2 Fork', () => {
  test('S1 forks into the personal namespace', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openRepo(page);
    await page.getByRole('button', { name: 'Fork' }).click();
    const name = unique('fork');
    await page.getByLabel('Repository name').fill(name);
    await page.getByRole('button', { name: 'Create fork' }).click();
    await expect(page.getByRole('heading', { name })).toBeVisible();
    await expect(page.getByText(`Forked from ${SEED.repo}`)).toBeVisible();
    await page.reload();
    await expect(page.getByRole('link', { name: SEED.repo, exact: true })).toBeVisible();
  });
  test('S2 conflicting fork name is rejected', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openRepo(page);
    await page.getByRole('button', { name: 'Fork' }).click();
    await page.getByLabel('Repository name').fill('acme-docs-fork');
    await page.getByRole('button', { name: 'Create fork' }).click();
    await expect(page.getByText('Repository name already exists')).toBeVisible();
  });
});

test.describe('REQ-3-2-3 Clone value', () => {
  test('S1 copies the HTTPS value', async ({ page }) => {
    await openRepo(page);
    await page.getByRole('button', { name: 'Code' }).click();
    await page.getByRole('tab', { name: 'HTTPS' }).click();
    await page.getByRole('button', { name: 'Copy clone value' }).click();
    await expect(page.getByText('Copied')).toBeVisible();
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toMatch(/^https:\/\/.*acme-demo\/acme-docs\.git$/);
    await expect(page.getByRole('heading', { name: `${SEED.org}/${SEED.repo}` })).toBeVisible();
  });
  test('S2 copies the SSH value', async ({ page }) => {
    await openRepo(page);
    await page.getByRole('button', { name: 'Code' }).click();
    await page.getByRole('tab', { name: 'SSH' }).click();
    await page.getByRole('button', { name: 'Copy clone value' }).click();
    await expect(page.getByText('Copied')).toBeVisible();
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toMatch(/^git@.*:acme-demo\/acme-docs\.git$/);
  });
});

test('REQ-3-3 S1 public repository overview', async ({ page }) => {
  await page.goto(`/${SEED.org}/${SEED.repo}`);
  await expect(page.getByRole('heading', { name: `${SEED.org}/${SEED.repo}` })).toBeVisible();
  await expect(page.getByText('Public', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Code', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Code', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: `${SEED.org}/${SEED.repo}` })).toBeVisible();
});

test.describe('REQ-3-4 Visibility', () => {
  test('S1 admin makes a private repository public', async ({ page, browser }) => {
    await login(page, SEED.alice.username);
    const name = unique('vis');
    await createRepo(page, name, { private: true });
    await page.getByRole('link', { name: 'Settings' }).click();
    await page.getByRole('link', { name: 'General' }).click();
    await page.getByRole('button', { name: 'Change visibility' }).click();
    await page.getByRole('radio', { name: 'Public' }).check();
    await page.getByRole('button', { name: 'Confirm visibility' }).click();
    await page.getByRole('link', { name: 'Code', exact: true }).click();
    await expect(page.getByText('Public', { exact: true })).toBeVisible();
    const visitor = await (await browser.newContext()).newPage();
    await visitor.goto(`/alice-dev/${name}`);
    await expect(visitor.getByRole('heading', { name })).toBeVisible();
  });
  test('S2 non-admin cannot change visibility', async ({ page }) => {
    await login(page, SEED.bob.username);
    await page.goto(`/${SEED.org}/visibility-demo`);
    await expect(page.getByRole('heading', { name: 'visibility-demo' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Change visibility' })).toHaveCount(0);
    await page.goto(`/${SEED.org}/visibility-demo/settings`);
    await expect(page.getByRole('button', { name: 'Change visibility' })).toHaveCount(0);
  });
});
