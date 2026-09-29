const {
  findTrainForBooking,
  getBookingByIdForUser,
  insertBooking,
} = require('../repositories/booking_repository');
const { buildBookingNumber } = require('../utils/security');

const ALLOWED_SEAT_TYPES = new Set(['Second Class', 'First Class', 'Business Class']);

function createHttpError(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function toTrainSummary(train, travelDate) {
  return {
    id: train.id,
    trainNo: train.train_no,
    departureDate: travelDate,
    departureStation: train.departure_station,
    destinationStation: train.destination_station,
    departureTime: train.departure_time,
    arrivalTime: train.arrival_time,
  };
}

async function loadBookingOptions({ userId, trainId, date }) {
  void userId;
  if (!trainId || !date) {
    throw createHttpError(400, 'Missing train information.');
  }

  const train = await findTrainForBooking(trainId);
  if (!train) {
    throw createHttpError(404, 'Train not found.');
  }

  return {
    train: toTrainSummary(train, String(date || '').trim()),
    passengerDefaults: {
      passengerName: '',
      passengerIdNumber: '',
      seatType: 'Second Class',
    },
  };
}

async function createBookingRecord({
  userId,
  trainId,
  travelDate,
  passengerName,
  passengerIdNumber,
  seatType,
}) {
  const normalizedTravelDate = String(travelDate || '').trim();
  const normalizedPassengerName = String(passengerName || '').trim();
  const normalizedPassengerIdNumber = String(passengerIdNumber || '').trim();
  const normalizedSeatType = String(seatType || '').trim();

  if (!trainId || !normalizedTravelDate || !normalizedPassengerName || !normalizedPassengerIdNumber || !normalizedSeatType) {
    throw createHttpError(400, 'Please provide passenger name, ID number, seat type, and travel date.');
  }
  if (normalizedPassengerName.length < 2) {
    throw createHttpError(400, 'Passenger name must contain at least 2 characters.');
  }
  if (normalizedPassengerIdNumber.length < 6) {
    throw createHttpError(400, 'Passenger ID number must contain at least 6 characters.');
  }
  if (!ALLOWED_SEAT_TYPES.has(normalizedSeatType)) {
    throw createHttpError(400, 'Please choose a supported seat type.');
  }

  const train = await findTrainForBooking(trainId);
  if (!train) {
    throw createHttpError(404, 'Train not found.');
  }

  const booking = await insertBooking({
    userId,
    trainId,
    bookingNumber: buildBookingNumber(),
    travelDate: normalizedTravelDate,
    passengerName: normalizedPassengerName,
    passengerIdNumber: normalizedPassengerIdNumber,
    seatType: normalizedSeatType,
  });

  return {
    message: 'Booking created successfully.',
    booking: {
      id: booking.id,
      bookingNumber: booking.booking_number,
      travelDate: booking.travel_date,
      passengerName: booking.passenger_name,
      passengerIdNumber: booking.passenger_id_number,
      seatType: booking.seat_type,
      status: booking.status,
    },
  };
}

async function loadBookingOrder({ userId, bookingId }) {
  const booking = await getBookingByIdForUser(bookingId, userId);
  if (!booking) {
    throw createHttpError(404, 'Booking not found.');
  }

  return {
    booking: {
      id: booking.id,
      bookingNumber: booking.booking_number,
      travelDate: booking.travel_date,
      passengerName: booking.passenger_name,
      passengerIdNumber: booking.passenger_id_number,
      seatType: booking.seat_type,
      status: booking.status,
      train: {
        trainNo: booking.train_no,
        departureStation: booking.departure_station,
        destinationStation: booking.destination_station,
        departureTime: booking.departure_time,
        arrivalTime: booking.arrival_time,
      },
    },
  };
}

module.exports = {
  createBookingRecord,
  loadBookingOrder,
  loadBookingOptions,
};
