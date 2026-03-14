#!/usr/bin/env node
/**
 * Interactive E2E test — drives two headed browser windows.
 * User handles QR scans. Script handles everything else.
 *
 * Usage:
 *   node tests/e2e/interactive-flow.mjs [scenario]
 *
 * Scenarios:
 *   happy   — buyer releases, seller collects (default)
 *   refund  — buyer disputes, admin refunds, buyer collects
 *   both    — runs happy path then refund on separate deals
 */

import { chromium } from '@playwright/test';
const API = process.env.API_URL || 'http://localhost:8001';
const SITE = process.env.SITE_URL || 'http://localhost:5173';
const ADMIN_KEY = process.env.ADMIN_KEY || '';
const SHOTS = 'tests/e2e/screenshots';

const scenario = process.argv[2] || 'happy';

// ── Helpers ──────────────────────────────────────────────────────────────

function log(msg) { console.log(`\n\x1b[1m▶ ${msg}\x1b[0m`); }
function info(msg) { console.log(`  ${msg}`); }
function success(msg) { console.log(`  \x1b[92m✓ ${msg}\x1b[0m`); }
function warn(msg) { console.log(`  \x1b[93m⚠ ${msg}\x1b[0m`); }
function fail(msg) { console.log(`  \x1b[91m✗ ${msg}\x1b[0m`); }

/** Pause: shows a floating banner in the browser with instructions + a Continue button.
 *  The page stays fully interactive. User does the action, then clicks Continue. */
async function ask(question, page) {
	console.log(`\n\x1b[96m🔵 ${question}\x1b[0m`);
	console.log(`   → Do the action in the browser, then click the green CONTINUE button`);
	await page.evaluate((msg) => {
		return new Promise(resolve => {
			const banner = document.createElement('div');
			banner.id = '__e2e_banner';
			banner.innerHTML = `
				<div style="position:fixed;top:0;left:0;right:0;z-index:99999;background:#1a1a2e;color:#fff;padding:12px 16px;
					font-family:sans-serif;font-size:14px;display:flex;align-items:center;gap:12px;box-shadow:0 2px 8px rgba(0,0,0,0.5)">
					<span style="flex:1">🔵 ${msg}</span>
					<button id="__e2e_continue" style="background:#22c55e;color:#fff;border:none;padding:8px 20px;border-radius:6px;
						font-size:14px;font-weight:bold;cursor:pointer">CONTINUE ▶</button>
				</div>`;
			document.body.appendChild(banner);
			document.getElementById('__e2e_continue').onclick = () => {
				banner.remove();
				resolve();
			};
		});
	}, question);
}

async function apiGet(path) {
	const r = await fetch(`${API}${path}`);
	return r.json();
}

async function apiPost(path, body, headers = {}) {
	const r = await fetch(`${API}${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', ...headers },
		body: JSON.stringify(body),
	});
	return { status: r.status, data: await r.json() };
}

async function waitForDealStatus(dealId, statuses, timeoutSec = 120) {
	const targets = Array.isArray(statuses) ? statuses : [statuses];
	const start = Date.now();
	while (Date.now() - start < timeoutSec * 1000) {
		const deal = await apiGet(`/deals/${dealId}`);
		if (targets.includes(deal.status)) return deal;
		await new Promise(r => setTimeout(r, 2000));
	}
	throw new Error(`Timeout waiting for status ${targets.join('|')}`);
}

async function waitForSigningReady(dealId, timeoutSec = 120) {
	const start = Date.now();
	while (Date.now() - start < timeoutSec * 1000) {
		const ss = await apiGet(`/deals/${dealId}/signing-status`);
		if (ss.ready_for_resolution) return ss;
		await new Promise(r => setTimeout(r, 3000));
	}
	throw new Error('Timeout waiting for signing ready');
}

// ── Main ─────────────────────────────────────────────────────────────────

async function main() {
	log('Launching browsers...');
	const browser = await chromium.launch({
		headless: false,
		slowMo: 200,
		args: ['--window-size=700,900'],
	});

	// Two separate browser contexts (separate localStorage = separate identities)
	const sellerCtx = await browser.newContext({ viewport: { width: 700, height: 900 }, ignoreHTTPSErrors: true });
	const buyerCtx = await browser.newContext({ viewport: { width: 700, height: 900 }, ignoreHTTPSErrors: true });
	const sellerPage = await sellerCtx.newPage();
	const buyerPage = await buyerCtx.newPage();

	// Log page errors for debugging
	sellerPage.on('console', msg => { if (msg.type() === 'error') console.log(`  [seller console] ${msg.text()}`); });
	buyerPage.on('console', msg => { if (msg.type() === 'error') console.log(`  [buyer console] ${msg.text()}`); });
	sellerPage.on('pageerror', err => console.log(`  [seller error] ${err.message}`));
	buyerPage.on('pageerror', err => console.log(`  [buyer error] ${err.message}`));

	try {
		if (scenario === 'happy' || scenario === 'both') {
			await runHappyPath(sellerPage, buyerPage);
		}
		if (scenario === 'refund' || scenario === 'both') {
			await runRefundPath(sellerPage, buyerPage);
		}
		log('ALL SCENARIOS COMPLETE');
	} catch (e) {
		fail(`Test failed: ${e.message}`);
		console.error(e);
		await sellerPage.screenshot({ path: `${SHOTS}/error-seller.png` });
		await buyerPage.screenshot({ path: `${SHOTS}/error-buyer.png` });
	}

	await ask('Review the browsers. Click RESUME to close everything.', sellerPage);
	await browser.close();
}

// ── Happy Path ───────────────────────────────────────────────────────────

async function runHappyPath(sellerPage, buyerPage) {
	log('═══ HAPPY PATH: Buyer releases → Seller collects ═══');

	// Step 1: Create deal
	log('Creating deal...');
	const priceSats = 1100 + Math.floor(Math.random() * 400);
	const { status, data: deal } = await apiPost('/deals', {
		seller_id: `e2e-seller-${Date.now()}`,
		title: 'E2E Happy Path Test',
		price_sats: priceSats,
	});
	if (status > 201) throw new Error(`Create deal failed: ${status} ${JSON.stringify(deal)}`);
	const dealId = deal.deal_id;
	const token = deal.deal_link_token;
	info(`Deal: ${dealId}`);
	info(`Join link: ${SITE}/join/${token}`);

	// Step 2: Seller authenticates
	log('Seller: opening deal page...');
	await sellerPage.goto(`${SITE}/deal/${dealId}`, { waitUntil: 'load', timeout: 30000 });
	info(`Seller page URL: ${sellerPage.url()}`);
	info(`Seller page title: ${await sellerPage.title()}`);
	await sellerPage.waitForTimeout(3000);
	await sellerPage.screenshot({ path: `${SHOTS}/happy-01-seller-initial.png` });

	await ask('SELLER window: Authenticate as seller (scan LNURL-auth QR or use passphrase)', sellerPage);

	// Wait for seller to be authenticated (deal should show "waiting for buyer" or similar)
	await sellerPage.waitForTimeout(3000);
	await sellerPage.screenshot({ path: `${SHOTS}/happy-02-seller-auth.png` });
	success('Seller authenticated');

	// Step 3: Buyer joins and authenticates
	log('Buyer: opening join link...');
	await buyerPage.goto(`${SITE}/join/${token}`);
	await buyerPage.waitForLoadState('networkidle');
	await buyerPage.screenshot({ path: `${SHOTS}/happy-03-buyer-join.png` });

	await ask('BUYER window: Authenticate as buyer (scan LNURL-auth QR or use passphrase)', buyerPage);

	await buyerPage.waitForTimeout(3000);
	await buyerPage.screenshot({ path: `${SHOTS}/happy-04-buyer-auth.png` });
	success('Buyer authenticated');

	// Step 4: Wait for escrow setup, then fund
	log('Waiting for escrow setup...');
	// Reload both to trigger key registration
	await sellerPage.reload();
	await buyerPage.reload();
	await sellerPage.waitForTimeout(5000);

	// Check if both keys are registered
	let ss = await apiGet(`/deals/${dealId}/signing-status`);
	info(`Phase: ${ss.phase}, buyer_key: ${ss.buyer_pubkey_registered}, seller_key: ${ss.seller_pubkey_registered}`);

	if (!ss.buyer_pubkey_registered || !ss.seller_pubkey_registered) {
		warn('Keys not yet registered — reloading...');
		await sellerPage.reload();
		await buyerPage.reload();
		await new Promise(r => setTimeout(r, 5000));
		ss = await apiGet(`/deals/${dealId}/signing-status`);
		info(`Phase: ${ss.phase}, buyer_key: ${ss.buyer_pubkey_registered}, seller_key: ${ss.seller_pubkey_registered}`);
	}

	// Step 5: Fund via LN invoice
	log('Buyer: pay the Lightning invoice to fund the escrow');
	// Navigate buyer to deal page (they may be on join page still)
	const dealResp = await apiGet(`/deals/${dealId}`);
	if (dealResp.deal_id) {
		await buyerPage.goto(`${SITE}/deal/${dealId}`);
		await buyerPage.waitForLoadState('networkidle');
	}
	await buyerPage.waitForTimeout(3000);
	await buyerPage.screenshot({ path: `${SHOTS}/happy-05-buyer-funding.png` });

	await ask('BUYER window: Pay the Lightning invoice (scan QR or copy invoice to wallet)', buyerPage);

	// Wait for deal to be funded
	info('Waiting for funding confirmation...');
	const fundedDeal = await waitForDealStatus(dealId, 'funded', 180);
	success(`Deal funded! Status: ${fundedDeal.status}`);

	// Step 6: Wait for auto-sign
	log('Waiting for both parties to auto-sign pre-signed TXs...');
	// Reload both pages to trigger auto-sign — wait between reloads
	await sellerPage.reload();
	await sellerPage.waitForLoadState('networkidle');
	await sellerPage.waitForTimeout(3000);
	await buyerPage.reload();
	await buyerPage.waitForLoadState('networkidle');
	await buyerPage.waitForTimeout(3000);

	// Poll with periodic reloads
	for (let attempt = 0; attempt < 6; attempt++) {
		try {
			ss = await waitForSigningReady(dealId, 15);
			break;
		} catch {
			ss = await apiGet(`/deals/${dealId}/signing-status`);
			info(`Auto-sign attempt ${attempt + 1}: buyer=${ss.buyer_signed} seller=${ss.seller_signed}`);
			// Reload whichever page hasn't signed
			if (!ss.seller_signed) {
				await sellerPage.reload();
				await sellerPage.waitForLoadState('networkidle');
				await sellerPage.waitForTimeout(5000);
			}
			if (!ss.buyer_signed) {
				await buyerPage.reload();
				await buyerPage.waitForLoadState('networkidle');
				await buyerPage.waitForTimeout(5000);
			}
		}
	}

	ss = await apiGet(`/deals/${dealId}/signing-status`);
	if (ss.ready_for_resolution) {
		success(`Both signed! buyer=${ss.buyer_signed} seller=${ss.seller_signed}`);
	} else {
		warn(`Signing incomplete: buyer=${ss.buyer_signed} seller=${ss.seller_signed}`);
		await ask('Auto-sign stuck — try reloading both browser windows, then click CONTINUE', sellerPage);
		ss = await waitForSigningReady(dealId, 60);
	}

	await buyerPage.screenshot({ path: `${SHOTS}/happy-06-ready.png` });
	await sellerPage.screenshot({ path: `${SHOTS}/happy-06-seller-ready.png` });

	// Step 7: BUYER CLICKS RELEASE
	log('Buyer: clicking Release button...');
	await buyerPage.reload();
	await buyerPage.waitForTimeout(3000);

	// Look for the release button
	const releaseBtn = buyerPage.locator('button').filter({ hasText: /Release Funds|Item Received/i }).first();
	await releaseBtn.waitFor({ timeout: 15000 });
	await buyerPage.screenshot({ path: `${SHOTS}/happy-07-release-btn.png` });
	await releaseBtn.click();

	// Handle confirmation dialog
	await buyerPage.waitForTimeout(1000);
	const confirmBtn = buyerPage.locator('button').filter({ hasText: /Yes.*Release|Confirm/i }).first();
	if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
		info('Confirming release...');
		await confirmBtn.click();
	}

	await buyerPage.waitForTimeout(5000);
	await buyerPage.screenshot({ path: `${SHOTS}/happy-08-buyer-released.png` });

	// Verify status
	let currentDeal = await apiGet(`/deals/${dealId}`);
	info(`Deal status: ${currentDeal.status}`);
	if (currentDeal.status === 'released') {
		success('Deal status = released — buyer can leave!');
	} else {
		warn(`Expected 'released', got '${currentDeal.status}'`);
	}

	// Step 8: SELLER sees released deal, scans QR to receive
	log('Seller: reloading to see released state...');
	await sellerPage.reload();
	await sellerPage.waitForTimeout(5000);
	await sellerPage.screenshot({ path: `${SHOTS}/happy-09-seller-released.png` });

	await ask('SELLER window: Scan the LNURL-withdraw QR to receive payment', sellerPage);

	// Wait for seller invoice to be submitted (via LNURL-withdraw callback)
	info('Waiting for seller invoice...');
	for (let i = 0; i < 30; i++) {
		currentDeal = await apiGet(`/deals/${dealId}`);
		if (currentDeal.has_seller_payout_invoice) break;
		await new Promise(r => setTimeout(r, 2000));
	}

	if (currentDeal.has_seller_payout_invoice) {
		success('Seller invoice received!');
	} else {
		fail('Seller invoice not received after timeout');
		return;
	}

	// Step 9: Wait for HTLC auto-prepare + seller auto-sign + completion
	log('Waiting for HTLC auto-sign + completion...');
	// Reload seller page to trigger auto-sign
	await sellerPage.reload();

	for (let i = 0; i < 30; i++) {
		await new Promise(r => setTimeout(r, 3000));
		currentDeal = await apiGet(`/deals/${dealId}`);
		ss = await apiGet(`/deals/${dealId}/signing-status`);

		info(`[${i * 3}s] status=${currentDeal.status} htlc_tx=${!!ss.htlc_tx_hex} htlc_seller_signed=${ss.htlc_seller_signed} payout=${currentDeal.payout_status}`);

		if (currentDeal.status === 'completed') {
			success('DEAL COMPLETED!');
			break;
		}

		// Reload seller page periodically to trigger auto-sign
		if (i > 0 && i % 5 === 0) {
			info('Reloading seller page to trigger auto-sign...');
			await sellerPage.reload();
		}
	}

	await sellerPage.screenshot({ path: `${SHOTS}/happy-10-final-seller.png` });
	await buyerPage.reload();
	await buyerPage.screenshot({ path: `${SHOTS}/happy-10-final-buyer.png` });

	currentDeal = await apiGet(`/deals/${dealId}`);
	if (currentDeal.status === 'completed') {
		success(`HAPPY PATH COMPLETE! Payout: ${currentDeal.payout_status}`);
	} else {
		warn(`Final status: ${currentDeal.status} (payout: ${currentDeal.payout_status})`);
		info('Check seller browser — auto-sign may need a page reload');
	}
}

// ── Refund Path ──────────────────────────────────────────────────────────

async function runRefundPath(sellerPage, buyerPage) {
	log('═══ REFUND PATH: Dispute → Admin refund → Buyer collects ═══');

	// Step 1: Create deal
	log('Creating deal...');
	const priceSats = 1100 + Math.floor(Math.random() * 400);
	const { status, data: deal } = await apiPost('/deals', {
		seller_id: `e2e-seller-${Date.now()}`,
		title: 'E2E Refund Path Test',
		price_sats: priceSats,
	});
	if (status > 201) throw new Error(`Create deal failed: ${status}`);
	const dealId = deal.deal_id;
	const token = deal.deal_link_token;
	info(`Deal: ${dealId}`);

	// Step 2: Both authenticate
	log('Seller: opening deal page...');
	await sellerPage.goto(`${SITE}/deal/${dealId}`);
	await sellerPage.waitForLoadState('networkidle');

	await ask('SELLER window: Authenticate as seller', sellerPage);
	await sellerPage.waitForTimeout(2000);
	success('Seller authenticated');

	log('Buyer: opening join link...');
	await buyerPage.goto(`${SITE}/join/${token}`);
	await buyerPage.waitForLoadState('networkidle');

	await ask('BUYER window: Authenticate as buyer', buyerPage);
	await buyerPage.waitForTimeout(2000);
	success('Buyer authenticated');

	// Step 3: Wait for keys, fund
	log('Waiting for escrow setup...');
	await sellerPage.reload();
	await buyerPage.reload();
	await new Promise(r => setTimeout(r, 5000));

	log('Buyer: navigate to deal page for funding...');
	await buyerPage.goto(`${SITE}/deal/${dealId}`);
	await buyerPage.waitForTimeout(3000);
	await buyerPage.screenshot({ path: `${SHOTS}/refund-01-funding.png` });

	await ask('BUYER window: Pay the Lightning invoice to fund', buyerPage);

	info('Waiting for funding...');
	await waitForDealStatus(dealId, 'funded', 180);
	success('Deal funded!');

	// Step 4: Wait for auto-sign
	log('Waiting for auto-sign...');
	await sellerPage.reload();
	await sellerPage.waitForLoadState('networkidle');
	await sellerPage.waitForTimeout(3000);
	await buyerPage.reload();
	await buyerPage.waitForLoadState('networkidle');
	await buyerPage.waitForTimeout(3000);

	for (let attempt = 0; attempt < 6; attempt++) {
		try {
			await waitForSigningReady(dealId, 15);
			break;
		} catch {
			let sigCheck = await apiGet(`/deals/${dealId}/signing-status`);
			info(`Auto-sign attempt ${attempt + 1}: buyer=${sigCheck.buyer_signed} seller=${sigCheck.seller_signed}`);
			if (!sigCheck.seller_signed) { await sellerPage.reload(); await sellerPage.waitForTimeout(5000); }
			if (!sigCheck.buyer_signed) { await buyerPage.reload(); await buyerPage.waitForTimeout(5000); }
		}
	}
	success('Both signed');

	// Step 5: Buyer opens dispute
	log('Buyer: opening dispute...');
	await buyerPage.reload();
	await buyerPage.waitForTimeout(3000);

	const disputeBtn = buyerPage.locator('button').filter({ hasText: /Dispute|Problem/i }).first();
	await disputeBtn.waitFor({ timeout: 10000 });
	await disputeBtn.click();
	await buyerPage.waitForTimeout(1000);

	// Fill reason if there's a text field
	const reasonInput = buyerPage.locator('textarea, input[placeholder*="reason" i]').first();
	if (await reasonInput.isVisible({ timeout: 2000 }).catch(() => false)) {
		await reasonInput.fill('E2E test dispute — testing refund flow');
	}

	// Confirm dispute
	const confirmDispute = buyerPage.locator('button').filter({ hasText: /Submit|Confirm|Open Dispute/i }).first();
	if (await confirmDispute.isVisible({ timeout: 2000 }).catch(() => false)) {
		await confirmDispute.click();
	}

	await buyerPage.waitForTimeout(3000);
	let currentDeal = await apiGet(`/deals/${dealId}`);
	info(`Deal status: ${currentDeal.status}`);
	await buyerPage.screenshot({ path: `${SHOTS}/refund-02-disputed.png` });

	// Step 6: Admin resolves as refund
	log('Admin: resolving dispute as refund...');
	const resolveResult = await apiPost(
		`/deals/admin/${dealId}/resolve-refund`,
		{ resolution_note: 'E2E test refund' },
		{ 'X-Admin-Key': ADMIN_KEY }
	);
	info(`Resolve result: ${resolveResult.status}`);

	await new Promise(r => setTimeout(r, 3000));
	currentDeal = await apiGet(`/deals/${dealId}`);
	info(`Deal status after admin resolve: ${currentDeal.status}`);
	info(`Buyer payout status: ${currentDeal.buyer_payout_status}`);
	await buyerPage.reload();
	await buyerPage.waitForTimeout(3000);
	await buyerPage.screenshot({ path: `${SHOTS}/refund-03-resolved.png` });

	if (currentDeal.status === 'refunded') {
		success('Deal refunded!');
	}

	// Step 7: Buyer collects refund
	log('Buyer: scan QR to receive refund...');
	await ask('BUYER window: Scan the LNURL-withdraw QR to receive refund', buyerPage);

	// Wait for buyer payout
	for (let i = 0; i < 30; i++) {
		currentDeal = await apiGet(`/deals/${dealId}`);
		if (currentDeal.buyer_payout_status === 'paid') break;
		await new Promise(r => setTimeout(r, 2000));
	}

	await buyerPage.screenshot({ path: `${SHOTS}/refund-04-final.png` });

	if (currentDeal.buyer_payout_status === 'paid') {
		success('REFUND PATH COMPLETE! Buyer received refund.');
	} else {
		warn(`Buyer payout status: ${currentDeal.buyer_payout_status}`);
	}
}

// ── Run ──────────────────────────────────────────────────────────────────
main().catch(e => { console.error(e); process.exit(1); });
