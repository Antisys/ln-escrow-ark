import { request, adminHeaders } from './_shared.js';

export async function getAdminConfig(pubkey) {
	return request('/deals/admin/config', {
		headers: adminHeaders(null, pubkey)
	});
}

export async function getAdminDeals(pubkey, includeFinished = false, limit = 100) {
	return request(`/deals/admin/deals?include_finished=${includeFinished}&limit=${limit}`, {
		headers: adminHeaders(null, pubkey)
	});
}

export async function getAdminDisputes(pubkey) {
	return request('/deals/admin/disputes', {
		headers: adminHeaders(null, pubkey)
	});
}

export async function getAdminFailedPayouts(pubkey) {
	return request('/deals/admin/failed-payouts', {
		headers: adminHeaders(null, pubkey)
	});
}

export async function getAdminLedger(pubkey) {
	return request('/deals/admin/ledger', {
		headers: adminHeaders(null, pubkey)
	});
}

export async function adminResolveRelease(dealId, pubkey, note = null) {
	return request(`/deals/admin/${dealId}/resolve-release`, {
		method: 'POST',
		headers: adminHeaders(null, pubkey),
		body: JSON.stringify({ resolution_note: note })
	});
}

export async function adminResolveRefund(dealId, pubkey, note = null) {
	return request(`/deals/admin/${dealId}/resolve-refund`, {
		method: 'POST',
		headers: adminHeaders(null, pubkey),
		body: JSON.stringify({ resolution_note: note })
	});
}

export async function adminOracleSign(dealId, pubkey, signedEvent) {
	return request(`/deals/admin/${dealId}/oracle-sign`, {
		method: 'POST',
		headers: adminHeaders(null, pubkey),
		body: JSON.stringify({ signed_event: signedEvent })
	});
}

export async function getLimits() {
	return request('/deals/settings/limits');
}

export async function updateLimits(pubkey, minSats, maxSats) {
	const body = {};
	if (minSats !== undefined && minSats !== null) body.min_sats = minSats;
	if (maxSats !== undefined && maxSats !== null) body.max_sats = maxSats;

	return request('/deals/admin/settings/limits', {
		method: 'PUT',
		headers: adminHeaders(null, pubkey),
		body: JSON.stringify(body)
	});
}

export async function updateFees(pubkey, serviceFeePercent) {
	const body = {};
	if (serviceFeePercent !== undefined && serviceFeePercent !== null) body.service_fee_percent = serviceFeePercent;

	return request('/deals/admin/settings/fees', {
		method: 'PUT',
		headers: adminHeaders(null, pubkey),
		body: JSON.stringify(body)
	});
}

export async function getAdminChallenge() {
	return request('/auth/lnurl/admin/challenge');
}

export async function checkAdminAuthStatus(k1) {
	return request(`/auth/lnurl/admin/status/${k1}`);
}
