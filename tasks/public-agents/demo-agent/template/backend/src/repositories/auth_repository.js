const { get, run } = require('../database/db_runtime');

async function findUserByUsername(username) {
  return get('SELECT id, username, email FROM users WHERE username = ?', [username]);
}

async function findUserByEmail(email) {
  return get('SELECT id, username, email FROM users WHERE email = ?', [email]);
}

async function findUserByAccount(account) {
  return get(
    'SELECT id, username, email, password_hash FROM users WHERE username = ? OR email = ?',
    [account, account],
  );
}

async function insertUser({ username, email, passwordHash }) {
  const result = await run(
    'INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
    [username, email, passwordHash],
  );
  return get('SELECT id, username, email FROM users WHERE id = ?', [result.lastID]);
}

async function createSessionForUser(userId, token) {
  return run('INSERT INTO sessions (user_id, token) VALUES (?, ?)', [userId, token]);
}

async function findSessionUserByToken(token) {
  return get(
    `
      SELECT users.id, users.username, users.email
      FROM sessions
      JOIN users ON users.id = sessions.user_id
      WHERE sessions.token = ?
    `,
    [token],
  );
}

async function deleteSessionByToken(token) {
  return run('DELETE FROM sessions WHERE token = ?', [token]);
}

module.exports = {
  createSessionForUser,
  deleteSessionByToken,
  findUserByAccount,
  findUserByEmail,
  findSessionUserByToken,
  findUserByUsername,
  insertUser,
};
