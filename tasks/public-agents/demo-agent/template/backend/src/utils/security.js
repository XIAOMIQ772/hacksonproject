const crypto = require('crypto');

function hashPassword(password) {
  const salt = crypto.randomBytes(16).toString('hex');
  const digest = crypto.scryptSync(String(password || ''), salt, 64).toString('hex');
  return `${salt}:${digest}`;
}

function verifyPassword(password, passwordHash) {
  const [salt, expectedDigest] = String(passwordHash || '').split(':');
  if (!salt || !expectedDigest) {
    return false;
  }

  const actualDigest = crypto.scryptSync(String(password || ''), salt, 64).toString('hex');
  return crypto.timingSafeEqual(Buffer.from(expectedDigest, 'hex'), Buffer.from(actualDigest, 'hex'));
}

function createToken() {
  return crypto.randomBytes(24).toString('hex');
}

function buildBookingNumber() {
  return `BK${Date.now()}${Math.floor(Math.random() * 1000).toString().padStart(3, '0')}`;
}

module.exports = {
  buildBookingNumber,
  createToken,
  hashPassword,
  verifyPassword,
};
