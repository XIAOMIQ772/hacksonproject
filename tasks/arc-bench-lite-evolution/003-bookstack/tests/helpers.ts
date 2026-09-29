import { expect, Locator, Page } from '@playwright/test';

export const FIXTURES = {
  auth: {
    nickname: 'BookStack User',
    email: 'bookstack_user@example.com',
    password: 'Password123!',
    invalidEmail: 'unknown.bookstack@example.com',
    invalidPassword: 'WrongPassword123!',
  },
  sorting: {
    bookName: 'Evolution Sort Book',
    chapterName: 'Beta Chapter',
    pageName: 'Alpha Page',
  },
  comments: {
    bookName: 'Evolution Comments Book',
    pageName: 'Review Guidelines',
    text: 'This page needs review.',
  },
  export: {
    bookName: 'Evolution Export Book',
  },
  search: {
    bookName: 'Evolution Search Book',
    matchingPageName: 'Deployment Guide',
    outsidePageName: 'Deployment Archive',
    keyword: 'Deployment',
  },
  revisions: {
    bookName: 'Evolution Revisions Book',
    pageName: 'Release Process',
    revisionLabel: 'Revision 2',
  },
} as const;

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function toPattern(value: string | RegExp): RegExp {
  if (value instanceof RegExp) return value;
  return new RegExp(escapeRegExp(value).replace(/\s+/g, '\\s+'), 'i');
}

async function firstVisible(locators: Locator[]): Promise<Locator> {
  for (const locator of locators) {
    const candidate = locator.first();
    try {
      if (await candidate.isVisible({ timeout: 500 })) return candidate;
    } catch {
      // continue
    }
  }
  return locators[0].first();
}

export async function clickNamed(page: Page, value: string | RegExp): Promise<void> {
  const name = toPattern(value);
  const locator = await firstVisible([
    page.getByRole('button', { name }),
    page.getByRole('link', { name }),
    page.getByRole('tab', { name }),
    page.getByRole('menuitem', { name }),
    page.getByText(name),
  ]);
  await locator.click();
}

export async function expectTextsVisible(page: Page, values: Array<string | RegExp>): Promise<void> {
  for (const value of values) {
    const name = toPattern(value);
    const locator = await firstVisible([
      page.getByRole('heading', { name }),
      page.getByRole('button', { name }),
      page.getByRole('link', { name }),
      page.getByRole('tab', { name }),
      page.getByText(name),
      page.getByLabel(name),
      page.getByPlaceholder(name),
    ]);
    await expect(locator).toBeVisible();
  }
}

export async function fillField(page: Page, labelOrPlaceholder: string, value: string): Promise<void> {
  const name = toPattern(labelOrPlaceholder);
  const locator = await firstVisible([
    page.getByLabel(name),
    page.getByPlaceholder(name),
    page.getByRole('textbox', { name }),
    page.getByRole('searchbox', { name }),
  ]);
  await locator.fill(value);
}

export async function expectSuccessFeedback(page: Page): Promise<void> {
  const locator = await firstVisible([
    page.getByRole('alert'),
    page.getByRole('status'),
    page.getByText(/success|saved|created|deleted|updated/i),
  ]);
  await expect(locator).toBeVisible();
}

export async function openHome(page: Page): Promise<void> {
  await page.goto('/');
}

export async function openLoginPage(page: Page): Promise<void> {
  await openHome(page);
  await clickNamed(page, /^Login$/i);
}

export async function login(page: Page): Promise<void> {
  await openLoginPage(page);
  await fillField(page, 'Email', FIXTURES.auth.email);
  await fillField(page, 'Password', FIXTURES.auth.password);
  const remember = page.getByRole('checkbox', { name: /remember me/i });
  if (await remember.count()) {
    await remember.check();
  }
  await clickNamed(page, /^Login$/i);
}

export async function openShelves(page: Page): Promise<void> {
  await openHome(page);
  await clickNamed(page, /^Shelves$/i);
}

export async function openShelfDetails(page: Page, shelfName: string): Promise<void> {
  await openShelves(page);
  await clickNamed(page, shelfName);
}

export async function openBooks(page: Page): Promise<void> {
  await openHome(page);
  await clickNamed(page, /^Books$/i);
}

export async function openBookDetailsFromList(page: Page, bookName: string): Promise<void> {
  await openBooks(page);
  await clickNamed(page, bookName);
}

export async function openBookDetailsFromShelf(page: Page, shelfName: string, bookName: string): Promise<void> {
  await openShelfDetails(page, shelfName);
  await clickNamed(page, bookName);
}

export async function openBookCreationFromList(page: Page): Promise<void> {
  await openBooks(page);
  await clickNamed(page, /Create New Book/i);
}

export async function openBookCreationFromShelf(page: Page, shelfName: string): Promise<void> {
  await openShelfDetails(page, shelfName);
  await clickNamed(page, /Create New Book/i);
}

export async function openPageReading(page: Page, bookName: string, pageName: string): Promise<void> {
  await openBookDetailsFromList(page, bookName);
  await clickNamed(page, pageName);
}

export async function returnHomeByLogo(page: Page): Promise<void> {
  const logo = await firstVisible([
    page.getByRole('link', { name: /bookstack/i }),
    page.getByText(/bookstack/i),
  ]);
  await logo.click();
}
