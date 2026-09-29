const express = require('express');
const { runTicketSearch, runTrainLookup } = require('../services/search_service');

const router = express.Router();

router.get('/tickets', async (req, res, next) => {
  try {
    const payload = await runTicketSearch(req.query || {});
    res.json(payload);
  } catch (error) {
    if (error && error.status) {
      res.status(error.status).json({ message: error.message });
      return;
    }
    next(error);
  }
});

router.get('/trains/:trainId', async (req, res, next) => {
  try {
    const payload = await runTrainLookup({
      trainId: req.params.trainId,
      date: req.query.date,
    });
    res.json(payload);
  } catch (error) {
    if (error && error.status) {
      res.status(error.status).json({ message: error.message });
      return;
    }
    next(error);
  }
});

module.exports = router;
