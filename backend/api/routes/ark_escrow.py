"""
Ark-specific escrow endpoints for Arkana.

POST /deals/{deal_id}/create-escrow   → Create Ark escrow VTXO for the deal
POST /deals/{deal_id}/confirm-funding → Confirm VTXO has been funded
"""
import logging
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from backend.ark.ark_service import ArkEscrowService
from backend.database import deal_storage

logger = logging.getLogger(__name__)
router = APIRouter()


class SetPubkeyRequest(BaseModel):
    pubkey: str
    role: str  # "buyer" or "seller"


@router.post("/{deal_id}/set-pubkey")
async def set_pubkey(deal_id: str, body: SetPubkeyRequest):
    """Set buyer or seller pubkey on a deal (called before create-escrow)."""
    deal = deal_storage.get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if body.role == 'buyer':
        deal_storage.update_deal(deal_id=deal_id, buyer_pubkey=body.pubkey)
    elif body.role == 'seller':
        deal_storage.update_deal(deal_id=deal_id, seller_pubkey=body.pubkey)
    else:
        raise HTTPException(status_code=400, detail="role must be 'buyer' or 'seller'")

    return {"status": "ok", "role": body.role, "pubkey": body.pubkey[:16] + "..."}


class CreateEscrowResponse(BaseModel):
    deal_id: str
    escrow_deal_id: str
    escrow_pubkey: str
    escrow_address: str
    tapscripts: list[str]


class ConfirmFundingRequest(BaseModel):
    vtxo_txid: str
    vtxo_vout: int = 0
    secret_code_hash: Optional[str] = None  # SHA256(secret_code) from buyer


class ConfirmFundingResponse(BaseModel):
    deal_id: str
    status: str


@router.post("/{deal_id}/create-escrow", response_model=CreateEscrowResponse)
async def create_escrow(deal_id: str):
    """
    Create an Ark escrow deal for the given deal.
    Requires both buyer_pubkey and seller_pubkey to be set.
    Returns the escrow address where the buyer should send funds.
    """
    deal = deal_storage.get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if deal['status'] not in ('pending', 'active'):
        raise HTTPException(status_code=409, detail=f"Deal status is {deal['status']}, expected pending/active")

    buyer_pub = deal.get('buyer_pubkey')
    seller_pub = deal.get('seller_pubkey')
    if not buyer_pub or not seller_pub:
        raise HTTPException(status_code=400, detail="Both buyer and seller must join before creating escrow")

    # Check if escrow already exists
    existing = deal.get('ark_escrow_deal_id')
    if existing:
        try:
            ark = ArkEscrowService()
            info = await ark.get_escrow_info(existing)
            return CreateEscrowResponse(
                deal_id=deal_id,
                escrow_deal_id=existing,
                escrow_pubkey=info.escrow_pubkey,
                escrow_address=info.address,
                tapscripts=[],
            )
        except Exception:
            pass  # Escrow not found, create new

    try:
        ark = ArkEscrowService()
        result = await ark.create_deal_escrow(
            amount_sats=deal['price_sats'],
            secret_code_hash='',  # Will be set by buyer at funding time
            timeout_hours=deal.get('timeout_hours', 24),
            timeout_action=deal.get('timeout_action', 'refund'),
            seller_pubkey=seller_pub,
            buyer_pubkey=buyer_pub,
        )

        escrow_id = result['deal_id']
        escrow_address = result['address']
        escrow_pubkey = result['escrow_pubkey']
        tapscripts = result.get('tapscripts', [])

        # Store escrow info in deal
        deal_storage.update_deal(
            deal_id=deal_id,
            ark_escrow_deal_id=escrow_id,
            ark_escrow_address=escrow_address,
            ark_timeout_block=result.get('timeout_block', 0),
        )

        # Transition deal to active
        if deal['status'] == 'pending':
            deal_storage.update_deal(deal_id=deal_id, status='active')

        logger.info("Escrow created for deal %s: escrow_id=%s", deal_id, escrow_id)

        return CreateEscrowResponse(
            deal_id=deal_id,
            escrow_deal_id=escrow_id,
            escrow_pubkey=escrow_pubkey,
            escrow_address=escrow_address,
            tapscripts=tapscripts,
        )

    except Exception as e:
        logger.error("Failed to create escrow for deal %s: %s", deal_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to create escrow: {str(e)}")


@router.post("/{deal_id}/confirm-funding", response_model=ConfirmFundingResponse)
async def confirm_funding(deal_id: str, body: ConfirmFundingRequest):
    """
    Confirm that the escrow VTXO has been funded.
    Called by the frontend after the wallet sends to the escrow address.
    """
    deal = deal_storage.get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if deal['status'] not in ('pending', 'active'):
        raise HTTPException(status_code=409, detail=f"Deal already in status {deal['status']}")

    escrow_id = deal.get('ark_escrow_deal_id')
    if not escrow_id:
        raise HTTPException(status_code=400, detail="No escrow created for this deal. Call create-escrow first.")

    try:
        # Notify the Ark escrow agent that the deal is funded
        ark = ArkEscrowService()
        await ark.client.fund_escrow(escrow_id, body.vtxo_txid, body.vtxo_vout)
    except Exception as e:
        logger.warning("Ark escrow fund notification failed (non-fatal): %s", e)

    # Mark deal as funded
    from backend.database.deal_storage import set_deal_funded
    set_deal_funded(deal_id)
    update_fields = dict(
        ark_vtxo_txid=body.vtxo_txid,
        ark_vtxo_vout=body.vtxo_vout,
    )
    if body.secret_code_hash:
        update_fields['ark_secret_code_hash'] = body.secret_code_hash
    deal_storage.update_deal(deal_id=deal_id, **update_fields)

    logger.info("Deal %s funded: vtxo=%s:%d", deal_id, body.vtxo_txid, body.vtxo_vout)

    return ConfirmFundingResponse(deal_id=deal_id, status="funded")
