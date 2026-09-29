const request = require('supertest');
const { beforeAll, describe, expect, it } = require('vitest');
const app = require('../src/app');
const { initializeDatabase } = require('../src/database/init_db');

describe('REQ-1.1 registration route', () => {
  beforeAll(async () => {
    await initializeDatabase();
  });

  it('returns a JSON payload when the registration endpoint is called', async () => {
    const response = await request(app).post('/api/auth/register').send({
      username: 'newuser',
      email: 'newuser@example.com',
      password: 'Password123',
      confirmPassword: 'Password123',
    });

    expect(response.status).toBe(201);
    expect(response.body).toHaveProperty('user');
  });
});
