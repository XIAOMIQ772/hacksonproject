const { findTrainById, findTrainsByRoute } = require('../repositories/search_repository');

function createHttpError(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function normalizeQuery(query = {}) {
  return {
    from: String(query.from || '').trim(),
    to: String(query.to || '').trim(),
    date: String(query.date || '').trim(),
  };
}

function toTrainCard(train) {
  return {
    id: train.id,
    trainNo: train.train_no,
    departureCity: train.departure_city,
    destinationCity: train.destination_city,
    departureStation: train.departure_station,
    destinationStation: train.destination_station,
    departureTime: train.departure_time,
    arrivalTime: train.arrival_time,
  };
}

async function runTicketSearch(query = {}) {
  const normalized = normalizeQuery(query);

  if (!normalized.from || !normalized.to || !normalized.date) {
    throw createHttpError(400, 'Please enter departure city, destination city, and departure date.');
  }

  const results = await findTrainsByRoute(normalized);

  return {
    search: normalized,
    resultCount: results.length,
    trains: results.map(toTrainCard),
    empty: results.length === 0,
    emptyMessage: `No trains matched the route from ${normalized.from} to ${normalized.to} on ${normalized.date}.`,
  };
}

async function runTrainLookup({ trainId, date }) {
  const train = await findTrainById(trainId);
  if (!train) {
    throw createHttpError(404, 'Train not found.');
  }

  return {
    date: String(date || '').trim(),
    train: toTrainCard(train),
  };
}

module.exports = {
  normalizeQuery,
  runTicketSearch,
  runTrainLookup,
};
