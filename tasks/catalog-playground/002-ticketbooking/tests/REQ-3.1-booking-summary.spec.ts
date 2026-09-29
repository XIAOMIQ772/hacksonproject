import { expect, test } from '@playwright/test';
import {
  expectBookingSummary,
  expectSignedIn,
  expectVisibleJourneyTimes,
  openBookableTrain,
  registerAccount,
  searchTrains,
  signOut,
  uniqueTicketBookingAccount,
} from './support/e2e';

test('REQ-3.1: open the booking page and display the selected train summary', async ({
  page,
}) => {
  const account = uniqueTicketBookingAccount();
  const criteria = {
    from: 'Shanghai',
    to: 'Beijing',
    date: 'Sun, May 31',
  };

  await registerAccount(page, account);
  await expectSignedIn(page, account.username);
  await searchTrains(page, criteria);
  await openBookableTrain(page, 'G532');

  await expectBookingSummary(page);
  await expect(page.getByText(/g532/i)).toBeVisible();
  await expect(page.getByText(/sun, may 31/i)).toBeVisible();
  await expect(page.getByText(/departure time/i)).toBeVisible();
  await expect(page.getByText(/arrival time/i)).toBeVisible();
  await expectVisibleJourneyTimes(page);
});

test('REQ-3.1: display booking summaries for multiple selected trains', async ({ page }) => {
  const account = uniqueTicketBookingAccount();
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

  await registerAccount(page, account);
  await expectSignedIn(page, account.username);

  for (const currentCase of cases) {
    await searchTrains(page, currentCase.criteria);
    await openBookableTrain(page, currentCase.trainNumber);
    await expectBookingSummary(page);
    await expect(page.getByText(currentCase.train)).toBeVisible();
    await expect(page.getByText(currentCase.criteria.from, { exact: false })).toBeVisible();
    await expect(page.getByText(currentCase.criteria.to, { exact: false })).toBeVisible();
    await expect(page.getByText(/sun, may 31/i)).toBeVisible();
    await expectVisibleJourneyTimes(page);
  }
});

test('REQ-3.1: a signed-out visitor cannot use a selected journey to submit a booking', async ({ page }) => {
  const account = uniqueTicketBookingAccount();
  const criteria = { from: 'Shanghai', to: 'Beijing', date: 'Sun, May 31' };

  await registerAccount(page, account);
  await expectSignedIn(page, account.username);
  await signOut(page);
  await searchTrains(page, criteria);
  await openBookableTrain(page, 'G532');

  await expect(page.getByText(/please (?:sign in|log in)|sign in.+required|must be signed in|unauthorized/i)).toBeVisible();
  const submitBooking = page.getByRole('button', { name: /place order|submit booking/i });
  if (await submitBooking.count()) {
    await expect(submitBooking).toBeDisabled();
  }
});
