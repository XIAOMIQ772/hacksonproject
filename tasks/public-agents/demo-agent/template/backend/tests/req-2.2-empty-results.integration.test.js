const request = require('supertest');
const { beforeAll, describe, expect, it } = require('vitest');
const app = require('../src/app');
const { initializeDatabase } = require('../src/database/init_db');

describe('REQ-2.2 empty search result route', () => {
  beforeAll(async () => {
    await initializeDatabase();
  });

  it('returns an explicit empty result payload when no trains match the route', async () => {
    const response = await request(app)
      .get('/api/search/tickets')
      .query({ from: 'Beijing', to: 'Kunming', date: '2026-07-07' });

    expect(response.status).toBe(200);
    expect(response.body.empty).toBe(true);
    expect(response.body.resultCount).toBe(0);
  });
});
