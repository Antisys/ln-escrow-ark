// Shared API infrastructure — imported by domain modules
import { API_URL } from './base-url.js';

export { API_URL };

export async function request(endpoint, options = {}) {
	const { headers: customHeaders, retries = 1, ...restOptions } = options;
	let lastError;

	for (let attempt = 0; attempt <= retries; attempt++) {
		try {
			const res = await fetch(`${API_URL}${endpoint}`, {
				...restOptions,
				headers: {
					'Content-Type': 'application/json',
					...customHeaders
				}
			});

			if (!res.ok) {
				const error = await res.json().catch(() => ({ detail: res.statusText }));
				let message;
				if (typeof error.detail === 'string') {
					message = error.detail;
				} else if (Array.isArray(error.detail)) {
					message = error.detail.map(e => e.msg || e.message || JSON.stringify(e)).join('; ');
				} else {
					message = error.message || error.error || res.statusText;
				}
				throw new Error(message || `Request failed (${res.status})`);
			}

			return res.json();
		} catch (err) {
			lastError = err;
			// Only retry on network errors, not on HTTP errors from the server
			if (err.name === 'TypeError' && attempt < retries) {
				await new Promise(r => setTimeout(r, 1000));
				continue;
			}
			throw err;
		}
	}

	throw lastError;
}

export function adminHeaders(apiKey, pubkey) {
	const headers = {};
	if (apiKey) headers['X-Admin-Key'] = apiKey;
	if (pubkey) headers['X-Admin-Pubkey'] = pubkey;
	return headers;
}
