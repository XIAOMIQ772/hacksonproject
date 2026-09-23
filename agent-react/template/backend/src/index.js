const app = require('./app');
const defaultPort = 3000;
const port = Number(process.env.PORT || defaultPort);

app.listen(port, () => {
  console.log(`Backend listening at http://127.0.0.1:${port}`);
});

// Some task test suites target their own fixed port (e.g. E2E_BASE_URL default
// like 127.0.0.1:3301) while the runner health-checks PORT. Listen on both.
const extraPorts = new Set(
  (process.env.EXTRA_LISTEN_PORTS || '3301').split(',').map((p) => Number(p.trim())));
try {
  const e2ePort = Number(new URL(process.env.E2E_BASE_URL || '').port);
  if (e2ePort) extraPorts.add(e2ePort);
} catch { /* E2E_BASE_URL unset or malformed */ }
for (const extra of extraPorts) {
  if (extra && extra !== port) {
    app.listen(extra, () => {
      console.log(`Backend also listening at http://127.0.0.1:${extra}`);
    });
  }
}
