const { describe, expect, it } = require('vitest');
const { sanitizeRegistrationPayload } = require('../src/services/auth_service');

describe('REQ-1.1 registration payload sanitization', () => {
  it('trims username and email fields before validation', () => {
    expect(
      sanitizeRegistrationPayload({
        username: ' demo ',
        email: ' user@example.com ',
        password: 'Password123',
        confirmPassword: 'Password123',
      }),
    ).toEqual({
      username: 'demo',
      email: 'user@example.com',
      password: 'Password123',
      confirmPassword: 'Password123',
    });
  });
});
