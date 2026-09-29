const { describe, expect, it } = require('vitest');
const { createBookingRecord } = require('../src/services/booking_service');

describe('REQ-3.2 booking creation validation', () => {
  it('rejects invalid passenger information without creating a booking record', async () => {
    await expect(
      createBookingRecord({
        userId: 1,
        trainId: 1,
        travelDate: '2026-07-07',
        passengerName: '',
        passengerIdNumber: '',
        seatType: '',
      }),
    ).rejects.toThrow();
  });
});
