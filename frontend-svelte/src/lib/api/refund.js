import { request } from './_shared.js';

export async function submitRefundInvoice(dealId, userId, invoice, signature, timestamp) {
	return request(`/deals/${dealId}/submit-refund-invoice`, {
		method: 'POST',
		body: JSON.stringify({
			user_id: userId,
			invoice: invoice,
			signature,
			timestamp
		})
	});
}

export async function openDispute(dealId, userId, reason, signature, timestamp, escrowSignature = null) {
	return request(`/deals/${dealId}/dispute`, {
		method: 'POST',
		body: JSON.stringify({
			user_id: userId,
			reason: reason,
			signature,
			timestamp,
			escrow_signature: escrowSignature,
		})
	});
}

export async function cancelDispute(dealId, userId, signature, timestamp) {
	return request(`/deals/${dealId}/cancel-dispute`, {
		method: 'POST',
		body: JSON.stringify({
			user_id: userId,
			signature,
			timestamp
		})
	});
}

export async function submitDisputeContact(dealId, userId, contact, message, signature, timestamp) {
	return request(`/deals/${dealId}/dispute-contact`, {
		method: 'POST',
		body: JSON.stringify({
			user_id: userId,
			contact,
			message,
			signature,
			timestamp
		})
	});
}
