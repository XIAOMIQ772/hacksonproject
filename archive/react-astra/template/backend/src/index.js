const { initializeDatabase, closeDb } = require('./database/init_db');
const seedDatabase = require('./database/seed_db');

const defaultPort = 3000;
const port = Number(process.env.PORT || defaultPort);

// Keep this order: schema -> idempotent seed -> accept requests.
async function start() {
  await initializeDatabase();
  await seedDatabase();
  const app = require('./app');
  return new Promise((resolve, reject) => {
    const server = app.listen(port, (error) => {
      if (error) {
        reject(error);
        return;
      }
      console.log(`Backend listening at http://127.0.0.1:${port}`);
      resolve(server);
    });
  });
}

if (require.main === module) {
  let started = false;

  // A stray rejection or callback exception must not take the server down once it is up.
  process.on('unhandledRejection', (reason) => {
    console.error('Unhandled promise rejection:', reason);
  });
  process.on('uncaughtException', (error) => {
    console.error('Uncaught exception:', error);
    if (!started) {
      process.exit(1);
    }
  });

  start()
    .then(() => {
      started = true;
    })
    .catch(async (error) => {
      console.error('Application startup failed:', error);
      await closeDb().catch(() => {});
      process.exit(1);
    });
}

module.exports = { start };
