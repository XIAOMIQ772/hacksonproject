import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BookingPage from '../../pages/BookingPage';

vi.mock('../../api/booking', () => ({
  fetchBookingOptions: vi.fn().mockResolvedValue({
    data: {
      train: {
        trainNo: 'G101',
        departureDate: '2026-07-07',
        departureStation: 'Beijing(北京)',
        destinationStation: 'Shanghai(上海)',
        departureTime: '07:00',
        arrivalTime: '12:38',
      },
      passengerDefaults: {
        passengerName: '',
        passengerIdNumber: '',
        seatType: 'Second Class',
      },
    },
  }),
  createBooking: vi.fn(),
  fetchBookingResult: vi.fn(),
}));

describe('REQ-3.1 booking page summary', () => {
  beforeEach(() => {
    window.localStorage.setItem('arc_demo_token', 'token');
  });

  it('renders the selected train summary on the booking page', async () => {
    render(
      <MemoryRouter initialEntries={['/booking?trainId=1&date=2026-07-07']}>
        <BookingPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('G101')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Selected train' })).toBeInTheDocument();
  });
});
