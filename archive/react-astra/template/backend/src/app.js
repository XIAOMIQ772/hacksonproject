const fs = require('fs');
const path = require('path');
const express = require('express');
const cors = require('cors');

// The database is initialised by src/index.js before listen; the helpers in
// ./database/db_runtime also initialise lazily, so requiring this app is safe in tests.
const app = express();

app.disable('x-powered-by');
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

app.get('/api/health', (req, res) => {
  res.json({ code: 200, message: 'Backend Ready' });
});

// register routes
// register API routes here (before the /api 404 below), e.g.
//   app.use('/api/items', require('./routes/items'));
// Express 5: errors thrown or rejected in async handlers reach the error handler below.

// Unknown API routes -> JSON 404 (keep after every API route).
app.use('/api', (req, res) => {
  res.status(404).json({ error: 'Not found' });
});

// Frontend: static build plus SPA fallback so deep links and reloads work.
const frontendDistPath = path.resolve(__dirname, '../../frontend/dist');
const frontendIndexPath = path.join(frontendDistPath, 'index.html');

app.use(express.static(frontendDistPath));

app.get(/^(?!\/api(?:\/|$)).*/, (req, res) => {
  if (!fs.existsSync(frontendIndexPath)) {
    res
      .status(503)
      .type('html')
      .send('<!doctype html><title>Frontend build missing</title>'
        + '<h1>Frontend build missing</h1>'
        + '<p>Run <code>npm run build</code> in <code>frontend</code>, then reload.</p>');
    return;
  }
  res.sendFile(frontendIndexPath);
});

// Final error handler (keep last): JSON { error } with err.status (default 500).
app.use((err, req, res, next) => {
  if (res.headersSent) {
    next(err);
    return;
  }
  const status = Number(err && (err.status || err.statusCode));
  const code = Number.isInteger(status) && status >= 400 && status < 600 ? status : 500;
  if (code >= 500) {
    console.error(err);
  }
  const message = (err && err.message) || 'Internal Server Error';
  res.status(code).json({ error: message });
});

module.exports = app;
