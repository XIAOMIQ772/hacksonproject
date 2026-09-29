const { describe, expect, it } = require('vitest');
const { sanitizeLoginPayload } = require('../src/services/auth_service');

describe('REQ-1.2 login payload sanitization', () => {
  it('trims the login account field', () => {
    expect(
      sanitizeLoginPayload({
        account: ' demo_user ',
        password: 'Password123',
      }),
    ).toEqual({
      account: 'demo_user',
      password: 'Password123',
    });
  });
});
