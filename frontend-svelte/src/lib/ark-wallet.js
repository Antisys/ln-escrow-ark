/**
 * Ark Wallet integration — singleton wrapper around @arkade-os/sdk.
 * Keys stored in localStorage (encrypted with user password via WebCrypto).
 */
import { getArkServerUrl, getEsploraUrl } from './config.js';
import { hex } from '@scure/base';
import * as secp from '@noble/secp256k1';

/** @type {any} */
let wallet = null;
let publicKeyHex = '';
let _cachedPrivHex = null;

const STORAGE_KEY = 'ark_wallet_key';

// ── Wallet lifecycle ──────────────────────────────────────

export async function createWallet(password) {
	const privBytes = secp.utils.randomPrivateKey();
	const privHex = hex.encode(privBytes);
	const pubBytes = secp.getPublicKey(privBytes, true);
	const pubHex = hex.encode(pubBytes);

	await encryptAndStore(privHex, password);
	publicKeyHex = pubHex;

	return { privateKey: privHex, publicKey: pubHex };
}

export async function unlockWallet(password) {
	const privHex = await decryptFromStore(password);
	if (!privHex) return false;

	const privBytes = hex.decode(privHex);
	const pubBytes = secp.getPublicKey(privBytes, true);
	publicKeyHex = hex.encode(pubBytes);

	// Try to init SDK wallet (may fail in some environments)
	try {
		const { ServiceWorkerWallet, SingleKey } = await import('@arkade-os/sdk');
		wallet = await ServiceWorkerWallet.setup({
			serviceWorkerPath: '/ark-service-worker.mjs',
			identity: SingleKey.fromHex(privHex),
			arkServerUrl: getArkServerUrl(),
			esploraUrl: getEsploraUrl(),
		});
	} catch (e) {
		console.warn('SDK wallet init skipped:', e.message);
	}

	return true;
}

export function isUnlocked() { return publicKeyHex !== ''; }
export function hasWallet() { return typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY) !== null; }

export function lockWallet() {
	wallet = null;
	publicKeyHex = '';
	_cachedPrivHex = null;
}

// ── Wallet operations ─────────────────────────────────────

export function getPublicKey() { return publicKeyHex; }

export async function getBalance() {
	if (!wallet) return { total: 0, offchain: 0, boarding: 0 };
	try {
		const bal = await wallet.getBalance();
		return { total: bal.total || 0, offchain: (bal.settled || 0) + (bal.preconfirmed || 0), boarding: bal.boarding?.total || 0 };
	} catch { return { total: 0, offchain: 0, boarding: 0 }; }
}

export async function getAddress() {
	if (!wallet) return '';
	return wallet.getAddress();
}

export async function getBoardingAddress() {
	if (!wallet) return '';
	return wallet.getBoardingAddress();
}

export async function signMessage(message) {
	if (!_cachedPrivHex) throw new Error('Wallet locked');
	const msgBytes = new TextEncoder().encode(message);
	const msgHash = new Uint8Array(await crypto.subtle.digest('SHA-256', msgBytes));
	const sig = await secp.schnorr.sign(msgHash, hex.decode(_cachedPrivHex));
	return hex.encode(sig);
}

export async function sendToAddress(address, amount) {
	if (!wallet) throw new Error('Wallet not initialized');
	return wallet.sendBitcoin({ address, amount });
}

// ── Crypto helpers (WebCrypto AES-256-GCM) ────────────────

async function encryptAndStore(privHex, password) {
	const enc = new TextEncoder();
	const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
	const salt = crypto.getRandomValues(new Uint8Array(16));
	const key = await crypto.subtle.deriveKey(
		{ name: 'PBKDF2', salt, iterations: 100000, hash: 'SHA-256' },
		keyMaterial, { name: 'AES-GCM', length: 256 }, false, ['encrypt']
	);
	const iv = crypto.getRandomValues(new Uint8Array(12));
	const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, enc.encode(privHex));
	const combined = new Uint8Array(salt.length + iv.length + encrypted.byteLength);
	combined.set(salt, 0);
	combined.set(iv, salt.length);
	combined.set(new Uint8Array(encrypted), salt.length + iv.length);
	localStorage.setItem(STORAGE_KEY, btoa(String.fromCharCode(...combined)));
	_cachedPrivHex = privHex;
}

async function decryptFromStore(password) {
	const stored = localStorage.getItem(STORAGE_KEY);
	if (!stored) return null;
	try {
		const combined = new Uint8Array(atob(stored).split('').map(c => c.charCodeAt(0)));
		const salt = combined.slice(0, 16);
		const iv = combined.slice(16, 28);
		const data = combined.slice(28);
		const enc = new TextEncoder();
		const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
		const key = await crypto.subtle.deriveKey(
			{ name: 'PBKDF2', salt, iterations: 100000, hash: 'SHA-256' },
			keyMaterial, { name: 'AES-GCM', length: 256 }, false, ['decrypt']
		);
		const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, data);
		_cachedPrivHex = new TextDecoder().decode(decrypted);
		return _cachedPrivHex;
	} catch { return null; }
}
