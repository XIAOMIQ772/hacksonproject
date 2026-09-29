const { findSessionUserByToken } = require('../repositories/auth_repository');

async function requireAuth(req, res, next) {
  const authorizationHeader = req.headers.authorization || '';
  const token = authorizationHeader.startsWith('Bearer ')
    ? authorizationHeader.slice(7)
    : '';

  if (!token) {
    res.status(401).json({ message: 'Unauthorized.' });
    return;
  }

  try {
    const user = await findSessionUserByToken(token);
    if (!user) {
      res.status(401).json({ message: 'Unauthorized.' });
      return;
    }

    req.authToken = token;
    req.user = user;
    next();
  } catch (error) {
    next(error);
  }
}

module.exports = {
  requireAuth,
};
