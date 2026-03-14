"""
Signature verification for sensitive deal endpoints.

Requires callers to prove they hold the ephemeral private key that matches
the registered public key, preventing impersonation via stolen user_id strings.
"""
import hashlib
import time
import logging

logger = logging.getLogger(__name__)

# Maximum age of a signature in seconds (5 minutes)
MAX_TIMESTAMP_DRIFT = 300


def verify_action_signature(
    deal_id: str,
    action: str,
    timestamp: int,
    signature_hex: str,
    pubkey_hex: str,
) -> bool:
    """
    Verify a secp256k1 signature over "{deal_id}:{action}:{timestamp}".

    Args:
        deal_id: The deal identifier
        action: Action string (e.g. 'release', 'ship', 'dispute')
        timestamp: Unix seconds when signature was created
        signature_hex: DER-encoded ECDSA signature, hex string
        pubkey_hex: Compressed public key (33 bytes), hex string

    Returns:
        True if signature is valid and timestamp is within allowed drift.

    Raises:
        ValueError: If timestamp is too old/new or signature is invalid.
    """
    # Check timestamp freshness
    now = int(time.time())
    drift = abs(now - timestamp)
    if drift > MAX_TIMESTAMP_DRIFT:
        raise ValueError(f"Timestamp too far from server time ({drift}s drift, max {MAX_TIMESTAMP_DRIFT}s)")

    # Reconstruct signed message
    message = f"{deal_id}:{action}:{timestamp}"
    msg_hash = hashlib.sha256(message.encode("utf-8")).digest()

    # Verify with coincurve
    try:
        from coincurve import PublicKey
        pubkey = PublicKey(bytes.fromhex(pubkey_hex))
        sig_bytes = bytes.fromhex(signature_hex)
        if not pubkey.verify(sig_bytes, msg_hash, hasher=None):
            raise ValueError("Invalid signature")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Signature verification failed: {e}")

    return True
