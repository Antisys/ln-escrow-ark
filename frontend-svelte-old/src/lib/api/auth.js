import { request } from './_shared.js';

export async function getLnurlChallenge(dealToken, role) {
	return request(`/auth/lnurl/challenge/${encodeURIComponent(dealToken)}?role=${encodeURIComponent(role)}`);
}

export async function checkAuthStatus(k1) {
	return request(`/auth/lnurl/status/${k1}`);
}

export async function registerDerivedKey(k1, userId, ephemeralPubkey, timeoutSignature = null) {
	const body = {
		k1,
		user_id: userId,
		ephemeral_pubkey: ephemeralPubkey,
	};
	if (timeoutSignature) {
		body.timeout_signature = timeoutSignature;
	}
	return request('/auth/lnurl/register-derived-key', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}

export async function getLoginChallenge() {
	return request('/auth/lnurl/login');
}

export async function getMyDeals(k1) {
	return request(`/auth/lnurl/my-deals/${k1}`);
}
