import { test, expect } from '@playwright/test';
import { SEED, login, register, signOut, unique } from './helpers';

test.describe('REQ-2-1-1 Browse organization repositories', () => {
  test('S1 visitor filters to the public repository', async ({ page }) => {
    await page.goto(`/${SEED.org}`);
    await page.getByRole('link', { name: 'Repositories' }).click();
    await page.getByRole('textbox', { name: 'Find a repository' }).fill(SEED.repo);
    await page.getByRole('link', { name: 'Public', exact: true }).click();
    await page.getByRole('link', { name: SEED.repo, exact: true }).click();
    await expect(page.getByRole('heading', { name: `${SEED.org}/${SEED.repo}` })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole('link', { name: SEED.repo, exact: true })).toBeVisible();
    await page.getByRole('textbox', { name: 'Find a repository' }).fill(SEED.privateRepo);
    await expect(page.getByRole('link', { name: SEED.privateRepo })).toHaveCount(0);
    await page.goto(`/${SEED.org}/${SEED.privateRepo}`);
    await expect(page.getByText('Access denied')).toBeVisible();
  });
  test('S2 owner sees the private repository', async ({ page }) => {
    await login(page, SEED.alice.username);
    await page.goto(`/${SEED.org}`);
    await page.getByRole('link', { name: 'Repositories' }).click();
    await page.getByRole('textbox', { name: 'Find a repository' }).fill(SEED.privateRepo);
    await page.getByRole('link', { name: SEED.privateRepo, exact: true }).click();
    await expect(page.getByRole('heading', { name: `${SEED.org}/${SEED.privateRepo}` })).toBeVisible();
    await expect(page.getByText('Private', { exact: true })).toBeVisible();
  });
});

async function newOrgForm(page) {
  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.getByRole('link', { name: 'Your organizations' }).click();
  await page.getByRole('link', { name: 'New organization' }).click();
}

test.describe('REQ-2-1-2 Create organization', () => {
  test('S1 creates an organization', async ({ page }) => {
    await login(page, SEED.alice.username);
    await newOrgForm(page);
    const id = unique('guild');
    await page.getByLabel('Organization name').fill(id);
    await page.getByLabel('Display name').fill('Mobile Guild');
    await page.getByRole('button', { name: 'Create organization' }).click();
    await expect(page.getByRole('heading', { name: id })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: id })).toBeVisible();
    await page.getByRole('button', { name: 'Account menu' }).click();
    await page.getByRole('link', { name: 'Your organizations' }).click();
    await expect(page.getByRole('link', { name: id, exact: true })).toBeVisible();
  });
  test('S2 duplicate identifier is rejected', async ({ page }) => {
    await login(page, SEED.alice.username);
    await newOrgForm(page);
    await page.getByLabel('Organization name').fill(SEED.org);
    await page.getByRole('button', { name: 'Create organization' }).click();
    await expect(page.getByText('Organization name already exists')).toBeVisible();
    await expect(page.getByRole('heading', { name: SEED.org, exact: true })).toHaveCount(0);
  });
  test('S3 malformed identifier and blank display name', async ({ page }) => {
    await login(page, SEED.alice.username);
    await newOrgForm(page);
    await page.getByLabel('Organization name').fill('-invalid-organization');
    await page.getByLabel('Display name').fill('   ');
    await page.getByRole('button', { name: 'Create organization' }).click();
    await expect(page.getByText('Organization name format is invalid')).toBeVisible();
    await expect(page.getByText('Display name is required')).toBeVisible();
  });
});

async function createTeam(page, name: string, parent?: string) {
  await page.goto(`/${SEED.org}`);
  await page.getByRole('link', { name: 'Teams' }).click();
  await page.getByRole('link', { name: 'New team' }).click();
  await page.getByLabel('Team name').fill(name);
  if (parent) {
    await page.getByRole('combobox', { name: 'Parent team' }).click();
    await page.getByRole('option', { name: parent, exact: true }).click();
  }
  await page.getByRole('button', { name: 'Create team' }).click();
  await expect(page.getByRole('heading', { name: `${SEED.org}/${name}` })).toBeVisible();
}

test.describe('REQ-2-2-1 Create team', () => {
  test('S1 owner creates a team', async ({ page }) => {
    await login(page, SEED.alice.username);
    const name = unique('mobile-team');
    await createTeam(page, name);
    await page.reload();
    await expect(page.getByRole('heading', { name: `${SEED.org}/${name}` })).toBeVisible();
    await page.goto(`/orgs/${SEED.org}/teams`);
    await expect(page.getByRole('link', { name, exact: true })).toBeVisible();
  });
  test('S2 malformed team name', async ({ page }) => {
    await login(page, SEED.alice.username);
    await page.goto(`/${SEED.org}`);
    await page.getByRole('link', { name: 'Teams' }).click();
    await page.getByRole('link', { name: 'New team' }).click();
    await page.getByLabel('Team name').fill('Bad Team!');
    await page.getByRole('button', { name: 'Create team' }).click();
    await expect(page.getByText('Team name format is invalid')).toBeVisible();
  });
});

test.describe('REQ-2-2-2 Team members and hierarchy', () => {
  test('S1 adds and removes a member, sets parent', async ({ page }) => {
    await login(page, SEED.alice.username);
    const name = unique('team');
    await createTeam(page, name);
    await page.getByRole('link', { name: 'Members' }).click();
    await page.getByRole('button', { name: 'Add member' }).click();
    await page.getByRole('textbox', { name: 'Username' }).fill('henry-member');
    await page.getByRole('button', { name: 'Add member' }).click();
    await expect(page.getByRole('button', { name: 'Remove henry-member' })).toBeVisible();
    await page.reload();
    await expect(page.getByText('henry-member', { exact: true })).toBeVisible();
    await page.getByRole('link', { name: 'Settings' }).click();
    await page.getByRole('combobox', { name: 'Parent team' }).selectOption({ label: 'engineering' });
    await page.getByRole('button', { name: 'Save' }).click();
    await page.reload();
    await expect(page.getByRole('combobox', { name: 'Parent team' })).toHaveValue('engineering');
    await page.getByRole('link', { name: 'Members' }).click();
    await page.getByRole('button', { name: 'Remove henry-member' }).click();
    await expect(page.getByText('henry-member', { exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.getByText('henry-member', { exact: true })).toHaveCount(0);
  });
  test('S2 rejects a cyclic parent', async ({ page }) => {
    await login(page, SEED.alice.username);
    const parent = unique('parent');
    const child = unique('child');
    await createTeam(page, parent);
    await createTeam(page, child, parent);
    await page.goto(`/orgs/${SEED.org}/teams/${parent}`);
    await page.getByRole('link', { name: 'Settings' }).click();
    await page.getByRole('combobox', { name: 'Parent team' }).selectOption({ label: child });
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Cyclic team hierarchy is not allowed')).toBeVisible();
    await page.reload();
    await expect(page.getByRole('combobox', { name: 'Parent team' })).toHaveValue('');
  });
});

async function openPeople(page) {
  await page.goto(`/${SEED.org}`);
  await page.getByRole('link', { name: 'People' }).click();
}

async function addMember(page, login: string) {
  await page.getByRole('button', { name: 'Add member' }).click();
  await page.getByLabel('Username or email').fill(login);
  await page.getByRole('combobox', { name: 'Role' }).click();
  await page.getByRole('option', { name: 'Member', exact: true }).click();
  await page.getByRole('button', { name: 'Add member' }).last().click();
}

test.describe('REQ-2-2-3 Add organization member', () => {
  test('S1 adds a registered account as member', async ({ page, browser }) => {
    const other = await browser.newPage();
    const { username } = await register(other, 'member');
    await login(page, SEED.alice.username);
    await openPeople(page);
    await addMember(page, username);
    await expect(page.getByText(username, { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText(username, { exact: true })).toBeVisible();
    await expect(page.getByText('Pending')).toHaveCount(0);
    await login(other, username);
    await other.getByRole('button', { name: 'Account menu' }).click();
    await other.getByRole('link', { name: 'Your organizations' }).click();
    await expect(other.getByRole('link', { name: SEED.org, exact: true })).toBeVisible();
    await other.goto(`/${SEED.org}/${SEED.privateRepo}`);
    await expect(other.getByText('Access denied')).toBeVisible();
  });
  test('S2 existing member and unknown account are rejected', async ({ page }) => {
    await login(page, SEED.alice.username);
    await openPeople(page);
    await addMember(page, SEED.bob.username);
    await expect(page.getByText('Account is already a member')).toBeVisible();
    await page.getByLabel('Username or email').fill('unknown-reviewer');
    await page.getByRole('button', { name: 'Add member' }).last().click();
    await expect(page.getByText('Account not found')).toBeVisible();
    await page.reload();
    await expect(page.getByText(SEED.bob.username, { exact: true })).toHaveCount(1);
  });
});

test.describe('REQ-2-2-4 Remove organization member', () => {
  test('S1 owner removes a member', async ({ page, browser }) => {
    const other = await browser.newPage();
    const { username } = await register(other, 'leaver');
    await login(page, SEED.alice.username);
    await openPeople(page);
    await addMember(page, username);
    await page.getByRole('button', { name: `Member menu ${username}` }).click();
    await page.getByRole('menuitem', { name: 'Remove from organization' }).click();
    await page.getByRole('button', { name: 'Remove', exact: true }).click();
    await expect(page.getByText(username, { exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.getByText(username, { exact: true })).toHaveCount(0);
  });
  test('S2 non-owner has no member menu', async ({ page }) => {
    await login(page, SEED.bob.username);
    await openPeople(page);
    await expect(page.getByText('henry-member', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Member menu henry-member' })).toHaveCount(0);
    await expect(page.getByRole('menuitem', { name: 'Remove from organization' })).toHaveCount(0);
  });
});

test.describe('REQ-2-3 Repository access', () => {
  test('S1 grants a team Write access', async ({ page }) => {
    await login(page, SEED.alice.username);
    const team = unique('grant-team');
    await createTeam(page, team);
    await page.goto(`/${SEED.org}/${SEED.privateRepo}`);
    await page.getByRole('link', { name: 'Settings' }).click();
    await page.getByRole('link', { name: 'Manage access' }).click();
    await page.getByRole('button', { name: 'Add people or teams' }).click();
    await page.getByRole('textbox', { name: 'Search' }).fill(team);
    await page.getByRole('option', { name: team }).click();
    await page.getByRole('combobox', { name: 'Role' }).click();
    await page.getByRole('option', { name: 'Write' }).click();
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByRole('row', { name: team })).toContainText('Write');
    await page.reload();
    await expect(page.getByRole('row', { name: team })).toHaveCount(1);
  });
  test('S2 replaces an existing grant role', async ({ page }) => {
    await login(page, SEED.alice.username);
    await page.goto(`/${SEED.org}/${SEED.repo}/settings/access`);
    const row = page.getByRole('row', { name: /docs-team/ });
    await row.getByLabel('Role').selectOption({ label: 'Read' });
    await row.getByRole('button', { name: 'Save' }).click();
    await page.reload();
    await expect(page.getByRole('row', { name: /docs-team/ })).toHaveCount(1);
    await expect(page.getByRole('row', { name: /docs-team/ })).toContainText('Read');
  });
});
