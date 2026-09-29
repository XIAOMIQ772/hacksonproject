const { get, run } = require('../database/db_runtime');

async function findTrainForBooking(trainId) {
  return get(
    `
      SELECT id, train_no, departure_city, destination_city, departure_station, destination_station, departure_time, arrival_time
      FROM trains
      WHERE id = ?
    `,
    [Number(trainId)],
  );
}

async function insertBooking({
  bookingNumber,
  passengerIdNumber,
  passengerName,
  seatType,
  travelDate,
  trainId,
  userId,
}) {
  const result = await run(
    `
      INSERT INTO bookings (
        user_id,
        train_id,
        booking_number,
        travel_date,
        passenger_name,
        passenger_id_number,
        seat_type,
        status
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 'success')
    `,
    [Number(userId), Number(trainId), bookingNumber, travelDate, passengerName, passengerIdNumber, seatType],
  );

  return get(
    `
      SELECT id, booking_number, travel_date, passenger_name, passenger_id_number, seat_type, status
      FROM bookings
      WHERE id = ? AND user_id = ?
    `,
    [result.lastID, Number(userId)],
  );
}

async function getBookingByIdForUser(bookingId, userId) {
  return get(
    `
      SELECT
        bookings.id,
        bookings.booking_number,
        bookings.travel_date,
        bookings.passenger_name,
        bookings.passenger_id_number,
        bookings.seat_type,
        bookings.status,
        trains.train_no,
        trains.departure_station,
        trains.destination_station,
        trains.departure_time,
        trains.arrival_time
      FROM bookings
      JOIN trains ON trains.id = bookings.train_id
      WHERE bookings.id = ? AND bookings.user_id = ?
    `,
    [Number(bookingId), Number(userId)],
  );
}

module.exports = {
  findTrainForBooking,
  getBookingByIdForUser,
  insertBooking,
};
