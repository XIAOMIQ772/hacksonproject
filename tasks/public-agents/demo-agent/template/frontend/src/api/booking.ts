import apiClient from './index';

export function fetchBookingOptions(params: { trainId: string; date: string }) {
  return apiClient.get('/booking/options', { params });
}

export function createBooking(payload: {
  trainId: number;
  travelDate: string;
  passengerName: string;
  passengerIdNumber: string;
  seatType: string;
}) {
  return apiClient.post('/booking/orders', payload);
}

export function fetchBookingResult(bookingId: string) {
  return apiClient.get(`/booking/orders/${bookingId}`);
}
