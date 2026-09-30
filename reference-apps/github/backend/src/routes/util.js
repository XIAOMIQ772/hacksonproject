const { HttpError } = require('../lib');

// Wraps an async handler: HttpError -> JSON {error, fields}; anything else -> 500 JSON.
const h = (fn) => async (req, res) => {
  try {
    const out = await fn(req, res);
    if (!res.headersSent) res.json(out ?? { ok: true });
  } catch (err) {
    if (err instanceof HttpError) {
      res.locals.errorMessage = err.message;
      res.status(err.status).json({ error: err.message, fields: err.fields || {} });
    } else {
      console.error(err);
      res.status(500).json({ error: 'Something went wrong' });
    }
  }
};

module.exports = { h };
