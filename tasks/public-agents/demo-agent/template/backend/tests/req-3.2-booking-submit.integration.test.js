const request = require('supertest');
const { beforeAll, describe, expect, it } = require('vitest');
const app = require('../src/app');
const { initializeDatabase } = require('../src/database/init_db');
const { createSessionForUser } = require('../src/repositories/auth_repository');

describe('REQ-3.2 booking submit route', () => {
  let authToken = '';

  beforeAll(async () => {
    await initializeDatabase();
    authToken = 'req32-token';
    await createSessionForUser(1, authToken);
  });

  it('creates a booking record for a logged-in user with valid passenger information', async () => {
    const response = await request(app)
      .post('/api/booking/orders')
      .set('Authorization', `Bearer ${authToken}`)
      .send({
        trainId: 1,
        travelDate: '2026-07-07',
        passengerName: 'Demo Passenger',
        passengerIdNumber: 'ID1234567890',
        seatType: 'Second Class',
      });

    expect(response.status).toBe(201);
    expect(response.body).toHaveProperty('booking');
  });
});
