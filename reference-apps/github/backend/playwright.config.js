const { defineConfig } = require('@playwright/test');

const baseURL = process.env.PLAYWRIGHT_BASE_URL || process.env.ARC_WEB_BASE_URL || 'http://127.0.0.1:3000';

module.exports = defineConfig({
  testDir: './test-e2e',
  testMatch: /.*\.spec\.(js|ts)$/,
  timeout: 30000,
  expect: { timeout: 5000 },
  workers: Number(process.env.PW_WORKERS || 4),
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    permissions: ['clipboard-read', 'clipboard-write'],
  },
});
