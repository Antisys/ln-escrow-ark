import { request } from './_shared.js';

export async function createDeal(data) {
	return request('/deals/', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export async function getDeal(id) {
	return request(`/deals/${id}`);
}

export async function getDealByToken(token) {
	return request(`/deals/token/${token}`);
}

export async function getSigningStatus(dealId) {
	return request(`/deals/${dealId}/signing-status`);
}
