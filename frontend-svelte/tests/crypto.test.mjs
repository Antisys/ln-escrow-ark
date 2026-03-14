/**
 * Crypto integration tests — run with: node tests/crypto.test.mjs
 * Tests all crypto operations used by ark-wallet.js without browser dependencies.
 */
import * as secp from '@noble/secp256k1';
import { sha256 } from '@noble/hashes/sha2.js';
import { hmac } from '@noble/hashes/hmac.js';
import { hex } from '@scure/base';

// Register hashes (same as ark-wallet.js)
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

let passed = 0;
let failed = 0;

function test(name, fn) {
	try {
		fn();
		passed++;
		console.log(`  PASS  ${name}`);
	} catch (e) {
		failed++;
		console.log(`  FAIL  ${name}: ${e.message}`);
	}
}

function assert(condition, msg) {
	if (!condition) throw new Error(msg || 'Assertion failed');
}

console.log('\n=== Crypto Tests ===\n');

// ── Key Generation ────────────────────────────────────────

test('randomSecretKey generates 32 bytes', () => {
	const key = secp.utils.randomSecretKey();
	assert(key.length === 32, `Expected 32, got ${key.length}`);
});

test('randomSecretKey generates unique keys', () => {
	const k1 = hex.encode(secp.utils.randomSecretKey());
	const k2 = hex.encode(secp.utils.randomSecretKey());
	assert(k1 !== k2, 'Keys should differ');
});

test('getPublicKey returns 33-byte compressed key', () => {
	const priv = secp.utils.randomSecretKey();
	const pub = secp.getPublicKey(priv, true);
	assert(pub.length === 33, `Expected 33, got ${pub.length}`);
	assert(pub[0] === 0x02 || pub[0] === 0x03, `Bad prefix: ${pub[0]}`);
});

test('same private key gives same public key', () => {
	const priv = secp.utils.randomSecretKey();
	const pub1 = hex.encode(secp.getPublicKey(priv, true));
	const pub2 = hex.encode(secp.getPublicKey(priv, true));
	assert(pub1 === pub2, 'Public keys should match');
});

// ── Schnorr Signing ───────────────────────────────────────

test('schnorr sign produces 64-byte signature', () => {
	const priv = secp.utils.randomSecretKey();
	const msg = sha256(new TextEncoder().encode('test'));
	const sig = secp.schnorr.sign(msg, priv);
	assert(sig.length === 64, `Expected 64, got ${sig.length}`);
});

test('schnorr verify succeeds with correct key', () => {
	const priv = secp.utils.randomSecretKey();
	const pub = secp.getPublicKey(priv, true);
	const xonly = pub.slice(1); // 32-byte x-only
	const msg = sha256(new TextEncoder().encode('hello world'));
	const sig = secp.schnorr.sign(msg, priv);
	const valid = secp.schnorr.verify(sig, msg, xonly);
	assert(valid, 'Signature should be valid');
});

test('schnorr verify fails with wrong key', () => {
	const priv1 = secp.utils.randomSecretKey();
	const priv2 = secp.utils.randomSecretKey();
	const pub2 = secp.getPublicKey(priv2, true).slice(1);
	const msg = sha256(new TextEncoder().encode('test'));
	const sig = secp.schnorr.sign(msg, priv1);
	const valid = secp.schnorr.verify(sig, msg, pub2);
	assert(!valid, 'Should reject wrong key');
});

test('schnorr verify fails with wrong message', () => {
	const priv = secp.utils.randomSecretKey();
	const pub = secp.getPublicKey(priv, true).slice(1);
	const msg1 = sha256(new TextEncoder().encode('msg1'));
	const msg2 = sha256(new TextEncoder().encode('msg2'));
	const sig = secp.schnorr.sign(msg1, priv);
	const valid = secp.schnorr.verify(sig, msg2, pub);
	assert(!valid, 'Should reject wrong message');
});

test('schnorr sign with random nonce produces valid but different signatures', () => {
	const priv = secp.utils.randomSecretKey();
	const pub = secp.getPublicKey(priv, true).slice(1);
	const msg = sha256(new TextEncoder().encode('deterministic'));
	const sig1 = secp.schnorr.sign(msg, priv);
	const sig2 = secp.schnorr.sign(msg, priv);
	// Both should verify
	assert(secp.schnorr.verify(sig1, msg, pub), 'Sig1 should verify');
	assert(secp.schnorr.verify(sig2, msg, pub), 'Sig2 should verify');
	// May differ due to random aux nonce (BIP-340 recommended)
});

// ── SHA256 ────────────────────────────────────────────────

test('sha256 produces 32-byte hash', () => {
	const h = sha256(new TextEncoder().encode('test'));
	assert(h.length === 32, `Expected 32, got ${h.length}`);
});

test('sha256 is deterministic', () => {
	const h1 = hex.encode(sha256(new TextEncoder().encode('abc')));
	const h2 = hex.encode(sha256(new TextEncoder().encode('abc')));
	assert(h1 === h2, 'Hashes should match');
	assert(h1 === 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', 'Known hash mismatch');
});

// ── Hex encode/decode ─────────────────────────────────────

test('hex roundtrip', () => {
	const bytes = secp.utils.randomSecretKey();
	const encoded = hex.encode(bytes);
	const decoded = hex.decode(encoded);
	assert(encoded.length === 64, `Expected 64 hex chars, got ${encoded.length}`);
	assert(decoded.length === 32, `Expected 32 bytes, got ${decoded.length}`);
	for (let i = 0; i < bytes.length; i++) {
		assert(bytes[i] === decoded[i], `Byte mismatch at ${i}`);
	}
});

// ── Secret Code Hash (escrow mechanism) ───────────────────

test('secret code hash workflow', () => {
	const secretCode = 'my-secret-code-12345';
	const hash = hex.encode(sha256(new TextEncoder().encode(secretCode)));
	assert(hash.length === 64, 'Hash should be 64 hex chars');

	// Simulated verify: given secret_code, compute hash and compare
	const verifyHash = hex.encode(sha256(new TextEncoder().encode(secretCode)));
	assert(hash === verifyHash, 'Hash verification should match');
});

test('different secret codes produce different hashes', () => {
	const h1 = hex.encode(sha256(new TextEncoder().encode('code1')));
	const h2 = hex.encode(sha256(new TextEncoder().encode('code2')));
	assert(h1 !== h2, 'Different codes should produce different hashes');
});

// ── Escrow signing workflow simulation ────────────────────

test('full escrow signing workflow', () => {
	// Simulate: buyer signs secret_code for release
	const buyerPriv = secp.utils.randomSecretKey();
	const buyerPub = secp.getPublicKey(buyerPriv, true);
	const buyerXonly = buyerPub.slice(1);

	const secretCode = 'release-secret-xyz';
	const msgHash = sha256(new TextEncoder().encode(secretCode));
	const releaseSig = secp.schnorr.sign(msgHash, buyerPriv);

	// Backend verifies
	const valid = secp.schnorr.verify(releaseSig, msgHash, buyerXonly);
	assert(valid, 'Release signature should verify');

	// Simulate: buyer pre-signs "timeout" for refund
	const timeoutHash = sha256(new TextEncoder().encode('timeout'));
	const timeoutSig = secp.schnorr.sign(timeoutHash, buyerPriv);
	const timeoutValid = secp.schnorr.verify(timeoutSig, timeoutHash, buyerXonly);
	assert(timeoutValid, 'Timeout signature should verify');

	// Simulate: buyer signs "dispute"
	const disputeHash = sha256(new TextEncoder().encode('dispute'));
	const disputeSig = secp.schnorr.sign(disputeHash, buyerPriv);
	const disputeValid = secp.schnorr.verify(disputeSig, disputeHash, buyerXonly);
	assert(disputeValid, 'Dispute signature should verify');
});

test('seller and buyer have different keys', () => {
	const sellerPriv = secp.utils.randomSecretKey();
	const buyerPriv = secp.utils.randomSecretKey();
	const sellerPub = hex.encode(secp.getPublicKey(sellerPriv, true));
	const buyerPub = hex.encode(secp.getPublicKey(buyerPriv, true));
	assert(sellerPub !== buyerPub, 'Seller and buyer should have different pubkeys');
});

// ── Results ───────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total\n`);
process.exit(failed > 0 ? 1 : 0);
