import { test, expect } from '@playwright/test';
import { SEED, createIssue, login, openIssue, openRepo, unique } from './helpers';

test.describe('REQ-5-1-1 Issue list', () => {
  test('S1 open filter with title search', async ({ page }) => {
    await openRepo(page);
    await page.getByRole('link', { name: 'Issues', exact: true }).click();
    await page.getByRole('link', { name: 'Open', exact: true }).click();
    await page.getByRole('searchbox', { name: 'Search issues' }).fill('Improve onboarding');
    await expect(page.getByRole('link', { name: 'Improve onboarding', exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('link', { name: 'Improve onboarding', exact: true })).toBeVisible();
  });
  test('S2 closed filter', async ({ page }) => {
    await openRepo(page);
    await page.getByRole('link', { name: 'Issues', exact: true }).click();
    await page.getByRole('link', { name: 'Closed', exact: true }).click();
    await page.getByRole('searchbox', { name: 'Search issues' }).fill('Legacy welcome text');
    await expect(page.getByRole('link', { name: 'Legacy welcome text', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Improve onboarding', exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole('link', { name: 'Legacy welcome text', exact: true })).toBeVisible();
  });
});

test.describe('REQ-5-1-2 Issue detail', () => {
  test('S1 visitor reads issue', async ({ page }) => {
    await openIssue(page, 'Improve onboarding');
    await expect(page.getByText('Open', { exact: true })).toBeVisible();
    await expect(page.getByText('Describe the onboarding improvement.', { exact: true })).toBeVisible();
    await expect(page.getByText('documentation', { exact: true })).toBeVisible();
    await expect(page.getByText('dave-triage', { exact: true })).toBeVisible();
    await expect(page.getByText(/Activity/).first()).toBeVisible();
  });
  test('S2 signed-in view has edit controls', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openIssue(page, 'Improve onboarding');
    await expect(page.getByRole('button', { name: 'Edit issue title' })).toBeVisible();
  });
  test('S3 visitor has no edit controls and reload keeps data', async ({ page }) => {
    await openIssue(page, 'Improve onboarding');
    await expect(page.getByRole('button', { name: 'Edit issue title' })).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Improve onboarding', exact: true })).toBeVisible();
  });
});

test.describe('REQ-5-2-1 Create issue', () => {
  test('S1 creates an issue', async ({ page }) => {
    await login(page, SEED.alice.username);
    const title = unique('issue');
    await createIssue(page, title, 'Created by the e2e suite');
    await expect(page.getByText('Created by the e2e suite', { exact: true })).toBeVisible();
    await openRepo(page);
    await page.getByRole('link', { name: 'Issues', exact: true }).click();
    await expect(page.getByRole('link', { name: title, exact: true })).toBeVisible();
  });
  test('S2 blank title rejected', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openRepo(page);
    await page.getByRole('link', { name: 'Issues', exact: true }).click();
    await page.getByRole('link', { name: 'New issue' }).click();
    await page.getByLabel('Title').fill('   ');
    await page.getByRole('button', { name: 'Submit new issue' }).click();
    await expect(page.getByText('Title is required')).toBeVisible();
  });
});

test.describe('REQ-5-2-2 Edit issue', () => {
  test('S1 edits title and description', async ({ page }) => {
    await login(page, SEED.alice.username);
    await createIssue(page, unique('edit'));
    const t = unique('edited');
    await page.getByRole('button', { name: 'Edit issue title' }).click();
    await page.getByRole('textbox', { name: 'Issue title' }).fill(t);
    await page.getByRole('button', { name: 'Save issue title' }).click();
    await page.getByRole('button', { name: 'Edit issue description' }).click();
    await page.getByRole('textbox', { name: 'Issue description' }).fill('New description text');
    await page.getByRole('button', { name: 'Save issue description' }).click();
    await page.reload();
    await expect(page.getByRole('heading', { name: t, exact: true })).toBeVisible();
    await expect(page.getByText('New description text', { exact: true })).toBeVisible();
  });
  test('S2 blank title keeps original', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openIssue(page, 'Original issue title');
    await page.getByRole('button', { name: 'Edit issue title' }).click();
    await page.getByRole('textbox', { name: 'Issue title' }).fill('   ');
    await page.getByRole('button', { name: 'Save issue title' }).click();
    await expect(page.getByText('Title is required')).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Original issue title', exact: true })).toBeVisible();
  });
});

test.describe('REQ-5-2-3 Comment', () => {
  test('S1 adds a comment', async ({ page }) => {
    await login(page, SEED.alice.username);
    await createIssue(page, unique('comment'));
    const body = unique('comment body');
    await page.getByRole('textbox', { name: 'Comment' }).fill(body);
    await page.getByRole('button', { name: 'Comment', exact: true }).click();
    await expect(page.getByText(body, { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText(body, { exact: true })).toBeVisible();
  });
  test('S2 whitespace comment adds nothing', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openIssue(page, 'Improve onboarding');
    const before = await page.getByRole('article').count();
    await page.getByRole('textbox', { name: 'Comment' }).fill('   ');
    await page.getByRole('button', { name: 'Comment', exact: true }).click();
    await expect(page.getByText('Comment is required')).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Improve onboarding', exact: true })).toBeVisible();
    await expect(page.getByRole('article')).toHaveCount(before);
  });
});

test('REQ-5-3-1 S1 assign and unassign', async ({ page }) => {
  await login(page, SEED.alice.username);
  await createIssue(page, unique('assign'));
  await page.getByRole('button', { name: 'Assignees' }).click();
  await page.getByRole('textbox', { name: 'Search assignees' }).fill('bob');
  await page.getByRole('option', { name: 'bob-reviewer', exact: true }).click();
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('bob-reviewer', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Assignees' }).click();
  await page.getByRole('option', { name: 'bob-reviewer', exact: true }).click();
  await page.reload();
  await expect(page.getByText('bob-reviewer', { exact: true })).toHaveCount(0);
});

test('REQ-5-3-2 S1 apply and remove a label', async ({ page }) => {
  await login(page, SEED.alice.username);
  await createIssue(page, unique('label'));
  await page.getByRole('button', { name: 'Labels' }).click();
  await page.getByRole('option', { name: 'bug', exact: true }).click();
  await page.reload();
  await expect(page.getByText('bug', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Labels' }).click();
  await page.getByRole('option', { name: 'bug', exact: true }).click();
  await page.reload();
  await expect(page.getByText('bug', { exact: true })).toHaveCount(0);
});

test('REQ-5-3-3 S1 milestone', async ({ page }) => {
  await login(page, SEED.alice.username);
  await createIssue(page, unique('milestone'));
  await page.getByRole('button', { name: 'Milestone' }).click();
  await page.getByRole('option', { name: 'Q3 launch', exact: true }).click();
  await page.reload();
  await expect(page.getByText('Q3 launch', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Milestone' }).click();
  await page.getByRole('option', { name: 'None', exact: true }).click();
  await page.reload();
  await expect(page.getByText('No milestone')).toBeVisible();
});

test.describe('REQ-5-4 Close and reopen issue', () => {
  test('S1 close then reopen', async ({ page }) => {
    await login(page, SEED.alice.username);
    await createIssue(page, unique('close'));
    await page.getByRole('button', { name: 'Close issue' }).click();
    await expect(page.getByText('Closed', { exact: true })).toBeVisible();
    await expect(page.getByText('Closed issue')).toBeVisible();
    await page.getByRole('button', { name: 'Reopen issue' }).click();
    await page.reload();
    await expect(page.getByRole('button', { name: 'Close issue' })).toBeVisible();
    await expect(page.getByText('Open', { exact: true })).toBeVisible();
  });
  test('S2 read-only viewer has no controls', async ({ page }) => {
    await login(page, SEED.carol.username);
    await openIssue(page, 'Protected issue');
    await expect(page.getByRole('button', { name: 'Close issue' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Reopen issue' })).toHaveCount(0);
  });
});
