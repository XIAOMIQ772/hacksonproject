import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import {
  expectBookingSummary,
  expectSignedIn,
  expectVisibleFeedback,
  openBookableTrain,
  registerAccount,
  searchTrains,
  uniqueTicketBookingAccount,
} from './support/e2e';

type BookingInput = {
  criteria: {
    from: string;
    to: string;
    date: string;
  };
  passenger: {
    name: string;
    idNumber: string;
    nationality: string;
  };
  ticketClass: string;
};

async function openBookingPage(
  page: Page,
  criteria: BookingInput['criteria'],
  trainNumber: string,
): Promise<void> {
  await searchTrains(page, criteria);
  await openBookableTrain(page, trainNumber);
  await expectBookingSummary(page);
}

async function fillBookingForm(
  page: Page,
  ticketClass: string,
  passenger: BookingInput['passenger'],
  options: { acceptTerms?: boolean } = {},
): Promise<void> {
  await page.getByRole('combobox', { name: /ticket class/i }).selectOption({ label: ticketClass });
  await page.getByRole('combobox', { name: /ticket type/i }).selectOption({ label: 'Adult' });
  await page.getByRole('textbox', { name: /^name$/i }).fill(passenger.name);
  await page.getByRole('textbox', { name: /id number/i }).fill(passenger.idNumber);
  await page.getByRole('textbox', { name: /nationality/i }).fill(passenger.nationality);
  if (options.acceptTerms !== false) {
    await page.getByRole('checkbox', { name: /terms of service/i }).check();
  }
}

async function expectSubmittedBookingDetails(page: Page, input: BookingInput): Promise<void> {
  await expect(page.getByText(input.criteria.from, { exact: false })).toBeVisible();
  await expect(page.getByText(input.criteria.to, { exact: false })).toBeVisible();
  await expect(page.getByText(/sun, may 31/i)).toBeVisible();
  await expect(page.getByText(input.passenger.name, { exact: false })).toBeVisible();
  await expect(page.getByText(input.passenger.idNumber, { exact: false })).toBeVisible();
  await expect(page.getByText(input.passenger.nationality, { exact: false })).toBeVisible();
  await expect(page.getByText(input.ticketClass, { exact: false })).toBeVisible();
  await expect(page.getByText(/adult/i)).toBeVisible();
}

async function readVisibleBookingNumber(page: Page): Promise<string> {
  const bookingNumberText = await page
    .getByText(/(?:booking|order) number\s*[:#-]?\s*[a-z0-9-]{4,}/i)
    .innerText();
  const match = bookingNumberText.match(/(?:booking|order) number\s*[:#-]?\s*([a-z0-9-]{4,})/i);
  expect(match, 'A visible booking number must follow the Booking number label').not.toBeNull();
  return match![1];
}

test('REQ-3.2: submit valid passenger information and create a booking record', async ({
  page,
}) => {
  const account = uniqueTicketBookingAccount();
  const criteria = {
    from: 'Shanghai',
    to: 'Beijing',
    date: 'Sun, May 31',
  };
  const passenger = {
    name: 'Nguyen Duc Minh',
    idNumber: 'C612345677',
    nationality: 'Vietnam',
  };

  await registerAccount(page, account);
  await expectSignedIn(page, account.username);
  await searchTrains(page, criteria);
  await openBookableTrain(page, 'G532');
  await expectBookingSummary(page);

  await page.getByRole('combobox', { name: /ticket class/i }).selectOption({ label: 'standing ticket' });
  await page.getByRole('combobox', { name: /ticket type/i }).selectOption({ label: 'Adult' });
  await page.getByRole('textbox', { name: /^name$/i }).fill(passenger.name);
  await page.getByRole('textbox', { name: /id number/i }).fill(passenger.idNumber);
  await page.getByRole('textbox', { name: /nationality/i }).fill(passenger.nationality);
  await page.getByRole('checkbox', { name: /terms of service/i }).check();
  await page.getByRole('button', { name: /place order/i }).click();

  await expect(page.getByText(/please confirm the following information/i)).toBeVisible();
  await expectSubmittedBookingDetails(page, {
    criteria,
    passenger,
    ticketClass: 'standing ticket',
  });
  await page.getByRole('button', { name: /confirm/i }).click();
  await expect(page.getByText(/booking number|order number|success|confirmed/i)).toBeVisible();
  await expectSubmittedBookingDetails(page, {
    criteria,
    passenger,
    ticketClass: 'standing ticket',
  });
  const bookingNumber = await readVisibleBookingNumber(page);
  await expect(page.getByRole('button', { name: /^confirm$/i })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText(bookingNumber, { exact: false })).toBeVisible();
  await expectSubmittedBookingDetails(page, {
    criteria,
    passenger,
    ticketClass: 'standing ticket',
  });
});

test('REQ-3.2: create bookings across supported route and seat combinations', async ({ page }) => {
  const cases: BookingInput[] = [
    {
      criteria: { from: 'Shanghai', to: 'Beijing', date: 'Sun, May 31' },
      passenger: {
        name: 'Nguyen Duc Minh',
        idNumber: 'C612345677',
        nationality: 'Vietnam',
      },
      ticketClass: 'standing ticket',
    },
    {
      criteria: { from: 'Beijing', to: 'Tianjin', date: 'Sun, May 31' },
      passenger: {
        name: 'Chen Li',
        idNumber: 'D712345678',
        nationality: 'Vietnam',
      },
      ticketClass: 'Business Class',
    },
  ];

  for (const currentCase of cases) {
    const account = uniqueTicketBookingAccount();

    await registerAccount(page, account);
    await expectSignedIn(page, account.username);
    await openBookingPage(
      page,
      currentCase.criteria,
      currentCase.criteria.from === 'Shanghai' ? 'G532' : 'G561',
    );
    await fillBookingForm(page, currentCase.ticketClass, currentCase.passenger);
    await page.getByRole('button', { name: /place order/i }).click();

    await expect(page.getByText(/please confirm the following information/i)).toBeVisible();
    await expectSubmittedBookingDetails(page, currentCase);
    await page.getByRole('button', { name: /confirm/i }).click();
    await expect(page.getByText(/booking number|order number|success|confirmed/i)).toBeVisible();
    await expectSubmittedBookingDetails(page, currentCase);
    await readVisibleBookingNumber(page);
  }
});

test('REQ-3.2: reject invalid passenger information without creating a booking', async ({
  page,
}) => {
  const account = uniqueTicketBookingAccount();
  const criteria = {
    from: 'Shanghai',
    to: 'Beijing',
    date: 'Sun, May 31',
  };

  await registerAccount(page, account);
  await searchTrains(page, criteria);
  await openBookableTrain(page, 'G532');
  await expectBookingSummary(page);

  await fillBookingForm(
    page,
    'standing ticket',
    { name: '', idNumber: 'C612345677', nationality: 'Vietnam' },
  );
  await page.getByRole('button', { name: /place order/i }).click();

  await expectVisibleFeedback(page, /name.+required|(?:enter|provide).+(?:passenger )?name/i);
  await expect(page.getByText(/please confirm the following information/i)).not.toBeVisible();
});

test('REQ-3.2: reject multiple invalid passenger combinations before confirmation', async ({
  page,
}) => {
  const account = uniqueTicketBookingAccount();
  const criteria = {
    from: 'Shanghai',
    to: 'Beijing',
    date: 'Sun, May 31',
  };
  const cases = [
    {
      passenger: { name: 'A', idNumber: 'C612345677', nationality: 'Vietnam' },
      expected: /name.+(?:at least 2|too short|invalid)|(?:enter|provide).+valid.+name/i,
      acceptTerms: true,
    },
    {
      passenger: { name: 'Nguyen Duc Minh', idNumber: '12345', nationality: 'Vietnam' },
      expected: /id(?: number)?.+(?:at least 6|too short|invalid)|(?:enter|provide).+valid.+id/i,
      acceptTerms: true,
    },
    {
      passenger: { name: 'Nguyen Duc Minh', idNumber: 'C612345677', nationality: '' },
      expected: /nationality.+(?:required|missing)|(?:enter|provide).+nationality/i,
      acceptTerms: true,
    },
    {
      passenger: { name: 'Nguyen Duc Minh', idNumber: 'C612345677', nationality: 'Vietnam' },
      expected: /(?:accept|agree).+terms|terms.+(?:required|must be accepted)/i,
      acceptTerms: false,
    },
  ];

  await registerAccount(page, account);
  await expectSignedIn(page, account.username);

  for (const currentCase of cases) {
    await openBookingPage(page, criteria, 'G532');
    await fillBookingForm(page, 'standing ticket', currentCase.passenger, {
      acceptTerms: currentCase.acceptTerms,
    });
    await page.getByRole('button', { name: /place order/i }).click();

    await expectVisibleFeedback(page, currentCase.expected);
    await expect(page.getByText(/please confirm the following information/i)).not.toBeVisible();
  }
});

test('REQ-3.2: reject passenger name or ID values that are too short', async ({
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

  await page.getByRole('combobox', { name: /ticket class/i }).selectOption({ label: 'standing ticket' });
  await page.getByRole('combobox', { name: /ticket type/i }).selectOption({ label: 'Adult' });
  await page.getByRole('textbox', { name: /^name$/i }).fill('A');
  await page.getByRole('textbox', { name: /id number/i }).fill('12345');
  await page.getByRole('textbox', { name: /nationality/i }).fill('Vietnam');
  await page.getByRole('checkbox', { name: /terms of service/i }).check();
  await page.getByRole('button', { name: /place order/i }).click();

  await expectVisibleFeedback(
    page,
    /name.+(?:at least 2|too short|invalid)|id(?: number)?.+(?:at least 6|too short|invalid)/i,
  );
  await expect(page.getByText(/please confirm the following information/i)).not.toBeVisible();
});

test('REQ-3.2: create a booking with another supported seat type', async ({ page }) => {
  const account = uniqueTicketBookingAccount();
  const criteria = {
    from: 'Shanghai',
    to: 'Beijing',
    date: 'Sun, May 31',
  };
  const passenger = {
    name: 'Chen Li',
    idNumber: 'D712345678',
    nationality: 'Vietnam',
  };

  await registerAccount(page, account);
  await expectSignedIn(page, account.username);
  await searchTrains(page, criteria);
  await openBookableTrain(page, 'G532');
  await expectBookingSummary(page);

  await page.getByRole('combobox', { name: /ticket class/i }).selectOption({ label: 'Business Class' });
  await page.getByRole('combobox', { name: /ticket type/i }).selectOption({ label: 'Adult' });
  await page.getByRole('textbox', { name: /^name$/i }).fill(passenger.name);
  await page.getByRole('textbox', { name: /id number/i }).fill(passenger.idNumber);
  await page.getByRole('textbox', { name: /nationality/i }).fill(passenger.nationality);
  await page.getByRole('checkbox', { name: /terms of service/i }).check();
  await page.getByRole('button', { name: /place order/i }).click();
  await expect(page.getByText(/please confirm the following information/i)).toBeVisible();
  await expectSubmittedBookingDetails(page, {
    criteria,
    passenger,
    ticketClass: 'Business Class',
  });
  await page.getByRole('button', { name: /confirm/i }).click();

  await expect(page.getByText(/booking number|order number|success|confirmed/i)).toBeVisible();
  await expectSubmittedBookingDetails(page, {
    criteria,
    passenger,
    ticketClass: 'Business Class',
  });
  await readVisibleBookingNumber(page);
});
