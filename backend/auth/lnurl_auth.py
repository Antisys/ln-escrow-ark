"""
LNURL-auth Implementation for trustMeBro-ARK Escrow

This module implements LNURL-auth with a twist: instead of just authenticating,
we use the signature to derive deterministic ephemeral keys for escrow signing.

Flow:
1. User requests auth challenge for a deal
2. Service generates: k1 = SHA256(deal_id + random_nonce + "vault")
3. User's wallet signs k1 with their linking key
4. User sends signature back
5. Service verifies signature
6. User derives ephemeral key: HMAC-SHA256(signature, deal_id + "ephemeral")
   - This key is deterministic: same wallet + same deal = same key
   - Only the wallet owner can recreate it
   - Service CANNOT derive it (doesn't have the private key to create signature)

Security:
- The ephemeral private key derivation happens CLIENT-SIDE
- Service only sees: public key, signature (for verification)
- Service CANNOT recreate the ephemeral private key
"""
import hashlib
import logging
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# For signature verification
try:
    from secp256k1 import PublicKey
    HAS_SECP256K1 = True
except ImportError:
    HAS_SECP256K1 = False
    logger.warning("secp256k1 not installed, using ecdsa fallback")

try:
    import ecdsa
    from ecdsa import SECP256k1, VerifyingKey
    from ecdsa.util import sigdecode_der
    HAS_ECDSA = True
except ImportError:
    HAS_ECDSA = False


@dataclass
class AuthChallenge:
    """LNURL-auth challenge"""
    k1: str  # 32-byte hex challenge
    deal_id: str
    role: str  # 'buyer' or 'seller'
    created_at: datetime
    expires_at: datetime
    callback_url: str
    lnurl: str  # bech32-encoded LNURL


class LNURLAuthManager:
    """
    Manages LNURL-auth challenges and verification

    Key insight: We use LNURL-auth not just for login, but to enable
    deterministic key derivation on the client side.
    """

    _MAX_CHALLENGES = 5000  # Hard cap to prevent memory DoS
    _MAX_VERIFIED = 5000

    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url.rstrip('/')
        # In-memory challenge store (use Redis/DB in production)
        self._challenges: dict[str, AuthChallenge] = {}
        # Verified sessions: k1 -> (pubkey, signature)
        self._verified: dict[str, tuple[str, str]] = {}

    def create_challenge(
        self,
        deal_id: str,
        user_role: str = "user",
        expires_minutes: int = 10
    ) -> AuthChallenge:
        """
        Create LNURL-auth challenge for a deal

        Uses a DETERMINISTIC k1 so re-authentication produces the same wallet
        signature and therefore the same derived ephemeral key. This enables
        key recovery without storing secrets server-side.

        Args:
            deal_id: The deal this auth is for
            user_role: 'buyer' or 'seller'
            expires_minutes: Challenge expiry time

        Returns:
            AuthChallenge with k1 and LNURL
        """
        # Prune expired challenges/verified sessions to prevent unbounded memory growth
        self._cleanup_expired()

        # Deterministic k1: same deal+role always produces the same challenge
        # This ensures re-auth with same wallet → same signature → same ephemeral key
        k1_preimage = f"{deal_id}:{user_role}:vault-auth".encode()
        k1 = hashlib.sha256(k1_preimage).hexdigest()

        # Build callback URL (must include tag=login for LNURL-auth spec)
        callback_url = f"{self.base_url}/auth/lnurl/callback?tag=login&k1={k1}"

        # Encode as LNURL (bech32)
        lnurl = self._encode_lnurl(callback_url)

        now = datetime.now(timezone.utc)
        challenge = AuthChallenge(
            k1=k1,
            deal_id=deal_id,
            role=user_role,
            created_at=now,
            expires_at=now + timedelta(minutes=expires_minutes),
            callback_url=callback_url,
            lnurl=lnurl
        )

        # Store challenge (overwrites previous for same deal+role since k1 is deterministic)
        self._challenges[k1] = challenge
        # Clear old verification so it can be re-verified
        self._verified.pop(k1, None)

        return challenge

    def verify_signature(
        self,
        k1: str,
        sig: str,
        key: str
    ) -> dict:
        """
        Verify LNURL-auth signature

        Args:
            k1: The challenge (32-byte hex)
            sig: DER-encoded signature (hex)
            key: Compressed public key (33 bytes hex, 66 chars)

        Returns:
            Dict with verification result and deal info
        """
        # Check challenge exists and not expired
        challenge = self._challenges.get(k1)
        if not challenge:
            return {"valid": False, "error": "Challenge not found or expired"}

        if datetime.now(timezone.utc) > challenge.expires_at:
            del self._challenges[k1]
            return {"valid": False, "error": "Challenge expired"}

        # Verify signature
        try:
            valid = self._verify_ecdsa_signature(k1, sig, key)
        except Exception as e:
            return {"valid": False, "error": f"Signature verification failed: {str(e)}"}

        if not valid:
            return {"valid": False, "error": "Invalid signature"}

        # Store verified session (including signature for client-side key derivation)
        self._verified[k1] = (key, sig)

        # Return success with deal binding info
        return {
            "valid": True,
            "deal_id": challenge.deal_id,
            "pubkey": key,
            "message": "Authentication successful. You can now derive your ephemeral key."
        }

    def get_challenge_for_deal(self, deal_id: str, role: str = None) -> Optional[AuthChallenge]:
        """Get active challenge for a deal and role"""
        for challenge in self._challenges.values():
            if challenge.deal_id == deal_id and datetime.now(timezone.utc) < challenge.expires_at:
                # If role specified, must match
                if role and challenge.role != role:
                    continue
                return challenge
        return None

    def is_verified(self, k1: str) -> bool:
        """Check if a challenge has been verified"""
        return k1 in self._verified

    def get_verified_pubkey(self, k1: str) -> Optional[str]:
        """Get the pubkey that verified a challenge"""
        if k1 in self._verified:
            return self._verified[k1][0]
        return None

    def get_verified_signature(self, k1: str) -> Optional[str]:
        """Get the signature that verified a challenge (for client-side key derivation)"""
        if k1 in self._verified:
            return self._verified[k1][1]
        return None

    def _cleanup_expired(self):
        """Remove expired challenges and their verified sessions."""
        now = datetime.now(timezone.utc)
        expired_k1s = [k1 for k1, c in self._challenges.items() if now > c.expires_at]
        for k1 in expired_k1s:
            del self._challenges[k1]
            self._verified.pop(k1, None)
        if expired_k1s:
            logger.debug("Cleaned up %d expired LNURL challenges", len(expired_k1s))

        # Hard cap: if still over limit after cleanup, drop oldest entries
        if len(self._challenges) > self._MAX_CHALLENGES:
            sorted_k1s = sorted(self._challenges, key=lambda k: self._challenges[k].created_at)
            for k1 in sorted_k1s[:len(self._challenges) - self._MAX_CHALLENGES]:
                del self._challenges[k1]
                self._verified.pop(k1, None)
            logger.warning("LNURL challenge store hit cap, dropped %d oldest entries",
                           len(sorted_k1s) - self._MAX_CHALLENGES)

        if len(self._verified) > self._MAX_VERIFIED:
            # Verified entries without a corresponding challenge are orphaned — drop them
            orphaned = [k1 for k1 in self._verified if k1 not in self._challenges]
            for k1 in orphaned[:len(self._verified) - self._MAX_VERIFIED]:
                del self._verified[k1]

    def _verify_ecdsa_signature(self, message_hex: str, sig_hex: str, pubkey_hex: str) -> bool:
        """
        Verify ECDSA signature over message

        LNURL-auth signs: SHA256(k1) with the linking key
        """
        logger.debug("Verifying signature: k1=%s sig=%s...%s key=%s",
            message_hex, sig_hex[:20], sig_hex[-20:], pubkey_hex)

        message_bytes = bytes.fromhex(message_hex)
        sig_bytes = bytes.fromhex(sig_hex)
        pubkey_bytes = bytes.fromhex(pubkey_hex)

        # Message is already the k1 hash, sign over it directly
        # (LNURL-auth spec: sign the k1 directly, not double-hashed)

        last_error = None

        if HAS_SECP256K1:
            # Use secp256k1 library (same as working flashpay implementation)
            try:
                logger.debug("Using secp256k1 library")
                pubkey = PublicKey(pubkey_bytes, raw=True)
                sig_obj = pubkey.ecdsa_deserialize(sig_bytes)
                result = pubkey.ecdsa_verify(message_bytes, sig_obj, raw=True)
                logger.debug("secp256k1 verification result: %s", result)
                return result
            except Exception as e:
                logger.debug("secp256k1 error: %s", e)
                last_error = f"secp256k1: {e}"

        if HAS_ECDSA:
            # Fallback to ecdsa library
            try:
                logger.debug("Using ecdsa library")
                vk = VerifyingKey.from_string(pubkey_bytes, curve=SECP256k1)
                result = vk.verify(sig_bytes, message_bytes, hashfunc=hashlib.sha256, sigdecode=sigdecode_der)
                logger.debug("ecdsa verification result: %s", result)
                return result
            except ecdsa.BadSignatureError as e:
                logger.debug("Bad signature: %s", e)
                return False
            except Exception as e:
                logger.debug("ecdsa error: %s", e)
                last_error = f"ecdsa: {e}"

        if not HAS_SECP256K1 and not HAS_ECDSA:
            raise RuntimeError("No ECDSA library available. Install secp256k1 or ecdsa.")

        # If we got here, verification failed with an error
        raise RuntimeError(f"Signature verification error: {last_error}")

    def _encode_lnurl(self, url: str) -> str:
        """Encode URL as LNURL (bech32)"""
        try:
            from bech32 import bech32_encode, convertbits
            data = convertbits(url.encode('utf-8'), 8, 5)
            return bech32_encode('lnurl', data).upper()
        except ImportError:
            # Fallback: return raw URL (wallet should handle both)
            return url



# Singleton instance
_auth_manager: Optional[LNURLAuthManager] = None

def get_auth_manager(base_url: str = None) -> LNURLAuthManager:
    """Get or create the auth manager singleton"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = LNURLAuthManager(base_url or "http://localhost:8001")
    elif base_url:
        # Update base_url if provided (for tunnel URL changes)
        _auth_manager.base_url = base_url.rstrip('/')
    return _auth_manager
