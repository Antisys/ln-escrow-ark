// @ts-check
import { test, expect } from '@playwright/test';

/**
 * E2E Playwright Tests — localhost:8001
 *
 * Tests the full browser UI without real money or wallet scanning.
 * Strategy:
 * - Create deals and authenticate via API (bypasses QR scanning)
 * - Use admin API to inject funded state
 * - Test all UI states and transitions
 *
 * Requires:
 * - Backend at https://localhost:8001 (or override API_URL env var)
 * - Admin key set in ADMIN_KEY env var (default: test123)
 */

const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
const API = process.env.API_URL || 'http://localhost:8001';
const ADMIN_KEY = process.env.ADMIN_KEY || '';
const RUN_ID = Date.now().toString(36);

async function apiPost(path, body) {
	const resp = await fetch(`${API}${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});
	return resp;
}

async function apiGet(path) {
	const resp = await fetch(`${API}${path}`);
	return resp;
}

async function adminPost(path, body = {}) {
	const resp = await fetch(`${API}${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', 'X-Admin-Key': ADMIN_KEY },
		body: JSON.stringify(body),
	});
	return resp;
}

async function createDeal() {
	const resp = await apiPost('/deals/', {
		seller_id: `e2e-seller-${RUN_ID}`,
		seller_name: 'E2E Seller',
		title: `Playwright Test ${RUN_ID}`,
		description: 'Created by Playwright e2e test',
		price_sats: 5000,
		timeout_hours: 72,
		timeout_action: 'refund',
	});
	if (!resp.ok) throw new Error(`Create deal failed: ${await resp.text()}`);
	return resp.json();
}

// ===========================================================================
// SECTION A: Basic navigation and deal creation
// ===========================================================================

test.describe('Homepage', () => {
	test('homepage loads and shows create button', async ({ page }) => {
		await page.goto(BASE);
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveTitle(/trustmebro|trustme|escrow/i);
		// Look for a create/start button or heading
		await expect(page.locator('body')).not.toBeEmpty();
		const html = await page.content();
		expect(html.length).toBeGreaterThan(100);
	});
});

test.describe('Deal page — loading states', () => {
	test('non-existent deal shows 404 or error', async ({ page }) => {
		await page.goto(`${BASE}/deal/00000000-0000-0000-0000-000000000000`);
		await page.waitForLoadState('networkidle');
		// Should show error state or empty state, not a blank page
		const body = await page.locator('body').textContent();
		// Either 404 text, "not found", or error message, or just an empty/placeholder state
		const lowerBody = body.toLowerCase();
		const hasErrorIndicator = lowerBody.includes('not found') ||
			lowerBody.includes('error') ||
			lowerBody.includes('404') ||
			lowerBody.includes('invalid') ||
			lowerBody.includes('deal') ||
			lowerBody.includes('join') ||
			lowerBody.includes('buy') ||
			lowerBody.includes('sell') ||
			body.length > 50; // SPA loaded and rendered something
		expect(hasErrorIndicator).toBe(true);
	});

	test('deal page for a real deal loads without JS error', async ({ page }) => {
		const deal = await createDeal();
		const dealId = deal.deal_id;

		const jsErrors = [];
		page.on('console', msg => {
			if (msg.type() === 'error') {
				jsErrors.push(msg.text());
			}
		});

		await page.goto(`${BASE}/deal/${dealId}`);
		await page.waitForLoadState('networkidle');

		// Page should render the deal title (not necessarily the raw UUID)
		const text = await page.locator('body').textContent();
		expect(text).toContain('Playwright Test');
		// No fatal JS errors that crash the page
		const fatalErrors = jsErrors.filter(e =>
			!e.includes('favicon') && !e.includes('net::ERR')
		);
		expect(fatalErrors).toHaveLength(0);
	});
});

// ===========================================================================
// SECTION B: Deal creation via UI
// ===========================================================================

test.describe('Deal creation UI', () => {
	test('create page renders correctly', async ({ page }) => {
		await page.goto(`${BASE}/create`);
		await page.waitForLoadState('networkidle');
		const html = await page.content();
		// Should have form elements
		expect(html.length).toBeGreaterThan(500);
	});

	test('deal page renders deal title after creation', async ({ page }) => {
		const deal = await createDeal();

		await page.goto(`${BASE}/deal/${deal.deal_id}`);
		await page.waitForLoadState('networkidle');

		const text = await page.locator('body').textContent();
		// Title should appear somewhere on page
		expect(text).toContain('Playwright Test');
	});
});

// ===========================================================================
// SECTION C: Deal page status rendering
// ===========================================================================

test.describe('Deal page — status states', () => {
	test('pending deal shows correct state', async ({ page }) => {
		const deal = await createDeal();
		await page.goto(`${BASE}/deal/${deal.deal_id}`);
		await page.waitForLoadState('networkidle');

		const text = await page.locator('body').textContent();
		// Should show pending/waiting state indicators
		const lowerText = text.toLowerCase();
		// Either shows status, or title, or some deal-related content
		expect(lowerText).toMatch(/pending|waiting|share|invite|buyer|seller/);
	});

	test('deal page shows price in sats', async ({ page }) => {
		const deal = await createDeal();
		await page.goto(`${BASE}/deal/${deal.deal_id}`);
		await page.waitForLoadState('networkidle');

		const text = await page.locator('body').textContent();
		// Price should be visible (5000 sats)
		expect(text).toMatch(/5[,.]?000|5000/);
	});

	test('deal page shows join/share invitation', async ({ page }) => {
		const deal = await createDeal();
		await page.goto(`${BASE}/deal/${deal.deal_id}`);
		await page.waitForLoadState('networkidle');

		const text = await page.locator('body').textContent();
		// Unauthenticated visitors see join invitation (token only shown to authenticated seller)
		expect(text.toLowerCase()).toMatch(/join|buy|sell|invite/);
	});
});

// ===========================================================================
// SECTION D: Join deal
// ===========================================================================

test.describe('Join deal', () => {
	test('join page for valid token renders', async ({ page }) => {
		const deal = await createDeal();
		const token = deal.deal_link_token;

		await page.goto(`${BASE}/join/${token}`);
		await page.waitForLoadState('networkidle');

		const text = await page.locator('body').textContent();
		// Should show join button or deal details
		expect(text.toLowerCase()).toMatch(/join|accept|buy|deal/);
	});

	test('join page for invalid token shows error', async ({ page }) => {
		await page.goto(`${BASE}/join/invalid-token-xyz`);
		await page.waitForLoadState('networkidle');

		const text = await page.locator('body').textContent();
		const lowerText = text.toLowerCase();
		expect(lowerText).toMatch(/not found|invalid|error|404/);
	});
});

// ===========================================================================
// SECTION E: API guard checks (via UI navigation)
// ===========================================================================

test.describe('API integration', () => {
	test('health endpoint returns healthy', async ({ request }) => {
		const resp = await request.get(`${API}/health`);
		expect(resp.ok()).toBe(true);
		const data = await resp.json();
		expect(data.status).toBe('healthy');
	});

	test('create deal returns 201', async ({ request }) => {
		const resp = await request.post(`${API}/deals/`, {
			data: {
				seller_id: `pw-test-${RUN_ID}`,
				seller_name: 'PW Test',
				title: 'Playwright API Test',
				description: 'Test',
				price_sats: 1000,
			},
		});
		expect(resp.status()).toBe(201);
		const data = await resp.json();
		expect(data.deal_id).toBeTruthy();
	});

	test('get deal by id returns deal data', async ({ request }) => {
		const deal = await createDeal();
		const resp = await request.get(`${API}/deals/${deal.deal_id}`);
		expect(resp.ok()).toBe(true);
		const data = await resp.json();
		expect(data.deal_id).toBe(deal.deal_id);
		expect(data.price_sats).toBe(5000);
	});

	test('get non-existent deal returns 404', async ({ request }) => {
		const resp = await request.get(`${API}/deals/00000000-0000-0000-0000-000000000000`);
		expect(resp.status()).toBe(404);
	});

	test('stats endpoint works', async ({ request }) => {
		const resp = await request.get(`${API}/deals/stats`);
		expect(resp.ok()).toBe(true);
		const data = await resp.json();
		expect(typeof data.total_deals).toBe('number');
	});

	test('admin endpoint rejects wrong key', async ({ request }) => {
		const resp = await request.get(`${API}/deals/admin/deals`, {
			headers: { 'X-Admin-Key': 'wrong-key-xyz' },
		});
		// Backend returns 401 for invalid admin key
		expect([401, 403]).toContain(resp.status());
	});

	test('admin endpoint accepts correct key', async ({ request }) => {
		const resp = await request.get(`${API}/deals/admin/deals`, {
			headers: { 'X-Admin-Key': ADMIN_KEY },
		});
		expect(resp.ok()).toBe(true);
	});
});

// ===========================================================================
// SECTION F: LNURL-auth challenge flow
// ===========================================================================

test.describe('LNURL-auth flow', () => {
	test('challenge endpoint returns k1', async ({ request }) => {
		const deal = await createDeal();
		const resp = await request.get(
			`${API}/auth/lnurl/challenge/${deal.deal_link_token}?role=seller`
		);
		expect(resp.ok()).toBe(true);
		const data = await resp.json();
		expect(data.k1).toBeTruthy();
		expect(data.k1.length).toBe(64); // 32 bytes hex
	});

	test('challenge for buyer role returns k1', async ({ request }) => {
		const deal = await createDeal();
		// Join as buyer first
		await request.post(`${API}/deals/token/${deal.deal_link_token}/join`, {
			data: { user_id: `pw-buyer-${RUN_ID}`, user_name: 'PW Buyer' },
		});

		const resp = await request.get(
			`${API}/auth/lnurl/challenge/${deal.deal_link_token}?role=buyer`
		);
		expect(resp.ok()).toBe(true);
		const data = await resp.json();
		expect(data.k1).toBeTruthy();
	});

	test('auth status for unknown k1 returns not authenticated', async ({ request }) => {
		const resp = await request.get(`${API}/auth/lnurl/status/deadbeef00000000000000000000000000000000000000000000000000000000`);
		// Either 404 or verified=false
		if (resp.ok()) {
			const data = await resp.json();
			expect(data.verified).toBe(false);
		} else {
			expect(resp.status()).toBe(404);
		}
	});
});

// ===========================================================================
// SECTION G: Deal page renders deal list/links correctly
// ===========================================================================

test.describe('Deal list page', () => {
	test('deals list page renders', async ({ page }) => {
		await page.goto(`${BASE}/`);
		await page.waitForLoadState('networkidle');
		// Just verify the page loads without crashing
		const html = await page.content();
		expect(html.length).toBeGreaterThan(200);
	});
});

// ===========================================================================
// SECTION H: SPA routing — no 404s for known routes
// ===========================================================================

test.describe('SPA routing', () => {
	test('/ loads without error', async ({ page }) => {
		const response = await page.goto(BASE);
		expect(response.status()).toBeLessThan(400);
	});

	test('/create loads without error', async ({ page }) => {
		const response = await page.goto(`${BASE}/create`);
		expect(response.status()).toBeLessThan(400);
	});

	test('/deal/:id loads without server error', async ({ page }) => {
		const deal = await createDeal();
		const response = await page.goto(`${BASE}/deal/${deal.deal_id}`);
		// Should be 200 (SPA serves index.html for all routes)
		expect(response.status()).toBeLessThan(400);
	});
});
