import * as secp from '@noble/secp256k1';
import { schnorr } from '@noble/curves/secp256k1';
import { hmac } from '@noble/hashes/hmac';
import { sha256 } from '@noble/hashes/sha256';
// Required for @noble/secp256k1 v2+ synchronous signing
secp.etc.hmacSha256Sync = (k, ...m) => hmac(sha256, k, secp.etc.concatBytes(...m));

function bytesToHex(bytes) {
	return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}

function hexToBytes(hex) {
	const bytes = new Uint8Array(hex.length / 2);
	for (let i = 0; i < hex.length; i += 2) {
		bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
	}
	return bytes;
}

/**
 * Derive ephemeral key pair from LNURL-auth signature
 * Uses HMAC-SHA256(signature, dealId + "ephemeral") as private key
 */
export function deriveEphemeralKey(signatureHex, dealId) {
	const sigBytes = hexToBytes(signatureHex);
	const derivationData = new TextEncoder().encode(dealId + 'ephemeral');

	// Derive private key using HMAC-SHA256
	const privateKeyBytes = hmac(sha256, sigBytes, derivationData);
	const privateKey = bytesToHex(privateKeyBytes);

	// Derive public key using secp256k1
	const publicKeyBytes = secp.getPublicKey(privateKeyBytes, true);
	const publicKey = bytesToHex(publicKeyBytes);

	return { privateKey, publicKey };
}

/**
 * Convert bigint to bytes for DER encoding.
 * Used internally by compactToDER.
 */
function bigintToBytes(n) {
	let hex = n.toString(16);
	if (hex.length % 2) hex = '0' + hex;

	const bytes = new Uint8Array(hex.length / 2);
	for (let i = 0; i < bytes.length; i++) {
		bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
	}

	// DER requires positive integers: add 0x00 prefix if high bit is set
	if (bytes[0] >= 0x80) {
		const padded = new Uint8Array(bytes.length + 1);
		padded[0] = 0x00;
		padded.set(bytes, 1);
		return padded;
	}

	return bytes;
}

/**
 * Convert compact signature (r, s bigints) to DER format.
 * Used by signAction() for LNURL-auth challenge signing.
 */
export function compactToDER(r, s) {
	const rBytes = bigintToBytes(r);
	const sBytes = bigintToBytes(s);

	const rLen = rBytes.length;
	const sLen = sBytes.length;
	const totalLen = 2 + rLen + 2 + sLen;

	const der = new Uint8Array(2 + totalLen);
	let offset = 0;

	der[offset++] = 0x30; // Sequence tag
	der[offset++] = totalLen;

	der[offset++] = 0x02; // Integer tag for R
	der[offset++] = rLen;
	der.set(rBytes, offset);
	offset += rLen;

	der[offset++] = 0x02; // Integer tag for S
	der[offset++] = sLen;
	der.set(sBytes, offset);

	return der;
}

/**
 * Sign a deal action with the ephemeral private key.
 * Returns { signature, timestamp } where signature is DER-encoded hex.
 *
 * Signed message: "{dealId}:{action}:{timestamp}" → SHA-256 → ECDSA
 */
export function signAction(privateKeyHex, dealId, action) {
	const timestamp = Math.floor(Date.now() / 1000);
	const message = `${dealId}:${action}:${timestamp}`;
	const msgHash = sha256(new TextEncoder().encode(message));
	const sig = secp.sign(msgHash, hexToBytes(privateKeyHex), { lowS: true });
	const derBytes = compactToDER(sig.r, sig.s);
	return { signature: bytesToHex(derBytes), timestamp };
}

/**
 * Sign an oracle attestation as a Nostr event (BIP-340 Schnorr).
 * Private key NEVER leaves the browser — only the signed event is sent to the backend.
 *
 * Returns a complete NIP-01 Nostr event: {id, pubkey, created_at, kind, tags, content, sig}
 */
export function signOracleAttestation(privkeyHex, escrowId, outcome, reason = null) {
	const privBytes = hexToBytes(privkeyHex);
	const xonly = bytesToHex(schnorr.getPublicKey(privBytes));
	const createdAt = Math.floor(Date.now() / 1000);
	const content = reason ? JSON.stringify({ outcome, reason }) : outcome;

	// NIP-01 canonical serialization for event ID
	const serialized = JSON.stringify(
		[0, xonly, createdAt, 30001, [['d', escrowId]], content]
	);
	const eventIdBytes = sha256(new TextEncoder().encode(serialized));
	const eventId = bytesToHex(eventIdBytes);

	// BIP-340 Schnorr signature over the 32-byte event ID
	const sig = bytesToHex(schnorr.sign(eventIdBytes, privBytes));

	return {
		id: eventId,
		pubkey: xonly,
		created_at: createdAt,
		kind: 30001,
		tags: [['d', escrowId]],
		content,
		sig,
	};
}

/**
 * Sign for release: BIP-340 Schnorr over SHA256(secretCode as UTF-8 bytes).
 * Used for non-custodial delegated release — proves buyer consent.
 */
export function signForRelease(privateKeyHex, secretCode) {
	const privBytes = hexToBytes(privateKeyHex);
	const message = sha256(new TextEncoder().encode(secretCode));
	return bytesToHex(schnorr.sign(message, privBytes));
}

/**
 * Sign timeout authorization: BIP-340 Schnorr over SHA256("timeout").
 * Pre-signed at funding time — allows service to process timeout without buyer online.
 */
export function signTimeoutAuth(privateKeyHex) {
	const privBytes = hexToBytes(privateKeyHex);
	const message = sha256(new TextEncoder().encode('timeout'));
	return bytesToHex(schnorr.sign(message, privBytes));
}

/**
 * Sign dispute authorization: BIP-340 Schnorr over SHA256("dispute").
 * Used for non-custodial delegated dispute — proves user initiated dispute.
 */
export function signDispute(privateKeyHex) {
	const privBytes = hexToBytes(privateKeyHex);
	const message = sha256(new TextEncoder().encode('dispute'));
	return bytesToHex(schnorr.sign(message, privBytes));
}

/**
 * Get the compressed public key (33 bytes, hex) from a private key.
 */
export function getPublicKey(privateKeyHex) {
	const privBytes = hexToBytes(privateKeyHex);
	return bytesToHex(secp.getPublicKey(privBytes, true));
}

/**
 * Encrypt plaintext for server-side backup using a key derived from the ephemeral private key.
 * Uses HKDF(SHA-256) for key derivation and AES-256-GCM for encryption.
 * The server stores the ciphertext but cannot decrypt without the ephemeral key.
 */
export async function encryptForBackup(privateKeyHex, plaintext) {
	const keyMaterial = await crypto.subtle.importKey(
		'raw', hexToBytes(privateKeyHex), 'HKDF', false, ['deriveKey']
	);
	const aesKey = await crypto.subtle.deriveKey(
		{ name: 'HKDF', hash: 'SHA-256', salt: new TextEncoder().encode('vault-backup'), info: new Uint8Array() },
		keyMaterial, { name: 'AES-GCM', length: 256 }, false, ['encrypt']
	);
	const iv = crypto.getRandomValues(new Uint8Array(12));
	const ciphertext = await crypto.subtle.encrypt(
		{ name: 'AES-GCM', iv }, aesKey, new TextEncoder().encode(plaintext)
	);
	return { iv: bytesToHex(iv), ciphertext: bytesToHex(new Uint8Array(ciphertext)) };
}

/**
 * Decrypt server-stored backup using the ephemeral private key.
 * Reverse of encryptForBackup — same HKDF derivation, AES-GCM decrypt.
 */
export async function decryptFromBackup(privateKeyHex, ivHex, ciphertextHex) {
	const keyMaterial = await crypto.subtle.importKey(
		'raw', hexToBytes(privateKeyHex), 'HKDF', false, ['deriveKey']
	);
	const aesKey = await crypto.subtle.deriveKey(
		{ name: 'HKDF', hash: 'SHA-256', salt: new TextEncoder().encode('vault-backup'), info: new Uint8Array() },
		keyMaterial, { name: 'AES-GCM', length: 256 }, false, ['decrypt']
	);
	const plainBuffer = await crypto.subtle.decrypt(
		{ name: 'AES-GCM', iv: hexToBytes(ivHex) }, aesKey, hexToBytes(ciphertextHex)
	);
	return new TextDecoder().decode(plainBuffer);
}

export function getVisitorId() {
	if (typeof window === 'undefined') return 'server';

	const components = [
		navigator.userAgent,
		navigator.language,
		screen.width + 'x' + screen.height,
		new Date().getTimezoneOffset()
	];

	const data = new TextEncoder().encode(components.join('|'));
	const hash = sha256(data);
	return bytesToHex(hash).slice(0, 32);
}
