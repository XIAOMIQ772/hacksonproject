import { test, expect } from '@playwright/test';
import { SEED, createRepo, login, openRepo, unique } from './helpers';

test('REQ-4-1 S1 browse directory and file', async ({ page }) => {
  await openRepo(page);
  await page.getByRole('link', { name: 'src', exact: true }).click();
  await page.getByRole('link', { name: 'search.ts', exact: true }).click();
  await expect(page.getByText('const normalized = query.trim();')).toBeVisible();
  await page.reload();
  await expect(page.getByText('const normalized = query.trim();')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Branch main' })).toBeVisible();
});

test('REQ-4-2-1 S1 commit history', async ({ page }) => {
  await openRepo(page);
  await page.getByRole('link', { name: 'Commits', exact: true }).click();
  await expect(page.getByText('Document search flow', { exact: true })).toBeVisible();
  await expect(page.getByText('alice-dev', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/ago/).first()).toBeVisible();
});

test('REQ-4-2-2 S1 commit diff', async ({ page }) => {
  await openRepo(page);
  await page.getByRole('link', { name: 'Commits', exact: true }).click();
  await page.getByRole('link', { name: 'Document search flow' }).click();
  await expect(page.getByText('src/search.ts', { exact: true })).toBeVisible();
  await expect(page.getByText('Changed files')).toBeVisible();
  await expect(page.getByText(/\d+ additions, \d+ deletions/)).toBeVisible();
});

async function repoSearch(page, q: string) {
  const box = page.getByRole('searchbox', { name: 'Search' });
  await box.fill(q);
  await box.press('Enter');
}

test.describe('REQ-4-2-3 Code search', () => {
  test('S1 finds README.md', async ({ page }) => {
    await openRepo(page);
    await repoSearch(page, 'search flow');
    await page.getByRole('link', { name: 'Code', exact: true }).click();
    await page.getByRole('link', { name: 'README.md', exact: true }).click();
    await expect(page.getByText('search flow', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText('search flow', { exact: true })).toBeVisible();
  });
  test('S2 no code results', async ({ page }) => {
    await openRepo(page);
    await repoSearch(page, 'no-such-token');
    await page.getByRole('link', { name: 'Code', exact: true }).click();
    await expect(page.getByText('No code results')).toBeVisible();
    await expect(page.getByRole('searchbox', { name: 'Search' })).toHaveValue('no-such-token');
    await openRepo(page);
    await repoSearch(page, 'no-such-token');
    await expect(page.getByText('No code results')).toBeVisible();
  });
  test('S3 path filter limits results', async ({ page }) => {
    await openRepo(page);
    await repoSearch(page, 'normalized');
    await page.getByRole('textbox', { name: 'Path' }).fill('src/');
    await expect(page.getByRole('link', { name: 'search.ts', exact: true })).toBeVisible();
    await page.getByRole('textbox', { name: 'Path' }).fill('docs/');
    await expect(page.getByText('No code results')).toBeVisible();
  });
  test('S4 signed-in search', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openRepo(page);
    await repoSearch(page, 'search flow');
    await expect(page.getByRole('link', { name: 'README.md', exact: true })).toBeVisible();
  });
});

test.describe('REQ-4-3-1 Branches', () => {
  test('S1 switches to feature-search', async ({ page }) => {
    await openRepo(page);
    await page.getByRole('button', { name: 'Branch main' }).click();
    await page.getByRole('textbox', { name: 'Find branch' }).fill('feature-search');
    await page.getByRole('option', { name: 'feature-search', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Branch feature-search' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'main-only.md', exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('button', { name: 'Branch feature-search' })).toBeVisible();
  });
  test('S2 unmatched search keeps branch', async ({ page }) => {
    await openRepo(page);
    await page.getByRole('button', { name: 'Branch main' }).click();
    await page.getByRole('textbox', { name: 'Find branch' }).fill('zz-unknown');
    await expect(page.getByText('No matching branch')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: 'Branch main' })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('button', { name: 'Branch main' })).toBeVisible();
  });
});

test.describe('REQ-4-3-2 Create branch', () => {
  test('S1 creates a branch', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openRepo(page);
    const name = unique('branch');
    await page.getByRole('button', { name: 'Branch main' }).click();
    await page.getByRole('textbox', { name: 'Find branch' }).fill(name);
    await page.getByRole('option', { name: `Create branch: ${name}` }).click();
    await expect(page.getByRole('button', { name: `Branch ${name}` })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('button', { name: `Branch ${name}` })).toBeVisible();
  });
  test('S2 invalid branch name', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openRepo(page);
    await page.getByRole('button', { name: 'Branch main' }).click();
    await page.getByRole('textbox', { name: 'Find branch' }).fill('invalid..branch');
    await expect(page.getByText('Invalid branch')).toBeVisible();
    await expect(page.getByRole('option', { name: /Create branch/ })).toHaveCount(0);
  });
});

test.describe('REQ-4-3-3 Default branch', () => {
  test('S1 admin changes the default branch', async ({ page }) => {
    await login(page, SEED.alice.username);
    const name = unique('defbranch');
    await createRepo(page, name);
    await page.getByRole('button', { name: 'Branch main' }).click();
    await page.getByRole('textbox', { name: 'Find branch' }).fill('release');
    await page.getByRole('option', { name: 'Create branch: release' }).click();
    await page.getByRole('link', { name: 'Settings' }).click();
    await page.getByRole('link', { name: 'Branches' }).click();
    await page.getByRole('combobox', { name: 'Default branch' }).selectOption('release');
    await page.getByRole('button', { name: 'Update' }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await page.goto(`/alice-dev/${name}`);
    await expect(page.getByRole('button', { name: 'Branch release' })).toBeVisible();
    await page.getByRole('button', { name: 'Branch release' }).click();
    await expect(page.getByRole('option', { name: 'main', exact: true })).toBeVisible();
  });
  test('S2 non-admin has no default branch control', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openRepo(page);
    await expect(page.getByRole('link', { name: 'Settings' })).toHaveCount(0);
    await page.goto(`/${SEED.org}/${SEED.repo}/settings/branches`);
    await expect(page.getByRole('combobox', { name: 'Default branch' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Update' })).toHaveCount(0);
  });
});

test.describe('REQ-4-4 Web file editor', () => {
  test('S1 creates a file', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openRepo(page);
    const file = `${unique('file')}.md`;
    await page.getByRole('button', { name: 'Add file' }).click();
    await page.getByRole('menuitem', { name: 'Create new file' }).click();
    await page.getByLabel('File name').fill(file);
    await page.getByRole('textbox', { name: 'File contents' }).fill('Hello from the web editor');
    await expect(page.getByLabel('Commit message')).toHaveValue('');
    await page.getByLabel('Commit message').fill(`Add ${file}`);
    await page.getByRole('button', { name: 'Commit changes' }).click();
    await expect(page.getByText('Hello from the web editor', { exact: true })).toBeVisible();
    await page.getByRole('link', { name: 'Commits', exact: true }).click();
    await expect(page.getByText(`Add ${file}`, { exact: true })).toBeVisible();
  });
  test('S2 invalid path and missing message', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openRepo(page);
    await page.getByRole('button', { name: 'Add file' }).click();
    await page.getByRole('menuitem', { name: 'Create new file' }).click();
    await page.getByLabel('File name').fill('../invalid.md');
    await page.getByRole('textbox', { name: 'File contents' }).fill('must not be saved');
    await page.getByRole('button', { name: 'Commit changes' }).click();
    await expect(page.getByText('Invalid file path')).toBeVisible();
    await expect(page.getByText('Commit message is required')).toBeVisible();
    await openRepo(page);
    await expect(page.getByRole('link', { name: 'invalid.md' })).toHaveCount(0);
  });
});
