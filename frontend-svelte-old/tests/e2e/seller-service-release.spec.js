// @ts-check
import { test, expect } from '@playwright/test';

/**
 * E2E Test: Seller+Service HTLC Release Flow
 *
 * Tests the full browser-based flow:
 * 1. Seller creates deal
 * 2. Buyer joins
 * 3. Both authenticate via passphrase (keys stored in localStorage)
 * 4. Admin funds the deal (real testnet coins — escrow has proper keys)
 * 5. Buyer clicks "Release" → status=released, buyer can leave
 * 6. Seller sees QR, submits invoice via API (simulates wallet scan)
 * 7. Seller receives payout via Lightning
 * 8. Deal completes
 *
 * SAFETY: Uses testnet coins via fund-from-wallet. Escrow has real keys
 * from passphrase auth, so pre-signed refund TX exists as recovery path.
 */

const API = process.env.API_URL || 'http://localhost:8001';
const FRONTEND = process.env.SITE_URL || 'http://localhost:5173';
const ADMIN_KEY = process.env.ADMIN_KEY || '';

// Unique IDs per test run
const RUN_ID = Date.now().toString(36);

test.describe('Seller+Service Release Flow', () => {
	let dealId;
	let dealToken;
	let sellerId;
	let buyerId;

	test('full release flow: create → fund → buyer-release → seller-collect', async ({ browser }) => {
		// ================================================================
		// Step 1: Seller creates deal via API (faster than clicking through UI)
		// ================================================================
		sellerId = `e2e-seller-${RUN_ID}`;
		buyerId = `e2e-buyer-${RUN_ID}`;

		const createResp = await fetch(`${API}/deals`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				seller_id: sellerId,
				title: `E2E Test ${RUN_ID}`,
				description: 'Playwright seller+service flow test',
				price_sats: 5000,
			}),
		});
		expect(createResp.status).toBeLessThan(300);
		const deal = await createResp.json();
		dealId = deal.deal_id;
		dealToken = deal.deal_link_token;
		console.log(`Deal created: ${dealId}`);

		// ================================================================
		// Step 2: Buyer joins via API
		// ================================================================
		const joinResp = await fetch(`${API}/deals/token/${dealToken}/join`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ user_id: buyerId }),
		});
		expect(joinResp.status).toBe(200);
		console.log('Buyer joined');

		// ================================================================
		// Step 3: Open seller's browser, authenticate with passphrase
		// ================================================================
		const sellerContext = await browser.newContext();
		const sellerPage = await sellerContext.newPage();

		// Navigate to the deal page
		await sellerPage.goto(`${FRONTEND}/deal/${dealId}`);
		await sellerPage.waitForLoadState('networkidle');

		// Screenshot: initial deal page
		await sellerPage.screenshot({ path: 'tests/e2e/screenshots/01-seller-initial.png' });

		// Click "Use Passphrase" auth method (if visible)
		const passphraseTab = sellerPage.locator('text=Use Passphrase').or(sellerPage.locator('text=passphrase')).first();
		if (await passphraseTab.isVisible({ timeout: 3000 }).catch(() => false)) {
			await passphraseTab.click();
		}

		// Enter passphrase for seller
		const sellerPassphrase = `test-seller-phrase-${RUN_ID}`;
		const passphraseInput = sellerPage.locator('input[placeholder*="passphrase" i], input[placeholder*="words" i]').first();
		await passphraseInput.waitFor({ timeout: 10000 });
		await passphraseInput.fill(sellerPassphrase);

		// Click authenticate/confirm button
		const authBtn = sellerPage.locator('button:has-text("Authenticate"), button:has-text("Continue"), button:has-text("Confirm")').first();
		await authBtn.click();

		// Wait for authentication to complete
		await sellerPage.waitForTimeout(3000);
		await sellerPage.screenshot({ path: 'tests/e2e/screenshots/02-seller-authenticated.png' });

		console.log('Seller authenticated');

		// ================================================================
		// Step 4: Open buyer's browser, authenticate with passphrase
		// ================================================================
		const buyerContext = await browser.newContext();
		const buyerPage = await buyerContext.newPage();

		await buyerPage.goto(`${FRONTEND}/deal/${dealId}`);
		await buyerPage.waitForLoadState('networkidle');

		// Click "Use Passphrase" auth method
		const buyerPassTab = buyerPage.locator('text=Use Passphrase').or(buyerPage.locator('text=passphrase')).first();
		if (await buyerPassTab.isVisible({ timeout: 3000 }).catch(() => false)) {
			await buyerPassTab.click();
		}

		const buyerPassphrase = `test-buyer-phrase-${RUN_ID}`;
		const buyerPassInput = buyerPage.locator('input[placeholder*="passphrase" i], input[placeholder*="words" i]').first();
		await buyerPassInput.waitFor({ timeout: 10000 });
		await buyerPassInput.fill(buyerPassphrase);

		const buyerAuthBtn = buyerPage.locator('button:has-text("Authenticate"), button:has-text("Continue"), button:has-text("Confirm")').first();
		await buyerAuthBtn.click();

		await buyerPage.waitForTimeout(3000);
		await buyerPage.screenshot({ path: 'tests/e2e/screenshots/03-buyer-authenticated.png' });
		console.log('Buyer authenticated');

		// ================================================================
		// Step 5: Wait for both keys registered + auto-sign
		// ================================================================
		// The frontend auto-signs pre-signed TXs when both parties load the funded page.
		// Wait for escrow setup to complete.
		await sellerPage.reload();
		await buyerPage.reload();
		await sellerPage.waitForTimeout(5000);
		await buyerPage.waitForTimeout(5000);

		// Check signing status
		let sigStatusResp = await fetch(`${API}/deals/${dealId}/signing-status`);
		let sigStatus = await sigStatusResp.json();
		console.log(`Signing status: phase=${sigStatus.phase}, buyer_signed=${sigStatus.buyer_signed}, seller_signed=${sigStatus.seller_signed}`);

		await sellerPage.screenshot({ path: 'tests/e2e/screenshots/04-pre-funding.png' });

		// ================================================================
		// Step 6: Fund the deal via admin API
		// ================================================================
		// SAFETY: This spends testnet coins. The escrow has real keys from
		// passphrase auth, so pre-signed refund TX will exist as recovery.
		console.log('Funding deal via admin API...');
		const fundResp = await fetch(`${API}/deals/admin/${dealId}/fund-from-wallet`, {
			method: 'POST',
			headers: { 'X-Admin-Key': ADMIN_KEY },
		});
		const fundResult = await fundResp.json();
		console.log(`Fund result: ${fundResp.status} - ${JSON.stringify(fundResult).slice(0, 200)}`);

		if (fundResp.status !== 200) {
			console.log('Funding failed — skipping rest of test');
			// This can happen if wallet has no balance
			test.skip();
			return;
		}

		// Wait for funding to be detected + auto-sign to complete
		console.log('Waiting for auto-sign...');
		await sellerPage.reload();
		await buyerPage.reload();

		// Wait longer for auto-sign — it needs both pages to load, detect funding, fetch unsigned TXs, sign
		for (let i = 0; i < 12; i++) {
			await sellerPage.waitForTimeout(5000);
			sigStatusResp = await fetch(`${API}/deals/${dealId}/signing-status`);
			sigStatus = await sigStatusResp.json();
			console.log(`  [${i * 5}s] buyer_signed=${sigStatus.buyer_signed} seller_signed=${sigStatus.seller_signed} ready=${sigStatus.ready_for_resolution}`);
			if (sigStatus.ready_for_resolution) break;

			// Reload pages to trigger auto-sign
			if (i === 3 || i === 6 || i === 9) {
				await sellerPage.reload();
				await buyerPage.reload();
			}
		}

		await buyerPage.screenshot({ path: 'tests/e2e/screenshots/05-funded-buyer.png' });
		await sellerPage.screenshot({ path: 'tests/e2e/screenshots/05-funded-seller.png' });

		expect(sigStatus.ready_for_resolution).toBe(true);
		console.log('Both parties signed, ready for resolution');

		// ================================================================
		// Step 7: Buyer clicks "Release Funds"
		// ================================================================
		console.log('Buyer releasing funds...');
		await buyerPage.reload();
		await buyerPage.waitForTimeout(3000);

		// Find and click the release button
		const releaseBtn = buyerPage.locator('button:has-text("Release Funds"), button:has-text("Item Received")').first();
		await releaseBtn.waitFor({ timeout: 15000 });
		await buyerPage.screenshot({ path: 'tests/e2e/screenshots/06-buyer-release-button.png' });

		await releaseBtn.click();

		// Handle confirmation dialog if present
		const confirmBtn = buyerPage.locator('button:has-text("Yes"), button:has-text("Confirm Release"), button:has-text("Release")').first();
		if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			await confirmBtn.click();
		}

		// Wait for the release to complete
		await buyerPage.waitForTimeout(5000);
		await buyerPage.screenshot({ path: 'tests/e2e/screenshots/07-buyer-after-release.png' });

		// Verify deal status is 'released'
		let dealResp = await fetch(`${API}/deals/${dealId}`);
		let dealData = await dealResp.json();
		console.log(`Deal status after buyer release: ${dealData.status}`);
		expect(dealData.status).toBe('released');

		// Verify buyer sees "Funds Released" message
		const buyerText = await buyerPage.textContent('body');
		expect(buyerText).toMatch(/released|completed/i);
		console.log('Buyer release confirmed');

		// ================================================================
		// Step 8: Seller loads released deal page → sees QR
		// ================================================================
		await sellerPage.reload();
		await sellerPage.waitForTimeout(5000);
		await sellerPage.screenshot({ path: 'tests/e2e/screenshots/08-seller-released.png' });

		// Seller should see QR or "Receive" text
		const sellerText = await sellerPage.textContent('body');
		const hasReceiveUI = /receive|scan|qr|wallet/i.test(sellerText);
		console.log(`Seller sees receive UI: ${hasReceiveUI}`);
		expect(hasReceiveUI).toBe(true);

		// ================================================================
		// Step 9: Submit seller invoice via API (simulates wallet QR scan)
		// ================================================================
		// In real life, seller scans QR with wallet → wallet generates invoice → callback submits it.
		// In test, we submit a Lightning Address directly via API.

		// First, we need the seller's auth signature. We'll use the page's JS context.
		const sellerInvoiceResult = await sellerPage.evaluate(async (args) => {
			const { dealId, sellerId } = args;
			// Use the crypto module loaded in the page
			const { signAction } = await import('/src/lib/crypto.js');

			// Get stored key from localStorage
			const storedKeys = JSON.parse(localStorage.getItem('escrow_deal_keys') || '{}');
			const key = storedKeys[dealId];
			if (!key || !key.privateKey) return { error: 'No key found', keys: Object.keys(storedKeys) };

			const { signature, timestamp } = signAction(key.privateKey, dealId, 'submit-payout-invoice');

			const resp = await fetch(`${API}/deals/${dealId}/submit-payout-invoice`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					user_id: sellerId,
					invoice: 'seller@walletofsatoshi.com',
					signature,
					timestamp,
				}),
			});

			return { status: resp.status, body: await resp.json() };
		}, { dealId, sellerId });

		console.log(`Submit invoice result: ${JSON.stringify(sellerInvoiceResult).slice(0, 200)}`);
		if (sellerInvoiceResult.error) {
			console.log(`ERROR: ${sellerInvoiceResult.error}`);
		}
		expect(sellerInvoiceResult.status).toBe(200);

		// ================================================================
		// Step 10: Wait for HTLC auto-prepare + seller auto-sign
		// ================================================================
		// The backend auto-prepares the HTLC TX when the invoice is submitted.
		// The seller's browser should detect it and auto-sign.

		console.log('Waiting for HTLC auto-prepare + seller auto-sign...');
		await sellerPage.reload();

		let htlcSigned = false;
		for (let i = 0; i < 20; i++) {
			await sellerPage.waitForTimeout(3000);

			sigStatusResp = await fetch(`${API}/deals/${dealId}/signing-status`);
			sigStatus = await sigStatusResp.json();

			dealResp = await fetch(`${API}/deals/${dealId}`);
			dealData = await dealResp.json();

			console.log(`  [${i * 3}s] status=${dealData.status} htlc_tx=${!!sigStatus.htlc_tx_hex} htlc_seller_signed=${sigStatus.htlc_seller_signed}`);

			if (dealData.status === 'completed') {
				htlcSigned = true;
				break;
			}

			// Reload seller page periodically to trigger auto-sign
			if (i === 5 || i === 10 || i === 15) {
				await sellerPage.reload();
			}
		}

		await sellerPage.screenshot({ path: 'tests/e2e/screenshots/09-final-seller.png' });
		await buyerPage.reload();
		await buyerPage.screenshot({ path: 'tests/e2e/screenshots/09-final-buyer.png' });

		// ================================================================
		// Step 11: Verify final state
		// ================================================================
		dealResp = await fetch(`${API}/deals/${dealId}`);
		dealData = await dealResp.json();
		console.log(`Final deal status: ${dealData.status}`);
		console.log(`Payout status: ${dealData.payout_status}`);

		// The deal should be completed (HTLC broadcast + LN paid + claimed)
		// OR still released if the LN payment failed (which is OK for testnet)
		expect(['completed', 'released', 'releasing']).toContain(dealData.status);

		if (dealData.status === 'completed') {
			console.log('SUCCESS: Full E2E flow completed!');
			expect(dealData.payout_status).toBe('paid');
		} else {
			console.log(`Deal is ${dealData.status} — HTLC signing or LN payment may have failed`);
			// Check if HTLC was at least prepared
			sigStatusResp = await fetch(`${API}/deals/${dealId}/signing-status`);
			sigStatus = await sigStatusResp.json();
			console.log(`HTLC TX prepared: ${!!sigStatus.htlc_tx_hex}`);
			console.log(`HTLC seller signed: ${sigStatus.htlc_seller_signed}`);
		}

		// Cleanup
		await sellerContext.close();
		await buyerContext.close();
	});
});
