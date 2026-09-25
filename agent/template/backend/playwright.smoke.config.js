const { defineConfig } = require('@playwright/test');

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3000';

module.exports = defineConfig({
  testDir: './agent-smoke-tests',
  testMatch: /.*\.spec\.(js|jsx|ts|tsx)$/,
  timeout: 15000,
  expect: {
    timeout: 5000,
  },
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
});
