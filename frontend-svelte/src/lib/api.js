/**
 * Backend API client for trustMeBro-ARK.
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

// ── Deals ─────────────────────────────────────────────────

export async function createDeal({ title, description, price_sats, timeout_hours, seller_pubkey }) {
	return request('/deals/', {
		method: 'POST',
		body: JSON.stringify({ title, description, price_sats, timeout_hours, seller_pubkey, creator_role: 'seller' }),
	});
}

export async function getDeal(dealId) {
	return request(`/deals/${dealId}`);
}

export async function joinDeal(dealId, buyerPubkey) {
	return request(`/deals/${dealId}/join`, {
		method: 'POST',
		body: JSON.stringify({ buyer_pubkey: buyerPubkey }),
	});
}

export async function getDealByToken(token) {
	return request(`/deals/by-token/${token}`);
}

// ── Escrow ────────────────────────────────────────────────

export async function createEscrow(dealId) {
	return request(`/deals/${dealId}/create-escrow`, { method: 'POST' });
}

export async function confirmFunding(dealId, vtxoTxid, vtxoVout) {
	return request(`/deals/${dealId}/fund`, {
		method: 'POST',
		body: JSON.stringify({ vtxo_txid: vtxoTxid, vtxo_vout: vtxoVout }),
	});
}

export async function checkFunding(dealId) {
	return request(`/deals/${dealId}/check-funding`);
}

// ── Actions ───────────────────────────────────────────────

export async function shipDeal(dealId, { carrier, tracking_number, notes }) {
	return request(`/deals/${dealId}/ship`, {
		method: 'POST',
		body: JSON.stringify({ carrier, tracking_number, notes }),
	});
}

export async function releaseDeal(dealId, { secret_code, buyer_signature }) {
	return request(`/deals/${dealId}/release`, {
		method: 'POST',
		body: JSON.stringify({ secret_code, buyer_signature }),
	});
}

export async function refundDeal(dealId, { buyer_signature }) {
	return request(`/deals/${dealId}/refund`, {
		method: 'POST',
		body: JSON.stringify({ buyer_signature }),
	});
}

export async function disputeDeal(dealId, { disputed_by, reason, signature }) {
	return request(`/deals/${dealId}/dispute`, {
		method: 'POST',
		body: JSON.stringify({ disputed_by, reason, signature }),
	});
}

// ── System ────────────────────────────────────────────────

export async function getHealth() {
	return request('/health');
}

export async function getSystemStatus() {
	return request('/system-status');
}
