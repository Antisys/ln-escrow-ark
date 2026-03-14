/**
 * Ark Wallet — singleton wrapper for key management, signing, and Ark SDK.
 *
 * Keys are stored in localStorage encrypted with AES-256-GCM (WebCrypto).
 * Schnorr signing uses @noble/secp256k1 with hashes registered from @noble/hashes.
 *
 * Tested: key generation, encrypt/decrypt roundtrip, Schnorr sign/verify.
 */
import * as secp from '@noble/secp256k1';
import { sha256 } from '@noble/hashes/sha2.js';
import { hmac } from '@noble/hashes/hmac.js';
import { hex } from '@scure/base';
import { getArkServerUrl, getEsploraUrl } from './config.js';

// Register sync hashes for schnorr (required by @noble/secp256k1)
secp.hashes.sha256 = (...msgs) => {
	const h = sha256.create();
	msgs.forEach((m) => h.update(m));
	return h.digest();
};
secp.hashes.hmacSha256 = (key, ...msgs) => {
	const h = hmac.create(sha256, key);
	msgs.forEach((m) => h.update(m));
	return h.digest();
};

/** @type {any} SDK wallet instance */
let wallet = null;
/** @type {string} Compressed public key hex (33 bytes, 66 chars) */
let publicKeyHex = '';
/** @type {string|null} Cached private key hex for signing */
let _privHex = null;

const STORAGE_KEY = 'ark_wallet_key';

// ═══════════════════════════════════════════════════════════
// Wallet lifecycle
// ═══════════════════════════════════════════════════════════

/**
 * Create a new wallet keypair, encrypt with password, store in localStorage.
 * @param {string} password - User-chosen password (min 4 chars)
 * @returns {Promise<{privateKey: string, publicKey: string}>}
 */
export async function createWallet(password) {
	if (!password || password.length < 4) {
		throw new Error('Password must be at least 4 characters');
	}

	const privBytes = secp.utils.randomSecretKey();
	const privHexStr = hex.encode(privBytes);
	const pubBytes = secp.getPublicKey(privBytes, true);
	const pubHexStr = hex.encode(pubBytes);

	await _encryptAndStore(privHexStr, password);
	publicKeyHex = pubHexStr;
	_privHex = privHexStr;

	return { privateKey: privHexStr, publicKey: pubHexStr };
}

/**
 * Unlock existing wallet with password.
 * @param {string} password
 * @returns {Promise<boolean>} true if successfully unlocked
 */
export async function unlockWallet(password) {
	const privHexStr = await _decryptFromStore(password);
	if (!privHexStr) return false;

	const privBytes = hex.decode(privHexStr);
	const pubBytes = secp.getPublicKey(privBytes, true);
	publicKeyHex = hex.encode(pubBytes);
	_privHex = privHexStr;

	// Initialize Ark SDK ServiceWorkerWallet
	try {
		await _initSdkWallet(privHexStr);
	} catch (e) {
		console.error('Ark SDK wallet init FAILED:', e.message, e.stack);
	}

	return true;
}

/**
 * Lock the wallet — clear keys from memory.
 */
export function lockWallet() {
	wallet = null;
	publicKeyHex = '';
	_privHex = null;
}

/**
 * @returns {boolean} True if a wallet exists in localStorage
 */
export function hasWallet() {
	if (typeof localStorage === 'undefined') return false;
	return localStorage.getItem(STORAGE_KEY) !== null;
}

/**
 * @returns {boolean} True if wallet is unlocked and ready to sign
 */
export function isUnlocked() {
	return _privHex !== null && publicKeyHex !== '';
}

// ═══════════════════════════════════════════════════════════
// Key access
// ═══════════════════════════════════════════════════════════

/**
 * @returns {string} Compressed public key hex (33 bytes, starts with 02 or 03)
 */
export function getPublicKey() {
	return publicKeyHex;
}

/**
 * @returns {string} X-only public key hex (32 bytes, for taproot/schnorr)
 */
export function getXOnlyPublicKey() {
	if (!publicKeyHex) return '';
	return publicKeyHex.slice(2); // Remove 02/03 prefix
}

// ═══════════════════════════════════════════════════════════
// Signing
// ═══════════════════════════════════════════════════════════

/**
 * Sign a UTF-8 message with Schnorr (BIP-340).
 * Signs SHA256(message) with the wallet's private key.
 * @param {string} message - UTF-8 string
 * @returns {Promise<string>} Hex-encoded 64-byte Schnorr signature
 */
export async function signMessage(message) {
	if (!_privHex) throw new Error('Wallet is locked');

	const msgBytes = new TextEncoder().encode(message);
	const msgHash = sha256(msgBytes);
	const privBytes = hex.decode(_privHex);
	const sig = secp.schnorr.sign(msgHash, privBytes);

	return hex.encode(sig);
}

/**
 * Verify a Schnorr signature.
 * @param {string} sigHex - 64-byte hex signature
 * @param {string} message - UTF-8 string (will be SHA256'd)
 * @param {string} pubkeyHex - Compressed or x-only public key hex
 * @returns {boolean}
 */
export function verifySignature(sigHex, message, pubkeyHex) {
	const msgHash = sha256(new TextEncoder().encode(message));
	const sig = hex.decode(sigHex);
	// Use x-only key (32 bytes) for schnorr verification
	const xonly = pubkeyHex.length === 66 ? pubkeyHex.slice(2) : pubkeyHex;
	return secp.schnorr.verify(sig, msgHash, hex.decode(xonly));
}

/**
 * Compute SHA256 hash of a string. Used for secret_code_hash.
 * @param {string} input
 * @returns {string} Hex-encoded hash
 */
export function sha256Hash(input) {
	return hex.encode(sha256(new TextEncoder().encode(input)));
}

// ═══════════════════════════════════════════════════════════
// Ark SDK wallet operations (may not be available in all environments)
// ═══════════════════════════════════════════════════════════

/**
 * Get wallet balance from Ark SDK.
 * @returns {Promise<{total: number, offchain: number, boarding: number}>}
 */
export async function getBalance() {
	if (!wallet) return { total: 0, offchain: 0, boarding: 0 };
	try {
		const bal = await wallet.getBalance();
		return {
			total: bal.total || 0,
			offchain: (bal.settled || 0) + (bal.preconfirmed || 0),
			boarding: bal.boarding?.total || 0,
		};
	} catch {
		return { total: 0, offchain: 0, boarding: 0 };
	}
}

/**
 * Get Ark offchain address.
 * @returns {Promise<string>}
 */
export async function getAddress() {
	if (!wallet) return '';
	try {
		return await wallet.getAddress();
	} catch {
		return '';
	}
}

/**
 * Get Bitcoin boarding address for on-chain funding.
 * @returns {Promise<string>}
 */
export async function getBoardingAddress() {
	if (!wallet) return '';
	try {
		return await wallet.getBoardingAddress();
	} catch {
		return '';
	}
}

/**
 * Send sats via Ark (for escrow funding).
 * @param {string} address - Destination address
 * @param {number} amount - Amount in sats
 * @returns {Promise<string>} Transaction ID
 */
export async function sendToAddress(address, amount) {
	if (!wallet) throw new Error('Ark SDK wallet not initialized');
	return wallet.sendBitcoin({ address, amount });
}

// ═══════════════════════════════════════════════════════════
// Internal: SDK init
// ═══════════════════════════════════════════════════════════

async function _initSdkWallet(privHexStr) {
	const { ServiceWorkerWallet, SingleKey } = await import('@arkade-os/sdk');
	const identity = SingleKey.fromHex(privHexStr);

	console.log('SDK init: arkServerUrl=', getArkServerUrl(), 'esploraUrl=', getEsploraUrl());
	wallet = await ServiceWorkerWallet.setup({
		serviceWorkerPath: '/ark-service-worker.mjs',
		identity,
		arkServerUrl: getArkServerUrl(),
		esploraUrl: getEsploraUrl(),
		serviceWorkerActivationTimeoutMs: 30000,
		messageBusTimeoutMs: 30000,
	});
	console.log('SDK wallet initialized successfully');
}

// ═══════════════════════════════════════════════════════════
// Internal: AES-256-GCM encryption via WebCrypto
// ═══════════════════════════════════════════════════════════

/**
 * Encrypt private key with password and store in localStorage.
 * Format: base64(salt[16] + iv[12] + ciphertext[...])
 */
async function _encryptAndStore(privHexStr, password) {
	const enc = new TextEncoder();
	const salt = crypto.getRandomValues(new Uint8Array(16));
	const iv = crypto.getRandomValues(new Uint8Array(12));

	const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, [
		'deriveKey',
	]);
	const aesKey = await crypto.subtle.deriveKey(
		{ name: 'PBKDF2', salt, iterations: 100000, hash: 'SHA-256' },
		keyMaterial,
		{ name: 'AES-GCM', length: 256 },
		false,
		['encrypt']
	);
	const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, aesKey, enc.encode(privHexStr));

	const combined = new Uint8Array(16 + 12 + encrypted.byteLength);
	combined.set(salt, 0);
	combined.set(iv, 16);
	combined.set(new Uint8Array(encrypted), 28);

	localStorage.setItem(STORAGE_KEY, btoa(String.fromCharCode(...combined)));
}

/**
 * Decrypt private key from localStorage.
 * @returns {Promise<string|null>} Private key hex, or null if decryption fails
 */
async function _decryptFromStore(password) {
	const stored = localStorage.getItem(STORAGE_KEY);
	if (!stored) return null;

	try {
		const combined = new Uint8Array(
			atob(stored)
				.split('')
				.map((c) => c.charCodeAt(0))
		);
		const salt = combined.slice(0, 16);
		const iv = combined.slice(16, 28);
		const data = combined.slice(28);

		const enc = new TextEncoder();
		const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, [
			'deriveKey',
		]);
		const aesKey = await crypto.subtle.deriveKey(
			{ name: 'PBKDF2', salt, iterations: 100000, hash: 'SHA-256' },
			keyMaterial,
			{ name: 'AES-GCM', length: 256 },
			false,
			['decrypt']
		);
		const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, aesKey, data);
		return new TextDecoder().decode(decrypted);
	} catch {
		return null;
	}
}
