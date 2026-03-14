"""
Release endpoint: buyer triggers release → Ark escrow release → LN payout to seller.
"""
import asyncio
import hashlib
import logging
from fastapi import APIRouter, HTTPException, status

from backend.database import deal_storage
from backend.database.models import DealStatus

from backend.api.routes._shared import (
    _ws_notify, deal_to_response, _verify_deal_signature,
    ReleaseDealRequest, DealResponse,
)
from backend.api.routes._payout import execute_ark_payout

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{deal_id}/release", response_model=DealResponse)
async def release_deal(deal_id: str, body: ReleaseDealRequest):
    """Buyer releases funds to seller. Claims Ark escrow, pays seller via LN."""
    deal = deal_storage.get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

    if deal['buyer_id'] != body.buyer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only buyer can release funds")

    _verify_deal_signature(deal, 'buyer', 'release', body.timestamp, body.signature, deal_id)

    # Already completed — return success (idempotency)
    if deal.get('payout_status') == 'paid':
        logger.info("Deal %s release: already paid, returning success", deal_id)
        return deal_to_response(deal)

    allowed_statuses = [DealStatus.FUNDED.value, DealStatus.SHIPPED.value, DealStatus.RELEASING.value]
    if deal['status'] == DealStatus.EXPIRED.value and not deal.get('release_txid') and not deal.get('refund_txid'):
        allowed_statuses.append(DealStatus.EXPIRED.value)

    # If deal is still 'active' but the escrow was already created (escrow_id stored at invoice
    # creation time), the funding status update was lost (e.g. check-invoice polling missed the
    # confirmation). Auto-heal: advance to funded so the release can proceed.
    if deal['status'] == DealStatus.ACTIVE.value and deal.get('ark_escrow_deal_id') and deal.get('funded_at'):
        logger.warning(
            "Deal %s in 'active' state but has escrow_id %s and funded_at — auto-advancing to funded",
            deal_id, deal['ark_escrow_deal_id']
        )
        from backend.database.deal_storage import set_deal_funded
        deal = set_deal_funded(deal_id)
        allowed_statuses.append(DealStatus.FUNDED.value)

    if deal['status'] not in allowed_statuses:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot release deal in status: {deal['status']}")

    # If deal requires tracking, buyer cannot release until seller has shipped.
    # This prevents bypassing the shipping requirement entirely.
    if deal.get('requires_tracking') and deal['status'] == DealStatus.FUNDED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seller must provide tracking info before release"
        )

    if deal['status'] == DealStatus.EXPIRED.value and deal.get('timeout_action') != 'release':
        raise HTTPException(status_code=400, detail="Cannot release expired deal — timeout action favors buyer")

    if not deal.get('ark_escrow_deal_id'):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deal has no Ark escrow yet")

    # In Ark mode, seller_pubkey is the payout destination (no LN invoice needed)
    if not deal.get('seller_payout_invoice') and not deal.get('seller_pubkey'):
        raise HTTPException(status_code=400, detail="Seller has no payout destination")

    # COIN SAFETY: block if a refund already claimed the escrow
    if deal.get('refund_txid'):
        raise HTTPException(status_code=409, detail="Escrow already claimed for refund — cannot release")

    # Non-custodial release: buyer MUST provide secret_code from their browser.
    # The service stores only the SHA-256 hash — it cannot release without the buyer's code.
    # Not exposed via to_dict() — fetched directly from the model.
    stored_hash = deal_storage.get_secret_code_hash(deal_id)
    provided_code = body.secret_code
    if not stored_hash:
        # All funded deals created through the proper flow have a hash.
        # Missing hash = data integrity issue — block the release.
        logger.error("Deal %s has no ark_secret_code_hash — cannot verify release", deal_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deal is missing escrow secret hash. Contact support."
        )
    if not provided_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Escrow recovery code required to release funds. "
                   "Check your browser's deal page for the recovery code."
        )
    if hashlib.sha256(provided_code.encode()).hexdigest() != stored_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid escrow recovery code."
        )

    # Kick off the payout in the background so the HTTP response returns immediately.
    # The frontend shows "Releasing Funds..." and waits for a WebSocket notification.
    # execute_ark_payout handles its own status transitions (releasing → completed).
    async def _bg_release():
        try:
            await execute_ark_payout(
                deal=deal,
                payout_type="release",
                raise_on_ln_fail=False,
                ws_complete_event='deal:completed',
                secret_code=provided_code,
                buyer_escrow_signature=body.buyer_escrow_signature,
            )
        except Exception as e:
            logger.error("Background release failed for deal %s: %s", deal_id, e, exc_info=True)

    asyncio.create_task(_bg_release())

    # Return immediately with 'releasing' status — the frontend will poll/WS for completion.
    # Give the background task a moment to transition the status.
    await asyncio.sleep(0.1)
    updated_deal = deal_storage.get_deal_by_id(deal_id)
    return deal_to_response(updated_deal)
