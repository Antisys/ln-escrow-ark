/**
 * API client — backward-compatible barrel file.
 *
 * All shared infrastructure lives in _shared.js.
 * Domain functions live in their own modules.
 * This file re-exports everything so existing imports
 * like `import { getDeal } from '$lib/api.js'` keep working
 * after renaming this directory.
 */

// Shared infrastructure
export { API_URL, request, adminHeaders } from './_shared.js';

// WebSocket + system status (defined here, no circular dep)
import { API_URL, request } from './_shared.js';

function getWsUrl() {
	return API_URL.replace(/^http/, 'ws') + '/ws';
}

/**
 * Create a WebSocket connection for real-time deal updates.
 * Reconnects automatically with exponential backoff.
 */
export function connectDealWs(dealId, onEvent) {
	if (typeof window === 'undefined') return { close() {} };

	let ws = null;
	let closed = false;
	let retryDelay = 1000;
	const maxRetry = 30000;

	function connect() {
		if (closed) return;
		try {
			ws = new WebSocket(`${getWsUrl()}/deals/${dealId}`);
		} catch {
			scheduleRetry();
			return;
		}

		ws.onopen = () => { retryDelay = 1000; };

		ws.onmessage = (evt) => {
			try {
				const msg = JSON.parse(evt.data);
				if (msg.event && msg.event !== 'pong') {
					onEvent(msg.event, msg.data);
				}
			} catch { /* ignore parse errors */ }
		};

		ws.onclose = () => { if (!closed) scheduleRetry(); };
		ws.onerror = () => { ws.close(); };
	}

	function scheduleRetry() {
		setTimeout(connect, retryDelay);
		retryDelay = Math.min(retryDelay * 1.5, maxRetry);
	}

	connect();

	const pingId = setInterval(() => {
		if (ws && ws.readyState === WebSocket.OPEN) {
			ws.send('ping');
		}
	}, 25000);

	return {
		close() {
			closed = true;
			clearInterval(pingId);
			if (ws) ws.close();
		}
	};
}

export async function getSystemStatus() {
	return request('/system-status');
}

// Re-export all domain modules
export * from './deals.js';
export * from './funding.js';
export * from './release.js';
export * from './refund.js';
export * from './payout.js';
export * from './admin.js';
export * from './auth.js';
