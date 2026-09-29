const request = require('supertest');
const { beforeAll, describe, expect, it } = require('vitest');
const app = require('../src/app');
const { initializeDatabase } = require('../src/database/init_db');

describe('REQ-1.2 login route', () => {
  beforeAll(async () => {
    await initializeDatabase();
  });

  it('returns a JSON payload when the login endpoint is called', async () => {
    const response = await request(app).post('/api/auth/login').send({
      account: 'demo_user',
      password: 'Password123',
    });

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('message');
  });
});
