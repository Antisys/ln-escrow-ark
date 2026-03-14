import { request } from './_shared.js';
import { storeSecretCodeForDeal, getSecretCodeForDeal, getKeyForDeal } from '$lib/stores/vault.js';
import { signTimeoutAuth, getPublicKey, encryptForBackup } from '$lib/crypto.js';

/**
 * Generate a cryptographically random secret code and its SHA-256 hash.
 * Uses Web Crypto API — runs entirely in the browser.
 * The plaintext never leaves the browser (stored in localStorage only).
 */
async function generateSecretAndHash() {
	const secretBytes = crypto.getRandomValues(new Uint8Array(32));
	const secretCode = Array.from(secretBytes)
		.map((b) => b.toString(16).padStart(2, '0'))
		.join('');

	const encoder = new TextEncoder();
	const hashBuffer = await crypto.subtle.digest('SHA-256', encoder.encode(secretCode));
	const secretCodeHash = Array.from(new Uint8Array(hashBuffer))
		.map((b) => b.toString(16).padStart(2, '0'))
		.join('');

	return { secretCode, secretCodeHash };
}

/**
 * Compute SHA-256 hash of an existing secret code.
 */
async function hashSecret(secretCode) {
	const encoder = new TextEncoder();
	const hashBuffer = await crypto.subtle.digest('SHA-256', encoder.encode(secretCode));
	return Array.from(new Uint8Array(hashBuffer))
		.map((b) => b.toString(16).padStart(2, '0'))
		.join('');
}

export async function createLnInvoice(dealId) {
	// FUND SAFETY: Reuse existing secret if one is already stored for this deal.
	// Generating a new secret would overwrite the old one in localStorage.
	// If the old invoice was already paid, the new hash won't match and funds get stuck.
	let secretCode = getSecretCodeForDeal(dealId);
	let secretCodeHash;

	if (secretCode) {
		secretCodeHash = await hashSecret(secretCode);
	} else {
		const generated = await generateSecretAndHash();
		secretCode = generated.secretCode;
		secretCodeHash = generated.secretCodeHash;
		storeSecretCodeForDeal(dealId, secretCode);
	}

	// Non-custodial: include buyer's ephemeral pubkey and pre-signed timeout authorization.
	// The timeout_signature allows the service to process deal timeout without the buyer online.
	const bodyData = { secret_code_hash: secretCodeHash };

	const buyerKey = getKeyForDeal(dealId, 'buyer');
	if (buyerKey?.privateKey) {
		bodyData.buyer_pubkey = getPublicKey(buyerKey.privateKey);
		bodyData.timeout_signature = signTimeoutAuth(buyerKey.privateKey);
		// Encrypt secret_code for server-side backup (non-custodial recovery).
		// Only the buyer's ephemeral key can decrypt — server stores opaque blob.
		try {
			const encrypted = await encryptForBackup(buyerKey.privateKey, secretCode);
			bodyData.encrypted_vault = JSON.stringify(encrypted);
		} catch (e) {
			console.warn('Failed to encrypt vault backup:', e);
		}
	}

	return request(`/deals/${dealId}/create-ln-invoice`, {
		method: 'POST',
		body: JSON.stringify(bodyData)
	});
}

export async function checkLnInvoice(dealId) {
	return request(`/deals/${dealId}/check-ln-invoice`);
}
