import { expect, test } from '@playwright/test';
import { baseUrl, expectSearchSummary, expectVisibleFeedback, searchTrains } from './support/e2e';

async function expectMatchingTrain(
  page: import('@playwright/test').Page,
  trainNumber: string,
  excludedTrainNumber: string,
): Promise<void> {
  await expect(page.getByText(new RegExp(`^${trainNumber}$`, 'i'))).toBeVisible();
  await expect(page.getByText(new RegExp(`^${excludedTrainNumber}$`, 'i'))).toHaveCount(0);
  await expect(page.getByText(/\b\d+\s+results?\b/i)).toBeVisible();
  await expect(
    page.getByRole('button', {
      name: new RegExp(`book\\s+${trainNumber}|${trainNumber}\\s+book`, 'i'),
    }),
  ).toBeVisible();
}

test('REQ-2.1: search with valid criteria and display matching train results', async ({
  page,
}) => {
  const criteria = {
    from: 'Shanghai',
    to: 'Beijing',
    date: 'Sun, May 31',
  };

  await searchTrains(page, criteria);
  await expectSearchSummary(page, criteria);
  await expectMatchingTrain(page, 'G532', 'G561');
});

test('REQ-2.1: block incomplete search input and stay on the homepage', async ({ page }) => {
  await page.goto(baseUrl());
  await page.getByLabel(/^from$/i).fill('Shanghai');
  await page.getByLabel(/^to$/i).fill('Beijing');
  await page.getByLabel(/^date$/i).fill('');
  await page.getByRole('button', { name: /search/i }).click();

  await expectVisibleFeedback(page, /date.+required|(?:enter|select|provide).+date|all fields.+required/i);
  await expect(page.getByRole('button', { name: /search/i })).toBeVisible();
});

test('REQ-2.1: trim surrounding whitespace in search criteria and still show results', async ({
  page,
}) => {
  const criteria = {
    from: ' Shanghai ',
    to: ' Beijing ',
    date: ' Sun, May 31 ',
  };

  await searchTrains(page, criteria);
  await expectSearchSummary(page, {
    from: 'Shanghai',
    to: 'Beijing',
    date: 'Sun, May 31',
  });
  await expectMatchingTrain(page, 'G532', 'G561');
});

test('REQ-2.1: search a different valid route and display the matching train', async ({ page }) => {
  const criteria = {
    from: 'Beijing',
    to: 'Tianjin',
    date: 'Sun, May 31',
  };

  await searchTrains(page, criteria);
  await expectSearchSummary(page, criteria);
  await expectMatchingTrain(page, 'G561', 'G532');
});

test('REQ-2.1: search supported routes with normalized criteria', async ({ page }) => {
  const cases = [
    {
      criteria: { from: 'Shanghai', to: 'Beijing', date: 'Sun, May 31' },
      normalized: { from: 'Shanghai', to: 'Beijing', date: 'Sun, May 31' },
      train: 'G532',
      excludedTrain: 'G561',
    },
    {
      criteria: { from: ' Beijing ', to: ' Tianjin ', date: ' Sun, May 31 ' },
      normalized: { from: 'Beijing', to: 'Tianjin', date: 'Sun, May 31' },
      train: 'G561',
      excludedTrain: 'G532',
    },
  ];

  for (const currentCase of cases) {
    await searchTrains(page, currentCase.criteria);
    await expectSearchSummary(page, currentCase.normalized);
    await expectMatchingTrain(page, currentCase.train, currentCase.excludedTrain);
  }
});

test('REQ-2.1: block incomplete search input across multiple missing-field combinations', async ({
  page,
}) => {
  const cases = [
    { from: 'Shanghai', to: 'Beijing', date: '' },
    { from: '', to: 'Beijing', date: 'Sun, May 31' },
    { from: 'Shanghai', to: '', date: 'Sun, May 31' },
  ];

  for (const criteria of cases) {
    await page.goto(baseUrl());
    await page.getByLabel(/^from$/i).fill(criteria.from);
    await page.getByLabel(/^to$/i).fill(criteria.to);
    await page.getByLabel(/^date$/i).fill(criteria.date);
    await page.getByRole('button', { name: /search/i }).click();

    await expectVisibleFeedback(
      page,
      /(?:from|to|date).+required|(?:enter|select|provide).+(?:from|to|date)|all fields.+required/i,
    );
    await expect(page.getByRole('button', { name: /search/i })).toBeVisible();
  }
});

test('REQ-2.1: reject a same-city search without opening a result list', async ({ page }) => {
  await page.goto(baseUrl());
  await page.getByLabel(/^from$/i).fill('Shanghai');
  await page.getByLabel(/^to$/i).fill(' shanghai ');
  await page.getByLabel(/^date$/i).fill('Sun, May 31');
  await page.getByRole('button', { name: /search/i }).click();

  await expectVisibleFeedback(page, /from.+to.+different|same (?:city|station)|choose.+different/i);
  await expect(page.getByRole('button', { name: /^book$/i })).toHaveCount(0);
});
