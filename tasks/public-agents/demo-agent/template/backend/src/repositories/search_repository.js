const { all, get } = require('../database/db_runtime');

async function findTrainsByRoute({ from, to }) {
  return all(
    `
      SELECT id, train_no, departure_city, destination_city, departure_station, destination_station, departure_time, arrival_time
      FROM trains
      WHERE departure_city = ? AND destination_city = ?
      ORDER BY departure_time ASC
    `,
    [from, to],
  );
}

async function findTrainById(trainId) {
  return get(
    `
      SELECT id, train_no, departure_city, destination_city, departure_station, destination_station, departure_time, arrival_time
      FROM trains
      WHERE id = ?
    `,
    [Number(trainId)],
  );
}

module.exports = {
  findTrainById,
  findTrainsByRoute,
};
