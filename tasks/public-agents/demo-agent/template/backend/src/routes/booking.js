const express = require('express');
const { requireAuth } = require('../middleware/auth');
const {
  createBookingRecord,
  loadBookingOrder,
  loadBookingOptions,
} = require('../services/booking_service');

const router = express.Router();

router.use(requireAuth);

router.get('/options', async (req, res, next) => {
  try {
    const payload = await loadBookingOptions({
      userId: req.user.id,
      trainId: req.query.trainId,
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

router.post('/orders', async (req, res, next) => {
  try {
    const payload = await createBookingRecord({
      userId: req.user.id,
      trainId: req.body.trainId,
      travelDate: req.body.travelDate,
      passengerName: req.body.passengerName,
      passengerIdNumber: req.body.passengerIdNumber,
      seatType: req.body.seatType,
    });
    res.status(201).json(payload);
  } catch (error) {
    if (error && error.status) {
      res.status(error.status).json({ message: error.message });
      return;
    }
    next(error);
  }
});

router.get('/orders/:bookingId', async (req, res, next) => {
  try {
    const payload = await loadBookingOrder({
      userId: req.user.id,
      bookingId: req.params.bookingId,
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
