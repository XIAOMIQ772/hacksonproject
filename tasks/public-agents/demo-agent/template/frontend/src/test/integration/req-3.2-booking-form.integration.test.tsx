import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import BookingPage from '../../pages/BookingPage';

vi.mock('../../api/booking', () => ({
  fetchBookingOptions: vi.fn().mockResolvedValue({
    data: {
      train: {
        trainNo: 'G101',
        departureDate: '2026-07-07',
        departureStation: 'Beijing',
        departureTime: '07:00',
        destinationStation: 'Shanghai',
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

describe('REQ-3.2 booking form shell', () => {
  it('renders passenger name, id number, seat type, and submit action', async () => {
    render(
      <MemoryRouter initialEntries={['/booking?trainId=1&date=2026-07-07']}>
        <BookingPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('button', { name: 'Submit booking' })).toBeInTheDocument();
    expect(screen.getByLabelText('Passenger name')).toBeInTheDocument();
    expect(screen.getByLabelText('ID number')).toBeInTheDocument();
    expect(screen.getByLabelText('Seat type')).toBeInTheDocument();
  });
});
