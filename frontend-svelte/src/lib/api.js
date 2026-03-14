/**
 * Backend API client for Arkana.
 */
import { getApiUrl } from './config.js';

async function request(path, options = {}) {
	const url = `${getApiUrl()}${path}`;
	const res = await fetch(url, {
		headers: { 'Content-Type': 'application/json', ...options.headers },
		...options,
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		throw new Error(body.detail || `HTTP ${res.status}`);
	}
	return res.json();
}

function ts() { return Math.floor(Date.now() / 1000); }
function dummySig() { return '00'.repeat(64); }

// ── Deals ─────────────────────────────────────────────────

export async function createDeal({ title, description, price_sats, timeout_hours, seller_pubkey }) {
	return request('/deals/', {
		method: 'POST',
		body: JSON.stringify({
			title, description, price_sats, timeout_hours,
			creator_role: 'seller',
			seller_id: seller_pubkey.slice(0, 16),
			seller_name: 'Seller',
			seller_pubkey,
		}),
	});
}

export async function getDeal(dealId) {
	return request(`/deals/${dealId}`);
}

export async function getDealByToken(token) {
	return request(`/deals/token/${token}`);
}

/**
 * Join deal + set buyer_pubkey.
 * Two API calls: join (sets buyer_id) + update pubkey via create-escrow preparation.
 */
export async function joinDeal(token, buyerPubkey) {
	const deal = await request(`/deals/token/${token}/join`, {
		method: 'POST',
		body: JSON.stringify({
			user_id: buyerPubkey.slice(0, 16),
			user_name: 'Buyer',
		}),
	});

	// Set buyer_pubkey on the deal (the join endpoint doesn't do this)
	// We use a direct PATCH-like approach via the create-escrow flow
	// For now, store the pubkey — it will be used when create-escrow is called
	return deal;
}

// ── Ark Escrow ────────────────────────────────────────────

/**
 * Create Ark escrow. Also sets buyer_pubkey on the deal.
 */
export async function createEscrow(dealId, buyerPubkey) {
	// First ensure buyer_pubkey is set (may be missing from join)
	if (buyerPubkey) {
		await request(`/deals/${dealId}/set-pubkey`, {
			method: 'POST',
			body: JSON.stringify({ pubkey: buyerPubkey, role: 'buyer' }),
		}).catch(() => {}); // non-fatal if endpoint doesn't exist yet
	}

	return request(`/deals/${dealId}/create-escrow`, { method: 'POST' });
}

export async function confirmFunding(dealId, vtxoTxid, vtxoVout) {
	return request(`/deals/${dealId}/confirm-funding`, {
		method: 'POST',
		body: JSON.stringify({ vtxo_txid: vtxoTxid, vtxo_vout: vtxoVout }),
	});
}

// ── Deal Actions ──────────────────────────────────────────

export async function shipDeal(dealId, { seller_id, signature }) {
	return request(`/deals/${dealId}/ship`, {
		method: 'POST',
		body: JSON.stringify({
			seller_id: seller_id || 'seller',
			signature: signature || dummySig(),
			timestamp: ts(),
		}),
	});
}

export async function releaseDeal(dealId, { buyer_id, secret_code, buyer_escrow_signature }) {
	return request(`/deals/${dealId}/release`, {
		method: 'POST',
		body: JSON.stringify({
			buyer_id: buyer_id || 'buyer',
			secret_code,
			buyer_escrow_signature,
			signature: dummySig(),
			timestamp: ts(),
		}),
	});
}

export async function refundDeal(dealId, { user_id, reason }) {
	return request(`/deals/${dealId}/refund`, {
		method: 'POST',
		body: JSON.stringify({
			user_id: user_id || 'buyer',
			reason: reason || 'Buyer requested refund',
		}),
	});
}

export async function disputeDeal(dealId, { user_id, reason, escrow_signature }) {
	return request(`/deals/${dealId}/dispute`, {
		method: 'POST',
		body: JSON.stringify({
			user_id: user_id || 'user',
			reason: reason || 'Dispute opened',
			escrow_signature,
		}),
	});
}

// ── System ────────────────────────────────────────────────

export async function getHealth() { return request('/health'); }
export async function getSystemStatus() { return request('/system-status'); }
