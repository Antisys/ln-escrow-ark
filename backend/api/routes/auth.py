"""
LNURL-auth API endpoints

Provides wallet-based authentication with deterministic key derivation.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Query, Request
from pydantic import BaseModel, Field

from backend.auth.lnurl_auth import get_auth_manager
from backend.database import deal_storage
from backend.config import CONFIG

logger = logging.getLogger(__name__)
router = APIRouter()

# Statuses where the deal is finished and key mismatches don't matter
_TERMINAL_STATUSES = {'completed', 'refunded', 'expired', 'cancelled', 'released'}


# ============================================================================
# Request/Response Models
# ============================================================================

class AuthChallengeResponse(BaseModel):
    """LNURL-auth challenge response"""
    k1: str = Field(..., description="32-byte hex challenge")
    lnurl: str = Field(..., description="LNURL for wallet scanning")
    callback_url: str = Field(..., description="Callback URL")
    deal_id: str
    expires_in_seconds: int
    qr_content: str = Field(..., description="Content for QR code (LNURL)")


class DeriveKeyRequest(BaseModel):
    """Request to register derived ephemeral pubkey"""
    k1: str = Field(..., min_length=64, max_length=64, description="Challenge k1")
    user_id: str = Field(..., description="User identifier")
    ephemeral_pubkey: str = Field(..., min_length=66, max_length=66, description="Derived pubkey")
    timeout_signature: str | None = Field(None, description="Pre-signed SHA256('timeout') for delegated timeout claims")


# ============================================================================
# LNURL-auth Endpoints
# ============================================================================

@router.get("/lnurl/challenge/{deal_token}")
async def create_auth_challenge(
    deal_token: str,
    role: str = Query("buyer", regex="^(buyer|seller)$")
) -> AuthChallengeResponse:
    """
    Create LNURL-auth challenge for a deal

    User scans the LNURL QR code with their Lightning wallet.
    The wallet will sign the challenge and call back to verify.

    Args:
        deal_token: Deal link token
        role: 'buyer' or 'seller'

    Returns:
        Challenge with LNURL for wallet
    """
    # Verify deal exists
    deal = deal_storage.get_deal_by_token(deal_token)
    if not deal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deal not found"
        )

    # Track when buyer starts the join process (first time they request challenge)
    if role == 'buyer' and not deal.get('buyer_started_at'):
        deal_storage.update_deal(deal_id=deal['deal_id'], buyer_started_at=datetime.now(timezone.utc))

    # Use LNURL_BASE_URL env var for mobile wallet access (must be reachable from phone)
    base_url = CONFIG.lnurl_base_url
    auth_manager = get_auth_manager(base_url)

    # Check if there's an active challenge for this deal+role
    # (prevent challenge spam)
    existing = auth_manager.get_challenge_for_deal(deal['deal_id'], role=role)
    if existing:
        expires_in = max(0, int((existing.expires_at - datetime.now(timezone.utc)).total_seconds()))
        return AuthChallengeResponse(
            k1=existing.k1,
            lnurl=existing.lnurl,
            callback_url=existing.callback_url,
            deal_id=deal['deal_id'],
            expires_in_seconds=expires_in,
            qr_content=existing.lnurl
        )

    # Create new challenge
    challenge = auth_manager.create_challenge(
        deal_id=deal['deal_id'],
        user_role=role,
        expires_minutes=10
    )

    return AuthChallengeResponse(
        k1=challenge.k1,
        lnurl=challenge.lnurl,
        callback_url=challenge.callback_url,
        deal_id=deal['deal_id'],
        expires_in_seconds=600,
        qr_content=challenge.lnurl
    )


@router.get("/lnurl/callback")
async def lnurl_callback(
    k1: str = Query(..., min_length=64, max_length=64),
    sig: str = Query(..., min_length=100),
    key: str = Query(..., min_length=66, max_length=66)
) -> dict:
    """
    LNURL-auth callback (called by wallet)

    This is the standard LNURL-auth callback endpoint.
    Wallet sends: k1, sig, key

    Returns:
        {"status": "OK"} or {"status": "ERROR", "reason": "..."}
    """
    auth_manager = get_auth_manager()

    result = auth_manager.verify_signature(k1=k1, sig=sig, key=key)

    if result.get("valid"):
        return {"status": "OK"}
    else:
        return {"status": "ERROR", "reason": result.get("error", "Unknown error")}


@router.get("/lnurl/status/{k1}")
async def check_auth_status(k1: str) -> dict:
    """
    Check if a challenge has been verified

    Frontend polls this to know when wallet has completed auth.

    Returns:
        Status, pubkey, and signature if verified
    """
    auth_manager = get_auth_manager()

    if auth_manager.is_verified(k1):
        pubkey = auth_manager.get_verified_pubkey(k1)
        signature = auth_manager.get_verified_signature(k1)
        return {
            "verified": True,
            "pubkey": pubkey,
            "signature": signature,  # For client-side ephemeral key derivation
            "message": "Ready to derive ephemeral key"
        }

    return {
        "verified": False,
        "message": "Waiting for wallet signature"
    }


@router.post("/lnurl/register-derived-key")
async def register_derived_key(request: Request, body: DeriveKeyRequest) -> dict:
    """
    Register the derived ephemeral pubkey

    After LNURL-auth verification, user derives their ephemeral key
    client-side and registers the PUBLIC key here.

    The derivation is: HMAC-SHA256(signature, deal_id + "ephemeral")
    Only the user can derive the private key, we only store the pubkey.

    Args:
        body: k1, user_id, and derived ephemeral_pubkey

    Returns:
        Registration status
    """
    auth_manager = get_auth_manager()

    # Verify the challenge was authenticated
    if not auth_manager.is_verified(body.k1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Challenge not verified. Complete LNURL-auth first."
        )

    # Get the verified linking pubkey
    linking_pubkey = auth_manager.get_verified_pubkey(body.k1)

    # Get the challenge to find the deal
    challenge = None
    for c in auth_manager._challenges.values():
        if c.k1 == body.k1:
            challenge = c
            break

    if not challenge:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Challenge expired"
        )

    deal = deal_storage.get_deal_by_id(challenge.deal_id)
    if not deal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deal not found"
        )

    # Use role from challenge (set when LNURL was created)
    role = challenge.role

    logger.info("register-derived-key: deal=%s role=%s linking_pk=%s ephemeral_pk=%s",
                challenge.deal_id[:8], role, linking_pubkey[:16], body.ephemeral_pubkey[:16])

    # RECOVERY: same wallet (deterministic k1) re-derives the same ephemeral key.
    # No auth_signature needed — k1 is SHA256(deal_id + role + "vault-auth"),
    # so same wallet always produces the same signature → same derived key.
    # Return encrypted_vault so frontend can decrypt the secret_code.
    if deal.get('funded_at') and deal.get(f'{role}_linking_pubkey') == linking_pubkey:
        logger.info("Key recovery for %s on deal %s (deterministic k1, same wallet)", role, deal['deal_id'][:8])
        if deal.get(f'{role}_id') != body.user_id:
            deal_storage.update_deal(deal_id=deal['deal_id'], **{f'{role}_id': body.user_id})

        # Dual-role: if same wallet holds both roles, tell frontend
        other_role = 'buyer' if role == 'seller' else 'seller'
        other_role_info = None
        if deal.get(f'{other_role}_linking_pubkey') == linking_pubkey:
            other_role_info = other_role
            if deal.get(f'{other_role}_id') != body.user_id:
                deal_storage.update_deal(deal_id=deal['deal_id'], **{f'{other_role}_id': body.user_id})

        return {
            "success": True,
            "deal_id": challenge.deal_id,
            "role": role,
            "recovery": True,
            "encrypted_vault": deal.get('buyer_encrypted_vault'),
            "other_role_recovery": other_role_info,
            "ephemeral_pubkey_registered": True,
            "linking_pubkey": linking_pubkey,
            "ready_for_funding": False,
            "message": "Key recovered via deterministic challenge."
        }

    # Funded deal but different wallet — reject
    if deal.get('funded_at') and deal.get(f'{role}_linking_pubkey') and deal.get(f'{role}_linking_pubkey') != linking_pubkey:
        if deal.get('status') not in _TERMINAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot recover key: different wallet. "
                       "Use the same Lightning wallet you originally signed in with."
            )

    # Update user_id for the role if not already set
    # For terminal deals, skip linking key mismatch checks (user may sign in with different wallet to view)
    is_terminal = deal.get('status') in _TERMINAL_STATUSES
    if role == 'seller':
        if not deal.get('seller_id'):
            deal_storage.update_deal(deal_id=deal['deal_id'], seller_id=body.user_id)
        # Allow re-registration with same linking key (e.g., browser refresh)
        elif not is_terminal and deal.get('seller_linking_pubkey') and deal.get('seller_linking_pubkey') != linking_pubkey:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seller already registered with different key"
            )
    elif role == 'buyer':
        if not deal.get('buyer_id'):
            deal_storage.update_deal(deal_id=deal['deal_id'], buyer_id=body.user_id)
        elif not is_terminal and deal.get('buyer_linking_pubkey') and deal.get('buyer_linking_pubkey') != linking_pubkey:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Buyer already registered with different key"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {role}"
        )

    # Store the derived pubkey and linking pubkey.
    # NOTE: auth_signature is intentionally NOT stored — it would let the server
    # compute the user's ephemeral private key (custodial hole). Recovery works
    # via deterministic k1: same wallet → same sig → same derived key.
    update_data = {
        f'{role}_pubkey': body.ephemeral_pubkey,
        f'{role}_linking_pubkey': linking_pubkey,
        f'{role}_auth_verified': True,
    }
    # Non-custodial: store pre-signed timeout authorization (verify before storing)
    if body.timeout_signature:
        from backend.auth.schnorr_verify import verify_timeout_signature
        if not verify_timeout_signature(body.ephemeral_pubkey, body.timeout_signature):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid timeout signature — does not match ephemeral pubkey"
            )
        update_data[f'{role}_timeout_signature'] = body.timeout_signature
    deal_storage.update_deal(deal_id=deal['deal_id'], **update_data)

    # Re-fetch deal to get updated data
    deal = deal_storage.get_deal_by_id(challenge.deal_id)

    # Check if both parties have registered keys — if so, activate the deal
    both_registered = deal.get('seller_pubkey') and deal.get('buyer_pubkey')
    if both_registered and deal.get('status') not in _TERMINAL_STATUSES:
        if deal['status'] == 'pending':
            deal_storage.update_deal(deal_id=deal['deal_id'], status='active')

    return {
        "success": True,
        "deal_id": challenge.deal_id,
        "role": role,
        "ephemeral_pubkey_registered": True,
        "linking_pubkey": linking_pubkey,
        "ready_for_funding": both_registered or False,
        "message": "Ephemeral key registered." + (" Both parties ready — proceed to funding!" if both_registered else " Waiting for other party.")
    }


# ============================================================================
# Info Endpoint
# ============================================================================

@router.get("/lnurl/info")
async def lnurl_info() -> dict:
    """
    LNURL-auth info and capabilities

    Returns info about the auth system for client integration.
    """
    return {
        "type": "lnurl-auth",
        "tag": "login",
        "description": "trustMeBro-ARK LNURL-auth with ephemeral key derivation",
        "features": [
            "Standard LNURL-auth (LUD-04)",
            "Deterministic ephemeral key derivation",
            "Key recovery via wallet re-authentication"
        ],
        "key_derivation": {
            "method": "HMAC-SHA256",
            "inputs": ["lnurl_signature", "deal_id", "constant"],
            "note": "Derivation happens client-side. Server only sees pubkey."
        },
        "endpoints": {
            "challenge": "GET /auth/lnurl/challenge/{deal_token}?role=buyer|seller",
            "login": "GET /auth/lnurl/login (global login, not deal-specific)",
            "callback": "GET /auth/lnurl/callback?k1=...&sig=...&key=...",
            "status": "GET /auth/lnurl/status/{k1}",
            "register": "POST /auth/lnurl/register-derived-key",
            "my_deals": "GET /auth/lnurl/my-deals/{k1}"
        }
    }


# ============================================================================
# Global Login (not deal-specific)
# ============================================================================

@router.get("/lnurl/login")
async def create_login_challenge() -> dict:
    """
    Create LNURL-auth challenge for global login (not tied to a specific deal)

    Used to recover past deals or just authenticate the user.
    """
    base_url = CONFIG.lnurl_base_url
    auth_manager = get_auth_manager(base_url)

    # Create challenge with special "login" deal_id
    challenge = auth_manager.create_challenge(
        deal_id="__global_login__",
        user_role="user",
        expires_minutes=10
    )

    return {
        "k1": challenge.k1,
        "lnurl": challenge.lnurl,
        "callback_url": challenge.callback_url,
        "expires_in_seconds": 600,
        "qr_content": challenge.lnurl
    }


@router.get("/lnurl/my-deals/{k1}")
async def get_my_deals(k1: str) -> dict:
    """
    Get all deals for the authenticated user (by linking pubkey)

    User must have completed LNURL-auth first.
    Returns all deals where user is buyer or seller.
    """
    auth_manager = get_auth_manager()

    if not auth_manager.is_verified(k1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Complete LNURL-auth first."
        )

    linking_pubkey = auth_manager.get_verified_pubkey(k1)

    # Find all deals for this user
    deals = deal_storage.find_deals_by_linking_pubkey(linking_pubkey)

    return {
        "linking_pubkey": linking_pubkey,
        "deal_count": len(deals),
        "deals": deals
    }


# ============================================================================
# Admin LNURL-auth
# ============================================================================

@router.get("/lnurl/admin/challenge")
async def create_admin_challenge() -> dict:
    """
    Create LNURL-auth challenge for admin login

    Admin authenticates with their Lightning wallet.
    Their linking pubkey must match one in the admin_pubkeys config.
    """
    base_url = CONFIG.lnurl_base_url
    auth_manager = get_auth_manager(base_url)

    # Create challenge with special "admin" deal_id
    challenge = auth_manager.create_challenge(
        deal_id="__admin_login__",
        user_role="admin",
        expires_minutes=10
    )

    return {
        "k1": challenge.k1,
        "lnurl": challenge.lnurl,
        "callback_url": challenge.callback_url,
        "expires_in_seconds": 600,
        "qr_content": challenge.lnurl
    }


@router.get("/lnurl/admin/status/{k1}")
async def check_admin_status(k1: str) -> dict:
    """
    Check if admin challenge has been verified and if user is admin

    Returns admin status and session info if verified.
    """
    auth_manager = get_auth_manager()

    if not auth_manager.is_verified(k1):
        return {
            "verified": False,
            "is_admin": False,
            "message": "Waiting for wallet signature"
        }

    linking_pubkey = auth_manager.get_verified_pubkey(k1)

    # Check if pubkey is in admin list
    admin_pubkeys = CONFIG.admin_pubkeys or []
    is_admin = linking_pubkey in admin_pubkeys

    # Also allow if admin_api_key is set and this is first admin (bootstrap)
    if not is_admin and CONFIG.admin_api_key and len(admin_pubkeys) == 0:
        # First admin bootstrap - allow and suggest adding to config
        is_admin = True

    return {
        "verified": True,
        "is_admin": is_admin,
        "linking_pubkey": linking_pubkey,
        "message": "Admin authenticated" if is_admin else "Not an admin. Add your pubkey to admin_pubkeys config."
    }
