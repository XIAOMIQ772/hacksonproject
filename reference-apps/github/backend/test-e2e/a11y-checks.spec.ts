// Rule 2.5 / 2.4 checks (not hidden-test scenarios): every visible label text resolves to exactly one
// element via getByLabel(exact), and duplicate same-role names per view are reported.
import { test, expect, Page } from '@playwright/test';
import { SEED, login } from './helpers';

const INTERACTIVE = ['button', 'link', 'textbox', 'searchbox', 'combobox', 'checkbox', 'radio', 'tab', 'option', 'menuitem'];

async function labelTexts(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const vis = (el: Element) => !!(el as HTMLElement).offsetParent || getComputedStyle(el).position === 'fixed';
    const out = new Set<string>();
    document.querySelectorAll('label').forEach((l) => { if (vis(l)) { const t = (l.textContent || '').trim().replace(/\s+/g, ' '); if (t) out.add(t); } });
    document.querySelectorAll('[aria-labelledby]').forEach((el) => {
      if (!vis(el)) return;
      const t = el.getAttribute('aria-labelledby')!.split(/\s+/).map((id) => document.getElementById(id)?.textContent?.trim() || '').join(' ').trim();
      if (t) out.add(t);
    });
    document.querySelectorAll('input[aria-label],textarea[aria-label],select[aria-label]').forEach((el) => { if (vis(el)) out.add(el.getAttribute('aria-label')!); });
    return [...out];
  });
}

// Mandated repeats: REQ-2-3 requires a native select "Role" + "Save" in every grant row (scoped by row);
// REQ-6-3-3 requires one "Add comment" per changed line.
const EXEMPT = (view: string, text: string) => view.includes('/settings/access') && text === 'Role';

async function check(page: Page, view: string, problems: string[], dupes: string[]) {
  for (const text of await labelTexts(page)) {
    if (EXEMPT(view, text)) continue;
    const n = await page.getByLabel(text, { exact: true }).count();
    if (n !== 1) problems.push(`${view}: label "${text}" -> ${n} elements`);
  }
  const snap = await page.locator('body').ariaSnapshot();
  const seen = new Map<string, number>();
  for (const m of snap.matchAll(/- (\w+) "([^"]*)"/g)) {
    if (!INTERACTIVE.includes(m[1])) continue;
    const k = `${m[1]} "${m[2]}"`;
    seen.set(k, (seen.get(k) || 0) + 1);
  }
  for (const [k, n] of seen) if (n > 1) dupes.push(`${view}: ${k} x${n}`);
}

test('label uniqueness and duplicate names across main views', async ({ page: first, browser }) => {
  test.setTimeout(180000);
  let page = first;
  const problems: string[] = [];
  const dupes: string[] = [];
  const R = `/${SEED.org}/${SEED.repo}`;
  const visit = async (url: string, view = url) => { await page.goto(url); await page.waitForTimeout(250); await check(page, view, problems, dupes); };
  const open = async (view: string, action: () => Promise<void>) => { await action(); await page.waitForTimeout(150); await check(page, view, problems, dupes); };

  for (const u of ['/', '/login', '/signup', `/${SEED.org}`, `/orgs/${SEED.org}/teams`, `/orgs/${SEED.org}/people`, R, `${R}/tree/main/src`, `${R}/blob/main/README.md`,
    `${R}/commits/main`, `${R}/search?q=search%20flow&type=code`, '/search?q=acme&type=repositories', `${R}/issues`, `${R}/issues/1`, `${R}/pulls`, `${R}/pull/6`, `${R}/pull/6/commits`, `${R}/pull/6/files`]) await visit(u);
  await visit('/password_reset');
  await open('reset step 2', async () => { await page.getByLabel('Email').fill('x@example.test'); await page.getByRole('button', { name: 'Send reset link' }).click(); });
  await visit(R);
  await open('clone menu', () => page.getByRole('button', { name: 'Code' }).click());
  await visit(R);
  await open('branch selector', () => page.getByRole('button', { name: 'Branch main' }).click());

  await login(page, SEED.alice.username);
  for (const u of ['/', '/new', '/organizations', '/organizations/new', '/settings/security', `/orgs/${SEED.org}/new-team`, `/orgs/${SEED.org}/teams/frontend-team/settings`, `${R}/fork`, `${R}/new/main`,
    `${R}/settings`, `${R}/issues/new`, `${R}/compare/main...feature-search`]) await visit(u);
  await open('account menu', () => page.getByRole('button', { name: 'Account menu' }).click());
  await visit(`/orgs/${SEED.org}/people`);
  await open('add org member', () => page.getByRole('button', { name: 'Add member' }).click());
  await open('role listbox', () => page.getByRole('combobox', { name: 'Role' }).click());
  await visit(`/orgs/${SEED.org}/people`);
  await open('member menu', () => page.getByRole('button', { name: 'Member menu bob-reviewer' }).click());
  await visit(`/orgs/${SEED.org}/teams/frontend-team/members`);
  await open('add team member', () => page.getByRole('button', { name: 'Add member' }).click());
  await visit(`${R}/settings`);
  await open('visibility dialog', () => page.getByRole('button', { name: 'Change visibility' }).click());
  await visit(`${R}/settings/access`);
  await open('access picker', () => page.getByRole('button', { name: 'Add people or teams' }).click());
  await open('access role listbox', () => page.getByRole('combobox', { name: 'Role' }).click());
  await visit(`${R}/settings/branches`);
  await open('protection form', () => page.getByRole('button', { name: 'Add branch protection rule' }).click());
  await visit(`${R}/issues/1`);
  await open('edit title', () => page.getByRole('button', { name: 'Edit issue title' }).click());
  await visit(`${R}/issues/1`);
  await open('edit description', () => page.getByRole('button', { name: 'Edit issue description' }).click());
  for (const p of ['Assignees', 'Labels', 'Milestone']) { await visit(`${R}/issues/1`); await open(`${p} picker`, () => page.getByRole('button', { name: p }).click()); }
  await visit(`${R}/compare/main...feature-search`);
  await open('create PR form', () => page.getByRole('button', { name: 'Create pull request' }).click());
  await visit(`${R}/pull/6`);
  await open('reviewers picker', () => page.getByRole('button', { name: 'Reviewers' }).click());
  await visit(`${R}/pull/6`);
  await open('test status listbox', () => page.getByRole('combobox', { name: 'test status' }).click());

  page = await (await browser.newContext()).newPage();
  await login(page, SEED.bob.username);
  await visit(`${R}/pull/6/files`);
  await open('review form', () => page.getByRole('button', { name: 'Review changes' }).click());
  await visit(`${R}/pull/6/files`);
  await open('inline comment', () => page.getByRole('button', { name: 'Add comment' }).first().click());

  console.log(`LABEL PROBLEMS (${problems.length}):\n${problems.join('\n')}`);
  console.log(`DUPLICATE SAME-ROLE NAMES (${dupes.length}):\n${dupes.join('\n')}`);
  expect(problems).toEqual([]);
});
