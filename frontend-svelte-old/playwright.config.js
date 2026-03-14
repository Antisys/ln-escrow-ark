import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: './tests/e2e',
	timeout: 120_000,
	use: {
		baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173',
		screenshot: 'on',
		trace: 'on-first-retry',
	},
	projects: [
		{ name: 'chromium', use: { browserName: 'chromium' } },
	],
});
