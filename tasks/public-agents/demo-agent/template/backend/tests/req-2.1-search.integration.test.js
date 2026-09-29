const request = require('supertest');
const { beforeAll, describe, expect, it } = require('vitest');
const app = require('../src/app');
const { initializeDatabase } = require('../src/database/init_db');

describe('REQ-2.1 search route', () => {
  beforeAll(async () => {
    await initializeDatabase();
  });

  it('returns a runtime search payload for a valid route query', async () => {
    const response = await request(app)
      .get('/api/search/tickets')
      .query({ from: 'Beijing', to: 'Shanghai', date: '2026-07-07' });

    expect(response.status).toBe(200);
    expect(response.body).toHaveProperty('search');
    expect(response.body).toHaveProperty('trains');
  });
});
