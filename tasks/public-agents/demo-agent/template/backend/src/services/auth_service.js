const {
  createSessionForUser,
  findUserByAccount,
  findUserByEmail,
  findUserByUsername,
  insertUser,
} = require('../repositories/auth_repository');
const { createToken, hashPassword, verifyPassword } = require('../utils/security');

function createHttpError(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function sanitizeRegistrationPayload(body = {}) {
  return {
    username: String(body.username || '').trim(),
    email: String(body.email || '').trim(),
    password: String(body.password || ''),
    confirmPassword: String(body.confirmPassword || ''),
  };
}

function sanitizeLoginPayload(body = {}) {
  return {
    account: String(body.account || '').trim(),
    password: String(body.password || ''),
  };
}

async function registerAccount(body = {}) {
  const payload = sanitizeRegistrationPayload(body);

  if (!payload.username || !payload.email || !payload.password || !payload.confirmPassword) {
    throw createHttpError(400, 'Please fill in username, email, password, and confirm password.');
  }

  if (payload.password !== payload.confirmPassword) {
    throw createHttpError(400, 'Passwords do not match.');
  }

  const existingByUsername = await findUserByUsername(payload.username);
  const existingByEmail = await findUserByEmail(payload.email);

  if (existingByUsername) {
    throw createHttpError(409, 'Username already exists.');
  }

  if (existingByEmail) {
    throw createHttpError(409, 'Email already exists.');
  }

  const createdUser = await insertUser({
    username: payload.username,
    email: payload.email,
    passwordHash: hashPassword(payload.password),
  });
  const token = createToken();
  await createSessionForUser(createdUser.id, token);

  return {
    message: 'Registration successful.',
    token,
    user: createdUser,
  };
}

async function buildLoginSession(body = {}) {
  const payload = sanitizeLoginPayload(body);

  if (!payload.account || !payload.password) {
    throw createHttpError(400, 'Please enter your username or email and password.');
  }

  const user = await findUserByAccount(payload.account);

  if (!user) {
    throw createHttpError(404, 'User not found.');
  }

  if (!verifyPassword(payload.password, user.password_hash)) {
    throw createHttpError(400, 'Incorrect password.');
  }

  const token = createToken();
  await createSessionForUser(user.id, token);

  return {
    message: 'Login successful.',
    token,
    user: {
      id: user.id,
      username: user.username,
      email: user.email,
    },
  };
}

module.exports = {
  buildLoginSession,
  registerAccount,
  sanitizeLoginPayload,
  sanitizeRegistrationPayload,
};
