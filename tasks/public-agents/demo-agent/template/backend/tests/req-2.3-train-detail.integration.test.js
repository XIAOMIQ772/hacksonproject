const request = require('supertest');
const { beforeAll, describe, expect, it } = require('vitest');
const app = require('../src/app');
const { initializeDatabase } = require('../src/database/init_db');

describe('REQ-2.3 train detail route', () => {
  beforeAll(async () => {
    await initializeDatabase();
  });

  it('returns a selected train detail payload by train id', async () => {
    const searchResponse = await request(app)
      .get('/api/search/tickets')
      .query({ from: 'Beijing', to: 'Shanghai', date: '2026-07-07' });

    const trainId = searchResponse.body.trains[0]?.id;
    const detailResponse = await request(app)
      .get(`/api/search/trains/${trainId}`)
      .query({ date: '2026-07-07' });

    expect(detailResponse.status).toBe(200);
    expect(detailResponse.body).toHaveProperty('train');
  });
});
