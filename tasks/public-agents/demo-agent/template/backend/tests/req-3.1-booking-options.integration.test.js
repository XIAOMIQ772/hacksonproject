const request = require('supertest');
const { beforeAll, describe, expect, it } = require('vitest');
const app = require('../src/app');
const { initializeDatabase } = require('../src/database/init_db');
const { createSessionForUser } = require('../src/repositories/auth_repository');

describe('REQ-3.1 booking options route', () => {
  let authToken = '';

  beforeAll(async () => {
    await initializeDatabase();
    authToken = 'req31-token';
    await createSessionForUser(1, authToken);
  });

  it('returns the selected train summary for a logged-in user', async () => {
    const response = await request(app)
      .get('/api/booking/options')
      .set('Authorization', `Bearer ${authToken}`)
      .query({ trainId: 1, date: '2026-07-07' });

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('train');
    expect(response.body.train).toHaveProperty('trainNo');
  });
});
