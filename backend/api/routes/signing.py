"""
Signing endpoints: signing-status (read-only).

Key registration is handled by /auth/lnurl/register-derived-key which
requires LNURL-auth verification. The old unauthenticated register-key
endpoint has been removed (security: accepted self-reported user_id).
"""
import logging
from fastapi import APIRouter, HTTPException, status

from backend.database import deal_storage

from backend.api.routes._shared import (
    SigningStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{deal_id}/signing-status", response_model=SigningStatusResponse)
async def get_signing_status(deal_id: str):
    """Get the current signing phase status for a deal (Ark mode)."""
    deal = deal_storage.get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deal not found"
        )

    seller_key_registered = bool(deal.get('seller_pubkey'))
    buyer_key_registered = bool(deal.get('buyer_pubkey'))

    # Ark mode: funded only when deal status is funded/shipped/beyond
    # (escrow_id is stored at invoice-creation time, so it existing ≠ payment received)
    funded_statuses = {'funded', 'shipped', 'completed', 'released', 'disputed', 'releasing', 'refunding', 'refunded', 'expired'}
    ark_funded = deal.get('status') in funded_statuses and bool(deal.get('ark_escrow_deal_id'))
    return SigningStatusResponse(
        deal_id=deal_id,
        phase="funded" if ark_funded else (
            "awaiting_funding" if (seller_key_registered and buyer_key_registered)
            else "awaiting_keys"
        ),
        buyer_pubkey_registered=buyer_key_registered,
        seller_pubkey_registered=seller_key_registered,
        ready_for_funding=seller_key_registered and buyer_key_registered,
        ready_for_resolution=ark_funded,
        # Use escrow_id as funding_txid so the frontend knows when the deal is funded
        funding_txid=deal.get('ark_escrow_deal_id') if ark_funded else None,
    )
