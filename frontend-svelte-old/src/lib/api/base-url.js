// Single source of truth for API URL detection

function getApiUrl() {
	if (typeof window === 'undefined') return 'http://localhost:8001';
	const host = window.location.hostname;
	if (host === 'localhost' || host === '127.0.0.1') {
		return 'http://localhost:8001';
	}
	if (host.match(/^192\.168\.|^10\.|^172\.(1[6-9]|2[0-9]|3[01])\./)) {
		return `http://${host}:8001`;
	}
	if (host === 'localhost:8001') return 'https://k9f2.localhost:8001';
	return window.location.origin.replace(':5174', ':8001').replace(':5173', ':8001');
}

export const API_URL = getApiUrl();
