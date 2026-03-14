"""
Funding endpoints: create-ln-invoice, check-ln-invoice.

Ark path: buyer pays LN invoice → e-cash arrives in service's federation wallet
→ service locks it into a Ark escrow → deal becomes funded.

Invoice creation: ark-escrow-agent module ln invoice <msats>
Payment detection: ark-escrow-agent await-invoice <operation_id> (with timeout, non-blocking)
"""
import asyncio
import logging
import re
from typing import Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.database import deal_storage
from backend.database.settings import get_fees

from backend.api.routes._shared import (
    CreateInvoiceResponse, InvoiceStatusResponse,
)
logger = logging.getLogger(__name__)

router = APIRouter()

_SHA256_HEX_RE = re.compile(r'^[0-9a-f]{64}$')

# Per-deal lock to prevent concurrent create-ln-invoice calls from creating
# duplicate escrows (second call would overwrite DB, orphaning the first escrow).
_invoice_create_locks: dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()


async def _get_deal_lock(deal_id: str) -> asyncio.Lock:
    """Get or create a per-deal asyncio lock for invoice creation."""
    async with _locks_lock:
        if deal_id not in _invoice_create_locks:
            _invoice_create_locks[deal_id] = asyncio.Lock()
        return _invoice_create_locks[deal_id]


class CreateInvoiceBody(BaseModel):
    """Request body for create-ln-invoice. The frontend generates secret_code_hash."""
    secret_code_hash: str  # SHA-256 hex of the buyer's secret (64 lowercase hex chars)
    # NON-CUSTODIAL: buyer_pubkey is REQUIRED. Without it, the Ark escrow uses the
    # service's own key as buyer_pubkey, making the service able to claim timeout unilaterally.
    buyer_pubkey: str  # Buyer's ephemeral secp256k1 pubkey (hex, compressed 33-byte)
    # NON-CUSTODIAL: timeout_signature is REQUIRED. This pre-signed authorization lets
    # the service execute timeout claims on behalf of the buyer without holding the buyer's key.
    # Without it, timeout claims fall back to the service's own key (custodial).
    timeout_signature: str  # Pre-signed SHA256("timeout") by buyer (hex, 64-byte BIP-340 Schnorr)
    # Encrypted secret_code for recovery (AES-256-GCM, key derived from ephemeral private key).
    # Server stores opaque blob — cannot decrypt without buyer's wallet.
    encrypted_vault: Optional[str] = None


@router.post("/{deal_id}/create-ln-invoice", response_model=CreateInvoiceResponse)
async def create_lightning_invoice(deal_id: str, body: CreateInvoiceBody):
    """Create a Lightning invoice for the buyer to pay."""
    # Serialize per deal_id to prevent concurrent calls from creating duplicate
    # escrows. Without this, two simultaneous requests could both pass the
    # existing-escrow check and create separate escrows — the second overwrites
    # the DB, orphaning the first escrow and stranding any payment to it.
    deal_lock = await _get_deal_lock(deal_id)
    async with deal_lock:
        return await _create_lightning_invoice_inner(deal_id, body)


async def _create_lightning_invoice_inner(deal_id: str, body: CreateInvoiceBody):
    deal = deal_storage.get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

    if deal['status'] not in ['pending', 'active']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot create invoice for deal in status: {deal['status']}"
        )

    if not deal.get('seller_payout_invoice') or not deal.get('buyer_payout_invoice'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both parties must provide Lightning Addresses before funding"
        )

    # Seller must authenticate via LNURL-auth — their linking pubkey is used as
    # seller_pubkey in the Ark escrow (non-custodial requirement).
    if not deal.get('seller_linking_pubkey'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seller must authenticate via LNURL-auth before funding can start"
        )

    # Validate secret_code_hash format (SHA-256 hex = 64 lowercase hex chars)
    if not _SHA256_HEX_RE.match(body.secret_code_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="secret_code_hash must be a 64-character lowercase hex SHA-256 hash"
        )

    # NON-CUSTODIAL: validate buyer_pubkey format (compressed secp256k1 = 66 hex chars, starts with 02/03)
    if not re.match(r'^0[23][0-9a-f]{64}$', body.buyer_pubkey):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="buyer_pubkey must be a 66-character compressed secp256k1 public key (hex)"
        )

    # NON-CUSTODIAL: verify buyer_pubkey matches the registered ephemeral key.
    # This prevents an attacker from substituting their own key to control the escrow.
    # Check both buyer_pubkey (set at LNURL-auth) and buyer_escrow_pubkey (set at prior funding attempt).
    registered_buyer_pubkey = deal.get('buyer_escrow_pubkey') or deal.get('buyer_pubkey')
    if registered_buyer_pubkey and body.buyer_pubkey != registered_buyer_pubkey:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="buyer_pubkey does not match registered ephemeral key"
        )

    # NON-CUSTODIAL: validate timeout pre-signature (REQUIRED — proves buyer authorized timeout claims)
    from backend.auth.schnorr_verify import verify_timeout_signature
    if not verify_timeout_signature(body.buyer_pubkey, body.timeout_signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid timeout signature — does not match buyer's pubkey"
            )

    # NON-CUSTODIAL: if timeout_action='release', the seller's timeout signature is needed
    # at timeout time. Enforce it exists BEFORE funding — otherwise the timeout handler
    # will crash with "missing timeout signature" when the deal expires.
    timeout_action = deal.get('timeout_action', 'refund')
    if timeout_action == 'release' and not deal.get('seller_timeout_signature'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seller must authenticate and provide timeout authorization before funding "
                   "(required for timeout_action='release')"
        )

    try:
        from backend.ark.ark_service import ArkEscrowService

        ark = ArkEscrowService()

        # FUND SAFETY: Block if an escrow is already registered for this deal.
        # Re-creating would overwrite the escrow_id/operation_id/hash, orphaning
        # any in-flight payment to the old invoice.
        existing_escrow = deal.get('ark_escrow_deal_id')
        existing_op_id = deal.get('ln_operation_id')
        if existing_escrow and existing_op_id:
            already_paid = await ark.check_funding_invoice_paid(existing_op_id)
            if already_paid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invoice already paid. Refresh the page to see updated status."
                )
            # Escrow registered but not yet paid — check if invoice is still valid.
            # SAFETY: before replacing an escrow's operation_id/invoice, we must be sure
            # the old invoice is expired. If the buyer pays the old invoice after we replace
            # the DB records, check-ln-invoice polls the new operation_id and never detects
            # the payment — funds get stranded. Use deal.created_at + 2h as a conservative
            # upper bound (invoice expiry is 1h, but we don't track exact invoice creation time).
            existing_bolt11 = deal.get('ln_invoice')
            if existing_bolt11:
                invoice_expired = False
                created_at = deal.get('created_at')
                if created_at:
                    from datetime import datetime, timezone
                    if isinstance(created_at, str):
                        created_dt = datetime.fromisoformat(created_at).replace(tzinfo=timezone.utc)
                    else:
                        created_dt = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at
                    age_secs = (datetime.now(timezone.utc) - created_dt).total_seconds()
                    # Conservative: only consider expired if deal is >2h old.
                    # Invoice was created sometime after deal creation, so deal_age > 2h
                    # means the invoice (created later) is at least 1h old and expired.
                    if age_secs > 7200:
                        invoice_expired = True

                if not invoice_expired:
                    logger.info(
                        "Deal %s: returning existing invoice (escrow %s already registered)",
                        deal_id, existing_escrow,
                    )
                    return CreateInvoiceResponse(
                        deal_id=deal_id,
                        payment_hash=deal.get('ln_payment_hash') or existing_op_id,
                        bolt11=existing_bolt11,
                        amount_sats=deal.get('invoice_amount_sats', deal['price_sats']),
                        description=f"Escrow: {deal['title'][:50]}",
                        price_sats=deal['price_sats'],
                        service_fee_sats=deal.get('service_fee_sats', 0),
                        chain_fee_sats=deal.get('chain_fee_budget_sats', 0),
                    )

                # Invoice expired and unpaid — create a fresh escrow+invoice.
                # SAFETY: final payment check before replacing — if buyer paid between
                # the check at line 89 and now, we must not replace the operation_id.
                final_check = await ark.check_funding_invoice_paid(existing_op_id)
                if final_check:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invoice already paid. Refresh the page to see updated status."
                    )
                # The old unfunded escrow is harmless (no money was locked).
                logger.info(
                    "Deal %s: existing invoice expired, creating new escrow+invoice (old escrow %s unfunded)",
                    deal_id, existing_escrow,
                )

        fees = get_fees()
        service_fee_sats = int(deal['price_sats'] * (fees['service_fee_percent'] / 100))
        chain_fee_sats = 0
        amount_sats = deal['price_sats'] + service_fee_sats + chain_fee_sats

        # New path: single CLI call creates invoice + pre-registers escrow params.
        # When buyer pays, await_receive_into_escrow atomically creates the Ark escrow
        # (eliminates Window ①: no separate create-escrow step).
        # Non-custodial: use seller's ephemeral key (from LNURL-auth) as seller_pubkey
        # in the Ark escrow. The seller's own key — not the service's key.
        seller_escrow_pubkey = deal.get('seller_pubkey')
        if not seller_escrow_pubkey:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seller's ephemeral key not found. Seller must authenticate first."
            )

        ln_result = await ark.create_funding_invoice_with_escrow(
            amount_sats=amount_sats,
            secret_code_hash=body.secret_code_hash,
            timeout_hours=deal.get('timeout_hours', 72),
            timeout_action=deal.get('timeout_action', 'refund'),
            seller_pubkey=seller_escrow_pubkey,
            buyer_pubkey=body.buyer_pubkey,
            description=f"{deal_id}   {deal['title']}",
        )
        # ln_result = {bolt11, escrow_id, operation_id}
        bolt11 = ln_result["bolt11"]
        escrow_id = ln_result["escrow_id"]
        operation_id = ln_result["operation_id"]
        timeout_block = ln_result["timeout_block"]

        update_fields = dict(
            ln_invoice=bolt11,
            ln_operation_id=operation_id,
            invoice_amount_sats=amount_sats,
            service_fee_sats=service_fee_sats,
            chain_fee_budget_sats=chain_fee_sats,
            # Non-custodial: store hash provided by buyer's browser.
            # Plaintext never leaves the browser — service only knows the hash.
            ark_secret_code_hash=body.secret_code_hash,
            # Store escrow_id NOW (created with invoice — not after payment).
            ark_escrow_deal_id=escrow_id,
            # Store timeout_block to avoid drift on subsequent polls.
            ark_timeout_block=timeout_block,
        )
        # Non-custodial: store buyer's ephemeral pubkey and pre-signed timeout
        # authorization. These enable the service to submit delegated claims
        # on the user's behalf while the user retains signing authority.
        # Both are REQUIRED (enforced above) — no custodial fallback.
        update_fields['buyer_escrow_pubkey'] = body.buyer_pubkey
        update_fields['buyer_timeout_signature'] = body.timeout_signature
        if body.encrypted_vault:
            update_fields['buyer_encrypted_vault'] = body.encrypted_vault

        deal_storage.update_deal(deal_id=deal_id, **update_fields)

        logger.info(
            "Deal %s: receive-into-escrow invoice created, escrow_id=%s, op_id=%s, amount=%d sats",
            deal_id, escrow_id, operation_id, amount_sats,
        )

        return CreateInvoiceResponse(
            deal_id=deal_id,
            payment_hash=operation_id,
            bolt11=bolt11,
            amount_sats=amount_sats,
            description=f"Escrow: {deal['title'][:50]}",
            price_sats=deal['price_sats'],
            service_fee_sats=service_fee_sats,
            chain_fee_sats=chain_fee_sats,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create Lightning invoice for deal %s: %s", deal_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error. Please try again."
        )


@router.get("/{deal_id}/check-ln-invoice", response_model=InvoiceStatusResponse)
async def check_lightning_invoice(deal_id: str):
    """Check if the Lightning invoice for this deal has been paid."""
    deal = deal_storage.get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

    payment_hash = deal.get('ln_payment_hash') or deal.get('ln_operation_id')
    if not payment_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Lightning invoice created for this deal"
        )

    # If deal is already funded (or further), return paid immediately
    if deal['status'] not in ['pending', 'active']:
        return InvoiceStatusResponse(
            deal_id=deal_id,
            payment_hash=payment_hash,
            paid=True,
            amount_sats=deal.get('price_sats'),
        )

    operation_id = deal.get('ln_operation_id')
    if not operation_id:
        # Legacy deal without operation_id — cannot check payment status
        return InvoiceStatusResponse(deal_id=deal_id, payment_hash=payment_hash, paid=False)

    try:
        from backend.ark.ark_service import ArkEscrowService
        from backend.database.deal_storage import set_deal_funded
        from backend.api.routes._shared import _ws_notify
        ark = ArkEscrowService()

        escrow_id = deal.get('ark_escrow_deal_id')
        if escrow_id:
            # New path: escrow_id was pre-registered at invoice creation via receive-into-escrow.
            # await_receive_into_escrow atomically creates the escrow when payment arrives —
            # no separate create-escrow step needed (Window ① eliminated).
            result = await ark.check_funding_invoice_with_escrow(
                operation_id=operation_id,
                escrow_id=escrow_id,
                amount_sats=deal.get('invoice_amount_sats', deal['price_sats']),
                secret_code_hash=deal_storage.get_secret_code_hash(deal_id) or '',
                timeout_block=deal.get('ark_timeout_block', 0),
                timeout_action=deal.get('timeout_action', 'refund'),
                seller_pubkey=deal.get('seller_pubkey', ''),
                buyer_pubkey=deal.get('buyer_escrow_pubkey'),
            )
            if result['status'] == 'funded':
                set_deal_funded(deal_id)
                await _ws_notify(deal_id, 'invoice:paid')
                await _ws_notify(deal_id, 'deal:funded')
                logger.info(
                    "Deal %s funded via receive-into-escrow: escrow_id=%s",
                    deal_id, escrow_id,
                )
                return InvoiceStatusResponse(
                    deal_id=deal_id,
                    payment_hash=payment_hash,
                    paid=True,
                    amount_sats=deal.get('invoice_amount_sats'),
                )
            else:
                # status == "awaiting" or "failed"
                is_failed = result.get('status') == 'failed'
                if is_failed:
                    logger.info("Deal %s: invoice expired or LN receive failed", deal_id[:8])
                return InvoiceStatusResponse(
                    deal_id=deal_id,
                    payment_hash=payment_hash,
                    paid=False,
                    invoice_expired=is_failed,
                )
        else:
            # Legacy path removed: deals without ark_escrow_deal_id should not exist.
            # Old flow (two-step: check payment → create escrow) was removed because it
            # returned paid=True even when escrow creation failed, leaving funds unprotected.
            logger.error("check-ln-invoice: deal %s has no ark_escrow_deal_id — legacy path removed", deal_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Deal missing escrow registration. Please contact support."
            )

    except HTTPException:
        raise
    except Exception as e:
        # Transient CLI timeout (arkd DB contention) → return awaiting, not 500.
        # The frontend/test polls again in a few seconds and will get the real status.
        from backend.ark.ark_client import ArkEscrowClient, ArkEscrowError, ArkEscrowNotFoundError, ArkEscrowStateError, EscrowInfo
        if isinstance(e, EscrowClientError) and "timed out" in str(e):
            logger.warning("check-ln-invoice: transient ark-escrow-agent timeout for deal %s — returning awaiting", deal_id)
            return InvoiceStatusResponse(deal_id=deal_id, payment_hash=payment_hash, paid=False)
        logger.error("Failed to check invoice status for deal %s: %s", deal_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error. Please try again."
        )



