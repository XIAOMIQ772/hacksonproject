const express = require('express');
const { requireAuth } = require('../middleware/auth');
const { deleteSessionByToken } = require('../repositories/auth_repository');
const {
  buildLoginSession,
  registerAccount,
} = require('../services/auth_service');

const router = express.Router();

router.post('/register', async (req, res, next) => {
  try {
    const payload = await registerAccount(req.body || {});
    res.status(201).json(payload);
  } catch (error) {
    if (error && error.status) {
      res.status(error.status).json({ message: error.message });
      return;
    }
    next(error);
  }
});

router.post('/login', async (req, res, next) => {
  try {
    const payload = await buildLoginSession(req.body || {});
    res.json(payload);
  } catch (error) {
    if (error && error.status) {
      res.status(error.status).json({ message: error.message });
      return;
    }
    next(error);
  }
});

router.get('/me', requireAuth, async (req, res) => {
  res.json({ user: req.user });
});

router.post('/logout', requireAuth, async (req, res, next) => {
  try {
    await deleteSessionByToken(req.authToken);
    res.json({ message: 'Logout successful.' });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
