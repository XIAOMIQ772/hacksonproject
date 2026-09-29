const { describe, expect, it } = require('vitest');
const { loadBookingOrder } = require('../src/services/booking_service');

describe('REQ-3.3 booking result lookup', () => {
  it('rejects missing booking records for the current user', async () => {
    await expect(loadBookingOrder({ userId: 1, bookingId: '999999' })).rejects.toThrow();
  });
});
