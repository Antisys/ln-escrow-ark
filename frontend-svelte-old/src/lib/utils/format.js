/**
 * Shared formatting utilities used across deal and admin pages.
 */

export function formatSats(sats) {
	if (sats == null) return '—';
	return Number(sats).toLocaleString();
}

export function getStatusLabel(status) {
	const labels = {
		'pending': 'Pending', 'active': 'Active', 'awaiting_funding': 'Awaiting Funding',
		'funded': 'Funded', 'shipped': 'Shipped', 'releasing': 'Releasing...',
		'refunding': 'Refunding...', 'completed': 'Completed', 'released': 'Completed',
		'refunded': 'Refunded', 'disputed': 'Disputed', 'expired': 'Expired', 'cancelled': 'Cancelled'
	};
	return labels[status] || status;
}

export function getStatusPillClass(status) {
	const classes = {
		'pending': 'pill-pending', 'active': 'pill-pending', 'awaiting_funding': 'pill-pending',
		'funded': 'pill-funded', 'shipped': 'pill-shipped', 'releasing': 'pill-funded',
		'refunding': 'pill-funded', 'completed': 'pill-completed', 'released': 'pill-completed',
		'refunded': 'pill-refunded', 'disputed': 'pill-disputed', 'expired': 'pill-refunded',
		'cancelled': 'pill-refunded'
	};
	return classes[status] || 'pill-pending';
}

export function getStatusColor(status) {
	const colors = {
		'pending': 'var(--text-muted)', 'active': 'var(--info)', 'funded': 'var(--success)',
		'shipped': '#8b5cf6', 'releasing': 'var(--success)', 'refunding': 'var(--warning)',
		'completed': 'var(--success)', 'released': 'var(--success)', 'refunded': 'var(--warning)',
		'disputed': 'var(--error)', 'expired': 'var(--text-dim)', 'cancelled': 'var(--text-dim)'
	};
	return colors[status] || 'var(--text-muted)';
}

export function friendlyError(msg, appStaleCallback) {
	if (!msg) return 'Something went wrong. Please try again.';
	const m = msg.toLowerCase();
	if (m.includes('dynamically imported module') || m.includes('loading chunk') || m.includes('loading css chunk')) {
		if (appStaleCallback) appStaleCallback();
		return 'App updated — please reload the page.';
	}
	if (m.includes('deal timeout') || m.includes('too close to expiry'))
		return 'This deal is too close to expiry for a safe payout. Please contact support.';
	if (m.includes('no route') || m.includes('no_route'))
		return 'Could not find a Lightning route. Try a different wallet or Lightning Address.';
	if (m.includes('insufficient') && m.includes('balance'))
		return 'Service has insufficient liquidity. Please try again later.';
	if (m.includes('invoice expired'))
		return 'Invoice expired. Please generate a new one.';
	if (m.includes('timeout') || m.includes('timed out'))
		return 'Lightning payment timed out. Please try again.';
	if (m.includes('network') || m.includes('fetch') || m.includes('failed to fetch'))
		return 'Network error. Check your connection and try again.';
	if (m.includes('escrow already claimed for refund'))
		return 'A refund was already processed for this deal. Funds were returned to the buyer.';
	if (m.includes('escrow already claimed for release'))
		return 'This deal was already released. Funds have been sent to the seller.';
	if (m.includes('escrow already claimed') || m.includes('already paid'))
		return 'This deal has already been settled. Reload the page to see the current status.';
	if (m.includes('invoice amount mismatch'))
		return 'Payment address amount mismatch. Please contact support.';
	if (m.includes('payment safety check failed') || m.includes('blocked'))
		return 'Payment safety check failed. Please try again or contact support.';
	if (m.includes('invalid signature') || m.includes('signature verification'))
		return 'Signature verification failed. Make sure you are using the same wallet you signed in with.';
	if (m.includes('timestamp'))
		return 'Request expired — your device clock may be incorrect. Please check your system time and try again.';
	if (m.includes('could not be verified'))
		return msg.replace(/^(Error: |HTTPError: )/i, '');
	if (m.includes('below') && m.includes('minimum'))
		return msg.replace(/^(Error: |HTTPError: )/i, '');
	if (m.includes('exceeds') && m.includes('maximum'))
		return msg.replace(/^(Error: |HTTPError: )/i, '');
	if (m.includes('cannot change payout invoice'))
		return 'The payout is already in progress and the destination cannot be changed.';
	return msg.replace(/^(Error: |HTTPError: )/i, '');
}

export async function copyToClipboard(text) {
	try {
		await navigator.clipboard.writeText(text);
	} catch {
		const ta = document.createElement('textarea');
		ta.value = text;
		ta.style.position = 'fixed';
		ta.style.left = '-9999px';
		document.body.appendChild(ta);
		ta.select();
		document.execCommand('copy');
		document.body.removeChild(ta);
	}
}

export function formatSatsCompact(sats) {
	if (sats >= 100000000) return `${(sats / 100000000).toFixed(2)} BTC`;
	if (sats >= 1000000)   return `${(sats / 1000000).toFixed(1)}M sats`;
	if (sats >= 1000)      return `${(sats / 1000).toFixed(0)}k sats`;
	return `${sats} sats`;
}
