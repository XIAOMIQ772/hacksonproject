const { closeDb } = require('./init_db');
const { withTransaction } = require('./db_runtime');
const { hashPassword } = require('../utils/security');

const STATIONS = [
  ['BJP', 'Beijing', 'Beijing(北京)'],
  ['SHH', 'Shanghai', 'Shanghai(上海)'],
  ['NJH', 'Nanjing', 'Nanjing(南京)'],
  ['HZH', 'Hangzhou', 'Hangzhou(杭州)'],
  ['TJP', 'Tianjin', 'Tianjin(天津)'],
];

const TRAINS = [
  ['G101', 'Beijing', 'Shanghai', 'Beijing(北京)', 'Shanghai(上海)', '07:00', '12:38'],
  ['G205', 'Beijing', 'Shanghai', 'Beijing(北京)', 'Shanghai Hongqiao(上海虹桥)', '09:15', '14:45'],
  ['G312', 'Shanghai', 'Nanjing', 'Shanghai(上海)', 'Nanjing(南京)', '08:20', '10:05'],
  ['D520', 'Nanjing', 'Hangzhou', 'Nanjing(南京)', 'Hangzhou(杭州)', '11:30', '13:25'],
  ['G561', 'Beijing', 'Tianjin', 'Beijing South(北京南)', 'Tianjin(天津)', '19:10', '19:45'],
];

async function seedDatabase() {
  return withTransaction(async ({ run, get, all, exec }) => {
    void get;
    void all;
    void exec;

    await run(
      `
        INSERT OR IGNORE INTO users (username, email, password_hash)
        VALUES (?, ?, ?)
      `,
      ['demo_user', 'demo@example.com', hashPassword('Password123')],
    );
    await run(
      `
        INSERT OR IGNORE INTO users (username, email, password_hash)
        VALUES (?, ?, ?)
      `,
      ['traveler', 'traveler@example.com', hashPassword('Travel123')],
    );

    for (const station of STATIONS) {
      await run(
        `
          INSERT OR IGNORE INTO stations (code, city_name, display_name)
          VALUES (?, ?, ?)
        `,
        station,
      );
    }

    for (const train of TRAINS) {
      await run(
        `
          INSERT OR IGNORE INTO trains (
            train_no,
            departure_city,
            destination_city,
            departure_station,
            destination_station,
            departure_time,
            arrival_time
          ) VALUES (?, ?, ?, ?, ?, ?, ?)
        `,
        train,
      );
    }
  });
}

if (require.main === module) {
  seedDatabase()
    .then(() => closeDb())
    .catch((error) => {
      console.error('Database seed failed:', error);
      process.exitCode = 1;
    });
}

module.exports = seedDatabase;
module.exports.seedDatabase = seedDatabase;
module.exports.seed = seedDatabase;
