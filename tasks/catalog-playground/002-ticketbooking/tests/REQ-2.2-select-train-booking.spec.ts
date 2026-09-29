import { expect, test } from '@playwright/test';
import { expectVisibleJourneyTimes, openBookableTrain, searchTrains } from './support/e2e';

test('REQ-2.2: select a train from the result list and open the booking page', async ({
  page,
}) => {
  const criteria = {
    from: 'Shanghai',
    to: 'Beijing',
    date: 'Sun, May 31',
  };

  await searchTrains(page, criteria);
  await openBookableTrain(page, 'G532');

  await expect(page.getByText(/train information/i)).toBeVisible();
  await expect(page.getByText(/g532/i)).toBeVisible();
  await expect(page.getByText(/shanghaihongqiao|shanghai/i)).toBeVisible();
  await expect(page.getByText(/beijingnan|beijing/i)).toBeVisible();
  await expect(page.getByText(/sun, may 31/i)).toBeVisible();
  await expect(page.getByText(/departure time/i)).toBeVisible();
  await expect(page.getByText(/arrival time/i)).toBeVisible();
  await expectVisibleJourneyTimes(page);
});

test('REQ-2.2: open the booking page from multiple bookable routes', async ({ page }) => {
  const cases = [
    {
      criteria: { from: 'Shanghai', to: 'Beijing', date: 'Sun, May 31' },
      train: /g532/i,
      trainNumber: 'G532',
    },
    {
      criteria: { from: 'Beijing', to: 'Tianjin', date: 'Sun, May 31' },
      train: /g561/i,
      trainNumber: 'G561',
    },
  ];

  for (const currentCase of cases) {
    await searchTrains(page, currentCase.criteria);
    await openBookableTrain(page, currentCase.trainNumber);

    await expect(page.getByText(/train information/i)).toBeVisible();
    await expect(page.getByText(currentCase.train)).toBeVisible();
    await expect(page.getByText(currentCase.criteria.from, { exact: false })).toBeVisible();
    await expect(page.getByText(currentCase.criteria.to, { exact: false })).toBeVisible();
    await expect(page.getByText(/sun, may 31/i)).toBeVisible();
    await expectVisibleJourneyTimes(page);
  }
});
