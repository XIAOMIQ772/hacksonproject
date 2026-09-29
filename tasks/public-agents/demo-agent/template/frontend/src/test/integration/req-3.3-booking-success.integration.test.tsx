import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import BookingSuccessPage from '../../pages/BookingSuccessPage';

vi.mock('../../api/booking', () => ({
  fetchBookingOptions: vi.fn(),
  createBooking: vi.fn(),
  fetchBookingResult: vi.fn().mockResolvedValue({
    data: {
      booking: {
        passengerIdNumber: 'ID1234567890',
        passengerName: 'Demo Passenger',
        bookingNumber: 'BK20260707001',
        seatType: 'Second Class',
        status: 'success',
        train: {
          trainNo: 'G101',
          departureStation: 'Beijing',
          departureTime: '07:00',
          destinationStation: 'Shanghai',
          arrivalTime: '12:38',
        },
        travelDate: '2026-07-07',
      },
    },
  }),
}));

describe('REQ-3.3 booking success shell', () => {
  it('renders the stored booking result on the success page', async () => {
    render(
      <MemoryRouter initialEntries={['/booking/success/101']}>
        <Routes>
          <Route path="/booking/success/:bookingId" element={<BookingSuccessPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Booking success' })).toBeInTheDocument();
    expect(await screen.findByText('BK20260707001')).toBeInTheDocument();
    expect(screen.getByText('Demo Passenger')).toBeInTheDocument();
    expect(screen.getByText('Second Class')).toBeInTheDocument();
  });
});
