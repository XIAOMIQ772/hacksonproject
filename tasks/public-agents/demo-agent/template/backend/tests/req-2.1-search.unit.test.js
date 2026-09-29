const { describe, expect, it } = require('vitest');
const { normalizeQuery } = require('../src/services/search_service');

describe('REQ-2.1 search query normalization', () => {
  it('trims route inputs and preserves the requested date', () => {
    expect(
      normalizeQuery({
        from: ' Beijing ',
        to: ' Shanghai ',
        date: '2026-07-07',
      }),
    ).toEqual({
      from: 'Beijing',
      to: 'Shanghai',
      date: '2026-07-07',
    });
  });
});
