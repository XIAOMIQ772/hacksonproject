const request = require('supertest');
const { beforeAll, describe, expect, it } = require('vitest');
const app = require('../src/app');
const { initializeDatabase } = require('../src/database/init_db');
const { createSessionForUser } = require('../src/repositories/auth_repository');

describe('REQ-3.3 booking result route', () => {
  let authToken = '';
  let bookingId = 0;

  beforeAll(async () => {
    await initializeDatabase();
    authToken = 'req33-token';
    await createSessionForUser(1, authToken);
    const createResponse = await request(app)
      .post('/api/booking/orders')
      .set('Authorization', `Bearer ${authToken}`)
      .send({
        trainId: 1,
        travelDate: '2026-07-07',
        passengerName: 'Result Passenger',
        passengerIdNumber: 'RID1234567890',
        seatType: 'Second Class',
      });
    bookingId = createResponse.body?.booking?.id || 0;
  });

  it('loads the current booking result for the current user', async () => {
    const response = await request(app)
      .get(`/api/booking/orders/${bookingId}`)
      .set('Authorization', `Bearer ${authToken}`);

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('booking');
  });
});
