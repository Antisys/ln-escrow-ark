import { request } from './_shared.js';

export async function validateLightningAddress(address, amountSats) {
	return request('/deals/validate-lightning-address', {
		method: 'POST',
		body: JSON.stringify({ address, amount_sats: amountSats })
	});
}

export async function submitPayoutInvoice(dealId, userId, invoice, signature, timestamp) {
	return request(`/deals/${dealId}/submit-payout-invoice`, {
		method: 'POST',
		body: JSON.stringify({
			user_id: userId,
			invoice: invoice,
			signature,
			timestamp
		})
	});
}

export async function shipDeal(dealId, sellerId, trackingCarrier, trackingNumber, shippingNotes, signature, timestamp) {
	return request(`/deals/${dealId}/ship`, {
		method: 'POST',
		body: JSON.stringify({
			seller_id: sellerId,
			tracking_carrier: trackingCarrier || null,
			tracking_number: trackingNumber || null,
			shipping_notes: shippingNotes || null,
			signature,
			timestamp
		})
	});
}
