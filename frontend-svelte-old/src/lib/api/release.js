import { request } from './_shared.js';

export async function releaseDeal(dealId, buyerId, signature, timestamp, secretCode = null, buyerEscrowSignature = null) {
	return request(`/deals/${dealId}/release`, {
		method: 'POST',
		body: JSON.stringify({
			buyer_id: buyerId,
			signature,
			timestamp,
			secret_code: secretCode,
			buyer_escrow_signature: buyerEscrowSignature,
		})
	});
}
