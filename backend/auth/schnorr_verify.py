"""
BIP-340 Schnorr signature verification for non-custodial escrow operations.

Verifies signatures produced by the frontend's @noble/curves/secp256k1 schnorr.sign().
Uses the secp256k1 Python binding for verification.
"""
import hashlib
import logging

logger = logging.getLogger(__name__)


def verify_timeout_signature(pubkey_hex: str, signature_hex: str) -> bool:
    """
    Verify BIP-340 Schnorr signature over SHA256("timeout").

    Args:
        pubkey_hex: Compressed secp256k1 public key (33 bytes = 66 hex chars)
        signature_hex: BIP-340 Schnorr signature (64 bytes = 128 hex chars)

    Returns:
        True if signature is valid.
    """
    return _verify_schnorr(pubkey_hex, signature_hex, b'timeout')


def verify_dispute_signature(pubkey_hex: str, signature_hex: str) -> bool:
    """Verify BIP-340 Schnorr signature over SHA256("dispute")."""
    return _verify_schnorr(pubkey_hex, signature_hex, b'dispute')


def verify_release_signature(pubkey_hex: str, signature_hex: str, secret_code: str) -> bool:
    """Verify BIP-340 Schnorr signature over SHA256(secret_code)."""
    return _verify_schnorr(pubkey_hex, signature_hex, secret_code.encode('utf-8'))


def _verify_schnorr(pubkey_hex: str, signature_hex: str, preimage: bytes) -> bool:
    """
    Core BIP-340 Schnorr verification.

    The message signed is SHA256(preimage), matching the frontend's
    sha256(new TextEncoder().encode(preimage)) → schnorr.sign(hash, privKey).
    """
    try:
        import secp256k1

        sig_bytes = bytes.fromhex(signature_hex)
        if len(sig_bytes) != 64:
            logger.warning("Schnorr signature wrong length: %d (expected 64)", len(sig_bytes))
            return False

        pubkey_bytes = bytes.fromhex(pubkey_hex)
        if len(pubkey_bytes) != 33:
            logger.warning("Public key wrong length: %d (expected 33)", len(pubkey_bytes))
            return False

        msg = hashlib.sha256(preimage).digest()
        pub = secp256k1.PublicKey(pubkey_bytes, raw=True)
        return pub.schnorr_verify(msg, sig_bytes, b'', raw=True)

    except Exception as e:
        logger.warning("Schnorr verification failed: %s", e)
        return False
