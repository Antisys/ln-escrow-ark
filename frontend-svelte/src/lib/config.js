/** @returns {string} */
export function getApiUrl() {
	if (typeof window === 'undefined') return '';
	const host = window.location.hostname;
	if (host === 'ark.trustbro.trade') return 'https://ark-api.trustbro.trade';
	if (host === 'localhost') return 'http://localhost:8002';
	return `${window.location.protocol}//${host}:8002`;
}

/** @returns {string} */
export function getArkServerUrl() {
	if (typeof window === 'undefined') return '';
	const host = window.location.hostname;
	if (host === 'ark.trustbro.trade') return 'https://ark.trustbro.trade/v1';
	if (host === 'localhost') return 'http://localhost:7070';
	return `${window.location.protocol}//${host}:7070`;
}

/** @returns {string} */
export function getEsploraUrl() {
	if (typeof window === 'undefined') return '';
	const host = window.location.hostname;
	if (host === 'ark.trustbro.trade') return 'https://ark.trustbro.trade/esplora';
	if (host === 'localhost') return 'http://localhost:3000';
	return `${window.location.protocol}//${host}:3000`;
}

export const APP_NAME = 'trustMeBro-ARK';
export const DEFAULT_PASSWORD = 'noah'; // dev default, user sets own in production
