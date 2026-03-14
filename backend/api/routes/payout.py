"""
Payout endpoints: ship, submit-payout-invoice, validate-lightning-address.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.database import deal_storage
from backend.database.models import DealStatus

from backend.api.routes._shared import (
    _ws_notify, deal_to_response, _verify_deal_signature,
    ShipDealRequest, SubmitPayoutInvoiceRequest,
    DealResponse,
)
from backend.api.routes._payout import validate_lightning_address

logger = logging.getLogger(__name__)

router = APIRouter()


class ValidateAddressRequest(BaseModel):
    address: str
    amount_sats: int = Field(gt=0)


@router.post("/validate-lightning-address")
async def validate_address(body: ValidateAddressRequest):
    """Validate a Lightning Address without requiring auth. Used during create/join flow."""
    await validate_lightning_address(body.address, body.amount_sats)
    return {"valid": True}


@router.post("/{deal_id}/ship", response_model=DealResponse)
async def ship_deal(deal_id: str, body: ShipDealRequest):
    """Seller marks deal as shipped"""
    deal = deal_storage.get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

    if deal['seller_id'] != body.seller_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only seller can mark as shipped")

    _verify_deal_signature(deal, 'seller', 'ship', body.timestamp, body.signature, deal_id)

    if deal['status'] != DealStatus.FUNDED.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot ship deal in status: {deal['status']}")

    if deal['requires_tracking'] and not body.tracking_number:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tracking number required for this deal")

    updated_deal = deal_storage.set_deal_shipped(
        deal_id=deal_id,
        tracking_carrier=body.tracking_carrier,
        tracking_number=body.tracking_number,
        shipping_notes=body.shipping_notes
    )
    await _ws_notify(deal_id, 'deal:shipped')

    return deal_to_response(updated_deal)


@router.post("/{deal_id}/submit-payout-invoice")
async def submit_payout_invoice(deal_id: str, body: SubmitPayoutInvoiceRequest):
    """Seller submits a Lightning Address for receiving payout on release."""
    deal = deal_storage.get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

    if deal['seller_id'] != body.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the seller can submit a payout invoice")

    _verify_deal_signature(deal, 'seller', 'submit-payout-invoice', body.timestamp, body.signature, deal_id)

    if deal['status'] in ['refunded', 'cancelled']:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot submit payout invoice for deal in status: {deal['status']}")

    # Block update if payout already succeeded or is currently in-flight.
    if deal.get('release_txid') and deal.get('payout_status') == 'paid':
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot change payout invoice — funds have already been sent."
        )
    if deal.get('payout_status') == 'pending' or deal['status'] in ['releasing']:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot change payout invoice while payment is in progress."
        )

    invoice = body.invoice.strip()
    await validate_lightning_address(invoice, deal['price_sats'])

    deal_storage.update_deal(deal_id, seller_payout_invoice=invoice)
    await _ws_notify(deal_id, 'deal:payout_invoice')

    logger.info("Seller payout Lightning Address saved for deal %s", deal_id)

    # FUND-LOCK FIX: If deal expired with timeout_action='release' but had no seller invoice,
    # the timeout handler marked it 'expired' with payout_status=NULL and no release_txid.
    # Now that the seller submitted an invoice, trigger a full timeout claim+pay.
    if (deal.get('status') == 'expired'
          and deal.get('timeout_action') == 'release'
          and deal.get('ark_escrow_deal_id')
          and not deal.get('release_txid')
          and not deal.get('payout_status')):
        # Set payout_status='failed' so execute_ark_payout's retry guard works correctly
        deal_storage.update_deal(deal_id, payout_status='failed')
        logger.info("Expired deal %s: seller submitted invoice, triggering timeout release", deal_id[:8])
        try:
            from backend.api.routes._payout import execute_ark_payout
            deal_fresh = deal_storage.get_deal_by_id(deal_id)
            await execute_ark_payout(
                deal=deal_fresh,
                payout_type="release",
                ws_complete_event='deal:timeout_released',
                timeout_claim=True,
            )
        except Exception as e:
            logger.warning("Auto timeout release after invoice submit failed for deal %s: %s", deal_id, e)
            # payout_status is now 'failed' (set by execute_ark_payout on error),
            # so the stalled payout retry handler will pick it up.

    return {
        "success": True,
        "deal_id": deal_id,
        "type": "lightning_address",
        "message": "Payout destination saved",
    }
