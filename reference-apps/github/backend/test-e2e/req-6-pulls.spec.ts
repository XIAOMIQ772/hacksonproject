import { test, expect } from '@playwright/test';
import { SEED, createRepo, login, openPull, openRepo, unique } from './helpers';

test.describe('REQ-6-1 Branch protection', () => {
  test('S1 admin creates a rule', async ({ page }) => {
    await login(page, SEED.alice.username);
    const name = unique('protect');
    await createRepo(page, name);
    await page.getByRole('link', { name: 'Settings' }).click();
    await page.getByRole('link', { name: 'Branches' }).click();
    await page.getByRole('button', { name: 'Add branch protection rule' }).click();
    await page.getByLabel('Branch name pattern').fill('main');
    await page.getByRole('checkbox', { name: 'Require 1 approval' }).check();
    await page.getByRole('checkbox', { name: 'Require status check test' }).check();
    await page.getByRole('button', { name: 'Create' }).click();
    await page.reload();
    await expect(page.getByText('main', { exact: true })).toBeVisible();
    await expect(page.getByText('1 approval', { exact: true })).toBeVisible();
    await expect(page.getByText('Require status check test', { exact: true })).toBeVisible();
  });
  test('S2 non-admin has no rule entry', async ({ page }) => {
    await login(page, SEED.bob.username);
    await page.goto(`/${SEED.org}/${SEED.repo}/settings/branches`);
    await expect(page.getByRole('button', { name: 'Add branch protection rule' })).toHaveCount(0);
  });
  test('S3 admin sets test to success', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openPull(page, 'Add review guide');
    await expect(page.getByText('test: pending')).toBeVisible();
    await page.getByRole('combobox', { name: 'test status' }).click();
    await page.getByRole('option', { name: 'success' }).click();
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('test: success')).toBeVisible();
    await expect(page.getByText(/Set by alice-dev/)).toBeVisible();
    await page.reload();
    await expect(page.getByText('test: success')).toBeVisible();
  });
});

test.describe('REQ-6-2-1 Pull request list', () => {
  test('S1 visitor opens the open PR', async ({ page }) => {
    await openPull(page, 'Improve onboarding');
    await page.goBack();
    await page.reload();
    await expect(page.getByRole('link', { name: 'Improve onboarding', exact: true })).toBeVisible();
  });
  test('S2 closed filter', async ({ page }) => {
    await openRepo(page);
    await page.getByRole('link', { name: 'Pull requests', exact: true }).click();
    await page.getByRole('link', { name: 'Closed', exact: true }).click();
    await expect(page.getByRole('link', { name: 'Fix search', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Improve onboarding', exact: true })).toHaveCount(0);
  });
  test('S3 author filter', async ({ page }) => {
    await openRepo(page);
    await page.getByRole('link', { name: 'Pull requests', exact: true }).click();
    await page.getByRole('textbox', { name: 'Author' }).fill('alice');
    await expect(page.getByRole('link', { name: 'Improve onboarding', exact: true })).toBeVisible();
    await page.getByRole('textbox', { name: 'Author' }).fill('nobody-here');
    await expect(page.getByRole('link', { name: 'Improve onboarding', exact: true })).toHaveCount(0);
  });
});

async function openCompare(page) {
  await openRepo(page);
  await page.getByRole('link', { name: 'Pull requests', exact: true }).click();
  await page.getByRole('link', { name: 'New pull request' }).click();
  await page.getByRole('combobox', { name: 'base' }).selectOption('main');
  await page.getByRole('combobox', { name: 'compare' }).selectOption('feature-search');
  await page.getByRole('button', { name: 'Compare changes' }).click();
}

test.describe('REQ-6-2-2 Compare', () => {
  test('S1 shows changes', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openCompare(page);
    await expect(page.getByText('src/search.ts', { exact: true })).toBeVisible();
    await expect(page.getByText('Commit summary')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create pull request' })).toBeEnabled();
  });
  test('S2 same branch shows No changes', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openCompare(page);
    await page.getByRole('combobox', { name: 'compare' }).selectOption('main');
    await expect(page.getByText('No changes')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create pull request' })).toBeDisabled();
    await page.getByRole('button', { name: 'Compare changes' }).click();
    await expect(page.getByText('No changes')).toBeVisible();
  });
});

test.describe('REQ-6-2-3 Create PR', () => {
  test('S1 creates a PR', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openCompare(page);
    await page.getByRole('button', { name: 'Create pull request' }).click();
    const title = unique('pr');
    await page.getByLabel('Title').fill(title);
    await page.getByRole('button', { name: 'Create pull request' }).click();
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
    await expect(page.getByText('Open', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  });
  test('S2 blank title rejected', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openCompare(page);
    await page.getByRole('button', { name: 'Create pull request' }).click();
    await page.getByLabel('Title').fill('   ');
    await page.getByRole('button', { name: 'Create pull request' }).click();
    await expect(page.getByText('Title is required')).toBeVisible();
  });
});

test.describe('REQ-6-2-4 Draft PR', () => {
  test('S1 creates a draft', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openCompare(page);
    await page.getByRole('button', { name: 'Create draft pull request' }).click();
    const title = unique('draft');
    await page.getByLabel('Title').fill(title);
    await page.getByRole('button', { name: 'Create draft pull request' }).click();
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
    await expect(page.getByText('Draft', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Merge pull request' })).toBeDisabled();
  });
  test('S2 ready for review', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openPull(page, 'Draft onboarding update');
    await expect(page.getByText('draft-feature', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Ready for review' }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.getByText('Draft', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Ready for review', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText('Open', { exact: true })).toBeVisible();
  });
});

test.describe('REQ-6-3-1 PR overview', () => {
  test('S1 visitor navigates tabs', async ({ page }) => {
    await openPull(page, 'Improve onboarding');
    await page.getByRole('link', { name: 'Commits', exact: true }).click();
    await expect(page.getByText('Commit summary')).toBeVisible();
    await page.getByRole('link', { name: 'Files changed', exact: true }).click();
    await expect(page.getByText('Changed files')).toBeVisible();
  });
  test('S2 reload keeps heading and links', async ({ page }) => {
    await openPull(page, 'Improve onboarding');
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Improve onboarding', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Files changed', exact: true })).toBeVisible();
  });
  test('S3 signed-in view shows discussion', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openPull(page, 'Improve onboarding');
    await expect(page.getByText('Looks good so far, I will review the search changes.')).toBeVisible();
  });
});

test('REQ-6-3-2 S1 files changed aggregate', async ({ page }) => {
  await openPull(page, 'Improve onboarding');
  await page.getByRole('link', { name: 'Files changed', exact: true }).click();
  await expect(page.getByText('src/search.ts', { exact: true })).toBeVisible();
  await expect(page.getByText('3 additions, 1 deletions')).toBeVisible();
});

test.describe('REQ-6-3-3 Inline comments', () => {
  test('S1 single comment', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openPull(page, 'Add FAQ');
    await page.getByRole('link', { name: 'Files changed', exact: true }).click();
    await page.getByRole('button', { name: 'Add comment' }).first().click();
    const body = unique('inline');
    await page.getByRole('textbox', { name: 'Comment' }).fill(body);
    await page.getByRole('button', { name: 'Add single comment' }).click();
    await expect(page.getByText(body, { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText(body, { exact: true })).toBeVisible();
  });
  test('S2 pending review comment', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openPull(page, 'Add glossary');
    await page.getByRole('link', { name: 'Files changed', exact: true }).click();
    await page.getByRole('button', { name: 'Add comment' }).first().click();
    const body = unique('pending');
    await page.getByRole('textbox', { name: 'Comment' }).fill(body);
    await page.getByRole('button', { name: 'Start a review' }).click();
    await expect(page.getByText('Pending review')).toBeVisible();
    await page.reload();
    await expect(page.getByText(body, { exact: true })).toBeVisible();
  });
});

test.describe('REQ-6-3-4 Submit review', () => {
  test('S1 approve', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openPull(page, 'Add review guide');
    await page.getByRole('link', { name: 'Files changed', exact: true }).click();
    await page.getByRole('button', { name: 'Review changes' }).click();
    await page.getByRole('radio', { name: 'Approve' }).check();
    await page.getByRole('button', { name: 'Submit review' }).click();
    await expect(page.getByText('Approved', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText('Approved', { exact: true })).toBeVisible();
  });
  test('S2 request changes', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openPull(page, 'Add style guide');
    await page.getByRole('link', { name: 'Files changed', exact: true }).click();
    await page.getByRole('button', { name: 'Review changes' }).click();
    await page.getByLabel('Summary').fill('Please shorten the guide.');
    await page.getByRole('radio', { name: 'Request changes' }).check();
    await page.getByRole('button', { name: 'Submit review' }).click();
    await expect(page.getByText('Changes requested', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText('Please shorten the guide.', { exact: true })).toBeVisible();
  });
});

test('REQ-6-4 S1 request and remove reviewer', async ({ page }) => {
  await login(page, SEED.alice.username);
  await openPull(page, 'Improve onboarding');
  await page.getByRole('button', { name: 'Reviewers' }).click();
  await page.getByRole('textbox', { name: 'Search' }).fill('bob-reviewer');
  await page.getByRole('option', { name: 'bob-reviewer', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Remove bob-reviewer' })).toBeVisible();
  await page.getByRole('button', { name: 'Remove bob-reviewer' }).click();
  await expect(page.getByRole('button', { name: 'Remove bob-reviewer' })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('button', { name: 'Remove bob-reviewer' })).toHaveCount(0);
});

test.describe('REQ-6-5 Merge', () => {
  test('S1 merges an eligible PR', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openPull(page, 'Ready to merge');
    await page.getByRole('button', { name: 'Merge pull request' }).click();
    await page.getByRole('button', { name: 'Confirm merge' }).click();
    await expect(page.getByText('Merged', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText('Merged', { exact: true })).toBeVisible();
  });
  test('S2 blocked PR explains the rule', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openPull(page, 'Blocked merge');
    await expect(page.getByRole('button', { name: 'Merge pull request' })).toBeDisabled();
    await expect(page.getByText('Review required by branch protection')).toBeVisible();
  });
});

test.describe('REQ-6-6 Close and reopen PR', () => {
  test('S1 author closes and reopens', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openCompare(page);
    await page.getByRole('button', { name: 'Create pull request' }).click();
    await page.getByLabel('Title').fill(unique('close-pr'));
    await page.getByRole('button', { name: 'Create pull request' }).click();
    await page.getByRole('button', { name: 'Close pull request' }).click();
    await expect(page.getByText('Closed', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Reopen pull request' }).click();
    await expect(page.getByText('Open', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('button', { name: 'Close pull request' })).toBeVisible();
  });
  test('S2 read viewer has no controls', async ({ page }) => {
    await login(page, SEED.carol.username);
    await openPull(page, 'Improve onboarding');
    await expect(page.getByRole('button', { name: 'Close pull request' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Reopen pull request' })).toHaveCount(0);
  });
});
