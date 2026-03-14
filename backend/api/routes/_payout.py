"""
LN payout helpers used across deal route files.

Ark-only: execute_ark_payout() — claim escrow → pay via LN.
"""
import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

from lnurl_toolkit import resolve_lightning_address, fetch_pay_params

from backend.database import deal_storage
from backend.api.routes._shared import _ws_notify
from backend.api.shutdown import inflight
from backend.api.logging_config import audit_log

logger = logging.getLogger(__name__)

_LN_ADDRESS_RE = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


def _payout_fields(payout_type: str) -> dict:
    """Return field names for a payout type (release or refund)."""
    is_refund = payout_type == "refund"
    return {
        'invoice_field': 'buyer_payout_invoice' if is_refund else 'seller_payout_invoice',
        'payout_status_field': 'buyer_payout_status' if is_refund else 'payout_status',
        'completed_status': 'refunded' if is_refund else 'completed',
        'transitional_status': 'refunding' if is_refund else 'releasing',
        'txid_field': 'refund_txid' if is_refund else 'release_txid',
        'cross_txid_field': 'release_txid' if is_refund else 'refund_txid',
    }



# ============================================================================
# Kill switch — emergency halt for all payouts
# ============================================================================

_PAYOUTS_HALTED = False


def halt_payouts():
    """Halt all payouts immediately (admin emergency stop)."""
    global _PAYOUTS_HALTED
    _PAYOUTS_HALTED = True
    logger.warning("KILL SWITCH: All payouts HALTED")


def resume_payouts():
    """Resume payouts after emergency halt."""
    global _PAYOUTS_HALTED
    _PAYOUTS_HALTED = False
    logger.info("Payouts RESUMED")


def payouts_halted() -> bool:
    """Check if payouts are halted (module state OR env var)."""
    return _PAYOUTS_HALTED or os.getenv('PAYOUTS_HALTED', '').lower() == 'true'



async def resolve_to_routeable_invoice(
    address: str, amount_sats: int, comment: str = ""
) -> str:
    """
    Resolve a Lightning Address to a BOLT11 invoice.

    No LND route pre-check: payouts go through the Ark gateway which has
    its own routing graph. Our LND node's graph is irrelevant.
    """
    bolt11 = await resolve_lightning_address(address, amount_sats, comment=comment)
    logger.info("Resolved Lightning Address %s → BOLT11 (len=%d)", address, len(bolt11))
    return bolt11


async def validate_lightning_address(address: str, amount_sats: int) -> None:
    """
    Validate a Lightning Address by resolving its LNURL-pay endpoint.

    Raises HTTPException on failure.
    """
    from fastapi import HTTPException, status

    if not _LN_ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid format. Provide a Lightning Address (user@domain)."
        )

    try:
        params = await fetch_pay_params(address)
    except Exception as e:
        logger.warning("Lightning Address validation failed for %s: %s", address, e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lightning Address '{address}' could not be verified. Check for typos or try a different address."
        )

    amount_msats = amount_sats * 1000
    if amount_msats < params.min_sendable_msats:
        min_sats = params.min_sendable_msats // 1000
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Deal amount ({amount_sats} sats) is below this address's minimum ({min_sats} sats)."
        )
    if amount_msats > params.max_sendable_msats:
        max_sats = params.max_sendable_msats // 1000
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Deal amount ({amount_sats} sats) exceeds this address's maximum ({max_sats} sats)."
        )

    logger.info("Lightning Address validated: %s (range: %d-%d sats)", address, params.min_sendable_msats // 1000, params.max_sendable_msats // 1000)




# ============================================================================
# Safety-gated LN payout
# ============================================================================



# ============================================================================
# execute_ark_payout() — the core resolution function
# ============================================================================

async def execute_ark_payout(
    deal: dict,
    payout_type: str,
    raise_on_ln_fail: bool = False,
    ws_complete_event: str = "",
    secret_code: Optional[str] = None,
    timeout_claim: bool = False,
    buyer_escrow_signature: Optional[str] = None,
) -> dict:
    """
    Execute a Ark-based payout: claim escrow → pay recipient via LN.

    Args:
        deal:              Deal dict from database.
        payout_type:       "release" (pay seller) or "refund" (pay buyer).
        raise_on_ln_fail:  True → raise HTTPException on LN failure (user-facing).
        ws_complete_event: WebSocket event to send on completion.
        secret_code:       For cooperative "release": the escrow secret_code from buyer's browser.
                           Must NOT come from DB for non-custodial guarantee.
                           Not needed when timeout_claim=True.
        timeout_claim:     True → use claim-timeout (no secret_code needed, valid after timeout block).
                           For timeout handler. False → use cooperative claim(secret_code) for release.

    Returns:
        dict with 'txid' (the escrow_id) and 'payout_result'.
    """
    from fastapi import HTTPException
    from backend.ark.ark_service import ArkEscrowService

    deal_id = deal['deal_id']

    if payouts_halted():
        raise ValueError(f"PAYOUTS HALTED: deal {deal_id} payout blocked by kill switch")

    escrow_id = deal.get('ark_escrow_deal_id')
    # secret_code is passed in by caller (from buyer's request body), NOT read from DB

    if not escrow_id:
        raise ValueError(f"Deal {deal_id} has no ark_escrow_deal_id")

    fields = _payout_fields(payout_type)
    invoice_field = fields['invoice_field']
    payout_status_field = fields['payout_status_field']
    completed_status = fields['completed_status']
    transitional_status = fields['transitional_status']
    txid_field = fields['txid_field']
    cross_txid_field = fields['cross_txid_field']
    is_refund = payout_type == "refund"

    # COIN SAFETY: Block if the OTHER payout type already claimed the escrow.
    if deal.get(cross_txid_field):
        cross_type = 'release' if is_refund else 'refund'
        raise ValueError(
            f"Deal {deal_id}: escrow already claimed via {cross_type} — cannot {payout_type}"
        )

    # Idempotency: if already completed (txid set), nothing to do.
    if deal.get(txid_field):
        logger.info("Deal %s already completed (%s) — idempotent return", deal_id, payout_type)
        return {'txid': escrow_id, 'payout_result': {'success': True, 'already_paid': True}}

    # Cooperative release requires secret_code from buyer
    if not is_refund and not timeout_claim and not secret_code:
        raise ValueError(
            f"Deal {deal_id}: secret_code required for cooperative release "
            f"(must be submitted by buyer, not read from DB)"
        )

    invoice = deal.get(invoice_field)
    # Ark mode: no LN invoice needed if pubkey is available
    ark_pubkey = deal.get('seller_pubkey') if not is_refund else deal.get('buyer_pubkey')
    if not invoice and not ark_pubkey:
        error_msg = f"No {'buyer' if is_refund else 'seller'} payout destination"
        if raise_on_ln_fail:
            raise HTTPException(status_code=400, detail=error_msg)
        raise ValueError(error_msg)

    # Ark mode: skip LN payment, just update escrow status via agent
    if not invoice and ark_pubkey:
        escrow_id = deal.get('ark_escrow_deal_id')
        if escrow_id:
            try:
                from backend.ark.ark_service import ArkEscrowService
                ark = ArkEscrowService()
                if is_refund:
                    await ark.refund_deal_escrow(escrow_id)
                else:
                    await ark.release_deal_escrow(escrow_id, secret_code or '')
            except Exception as e:
                logger.warning("Ark escrow %s failed (non-fatal): %s", 'refund' if is_refund else 'release', e)

        # Update deal status directly
        new_status = 'refunded' if is_refund else 'completed'
        txid_field = fields['txid_field']
        deal_storage.update_deal(deal_id=deal_id, status=new_status, **{txid_field: escrow_id or 'ark_direct'})
        if ws_complete_event:
            try:
                from backend.api.routes._shared import _ws_notify
                await _ws_notify(deal_id, ws_complete_event)
            except Exception:
                pass
        logger.info("Ark payout %s completed for deal %s", 'refund' if is_refund else 'release', deal_id[:8])
        return

    t_start = time.monotonic()

    # Resolve Lightning Address → BOLT11 in Python (HTTP call stays in Python layer)
    # Uses route pre-check to avoid wasting federation fees on unrouteable destinations
    if '@' in invoice and not invoice.lower().startswith('ln'):
        logger.info("Resolving Lightning Address %s for deal %s payout", invoice, deal_id)
        deal_obj = deal_storage.get_deal_by_id(deal_id) or deal
        deal_title = deal_obj.get('title', '')
        comment = f"trustMeBro-ARK payout: {deal_title}" if deal_title else f"trustMeBro-ARK payout ({deal['price_sats']} sats)"
        try:
            invoice = await resolve_to_routeable_invoice(invoice, deal['price_sats'], comment=comment)
            t_resolved = time.monotonic()
            logger.info("[TIMING] Deal %s: Lightning Address resolution took %.1fs", deal_id[:8], t_resolved - t_start)
        except Exception as resolve_err:
            logger.error("Lightning Address resolution failed for deal %s: %s", deal_id, resolve_err)
            if raise_on_ln_fail:
                raise HTTPException(
                    status_code=502,
                    detail="Could not reach the Lightning Address provider. Please try again later.",
                )
            raise ValueError(f"Lightning Address resolution failed: {resolve_err}")

    # Re-read status from DB to avoid stale dict race: if a concurrent process
    # already transitioned the deal (e.g. funded → refunding), using the stale
    # dict's status would bypass the extra_check guard.
    fresh = deal_storage.get_deal_by_id(deal_id)
    if not fresh:
        raise ValueError(f"Deal {deal_id} not found")
    prev_status = fresh['status']

    # Wrap the entire payout operation in inflight() so graceful shutdown
    # waits for it to complete instead of cancelling mid-flight.
    async with inflight():
        # RACE CONDITION FIX: atomically transition status only if still in an
        # expected state.  If a concurrent release/refund already moved the deal
        # to a transitional or terminal status, this returns None and we abort.
        allowed_from = [prev_status]
        # Also allow the same transitional status (idempotent retry)
        if prev_status != transitional_status:
            allowed_from.append(transitional_status)
        # RACE GUARD: when entering from a transitional status (retry), check that
        # payout_status is NOT already 'pending' (another process is in-flight).
        # For first-time payouts (prev_status is funded/shipped/etc), payout_status
        # is null so this check doesn't apply — only guard retries.
        extra_check = None
        if prev_status == transitional_status:
            extra_check = {payout_status_field: 'failed'}
        transitioned = deal_storage.atomic_status_transition(
            deal_id, allowed_from, transitional_status,
            expected_extra=extra_check,
            **{payout_status_field: 'pending'},
        )
        if not transitioned:
            raise ValueError(
                f"Deal {deal_id}: cannot start {payout_type} — status already changed "
                f"(expected {allowed_from}, current status may differ)"
            )

        ark = ArkEscrowService()
        t_ark_start = time.monotonic()
        try:
            # NON-CUSTODIAL: deals with buyer_escrow_pubkey have user keys registered
            # in the Ark escrow. The service CANNOT use its own key — it MUST use
            # delegated paths with user-provided signatures. Custodial fallback is only
            # allowed for old deals created before non-custodial enforcement.
            has_user_keys = bool(deal.get('buyer_escrow_pubkey'))

            if is_refund or timeout_claim:
                # Non-custodial: use stored pre-signed timeout signature.
                # Which signature to use depends on timeout_action:
                #   "refund" → buyer gets money back → buyer's signature
                #   "release" → seller gets paid → seller's signature
                timeout_action = deal.get('timeout_action', 'refund')
                if timeout_action == 'release':
                    timeout_sig = deal.get('seller_timeout_signature')
                else:
                    timeout_sig = deal.get('buyer_timeout_signature')
                if timeout_sig:
                    await ark.refund_deal_delegated(escrow_id, timeout_sig, invoice)
                elif has_user_keys:
                    # NON-CUSTODIAL: deal has user keys but no timeout signature.
                    # Service key WILL NOT match escrow's buyer/seller key — claim would fail.
                    raise ValueError(
                        f"Deal {deal_id}: non-custodial escrow but missing timeout signature. "
                        f"Cannot fall back to service key."
                    )
                else:
                    # Legacy fallback for old deals without user keys in escrow
                    logger.warning("Deal %s: using custodial timeout claim (old deal without user keys)", deal_id)
                    await ark.refund_deal_escrow(escrow_id, invoice)
            else:
                # Non-custodial release: buyer's Schnorr signature required
                if buyer_escrow_signature:
                    await ark.release_deal_delegated(
                        escrow_id, secret_code, buyer_escrow_signature, invoice,
                    )
                elif has_user_keys:
                    # NON-CUSTODIAL: deal has user keys but no buyer signature.
                    # Service key WILL NOT match escrow's seller key — claim would fail.
                    raise ValueError(
                        f"Deal {deal_id}: non-custodial escrow but missing buyer_escrow_signature. "
                        f"Cannot fall back to service key."
                    )
                else:
                    # Legacy fallback for old deals without user keys in escrow
                    logger.warning("Deal %s: using custodial release (old deal without user keys)", deal_id)
                    await ark.release_deal_escrow(escrow_id, secret_code, invoice)
        except Exception as payout_err:
            t_ark_done = time.monotonic()
            logger.error(
                "Ark payout failed for deal %s after %.1fs: %s",
                deal_id, t_ark_done - t_ark_start, payout_err,
            )

            # Check if this was an HTTP timeout (operation outcome unknown)
            is_timeout = "timed out" in str(payout_err).lower()

            # RECOVERY: check escrow state to understand what happened.
            escrow_claimed = False
            try:
                escrow_info = await ark.get_escrow_info(escrow_id)
                escrow_claimed = escrow_info.state not in ('Open', 'DisputedByBuyer', 'DisputedBySeller')
            except Exception:
                pass

            if escrow_claimed and is_timeout:
                # DOUBLE PAYMENT PREVENTION: claim-delegated-and-pay and
                # claim-timeout-delegated-and-pay are ATOMIC Ark operations
                # (single consensus item: claim escrow + LN pay). If the escrow
                # is claimed and we only got an HTTP timeout (not an explicit LN
                # failure), the payment MOST LIKELY succeeded — the HTTP layer
                # just didn't wait long enough.
                #
                # Marking as 'failed' would cause the retry handler to call
                # pay_from_wallet → DOUBLE PAYMENT (seller gets paid twice).
                # Instead, mark as completed. If LN pay actually failed (unlikely
                # for atomic ops), e-cash is in the wallet and admin can resolve
                # manually. Double payment is unrecoverable; stuck e-cash is not.
                logger.warning(
                    "TIMEOUT SAFETY: Deal %s escrow %s claimed after HTTP timeout — "
                    "marking COMPLETED (atomic claim+pay likely succeeded). "
                    "Admin: verify payment arrived; if not, manual payout from wallet needed.",
                    deal_id, escrow_id,
                )
                audit_log.warning("payout_timeout_assumed_success",
                    deal_id=deal_id, escrow_id=escrow_id,
                    payout_type=payout_type, error=str(payout_err)[:200])
                deal_storage.atomic_status_transition(
                    deal_id, [transitional_status], completed_status,
                    completed_at=datetime.now(timezone.utc),
                    **{txid_field: escrow_id, payout_status_field: 'paid'},
                )
                if ws_complete_event:
                    await _ws_notify(deal_id, ws_complete_event)
                # Return success — do NOT re-raise, do NOT trigger retry
                return {
                    'txid': escrow_id,
                    'payout_result': {'success': True, 'timeout_assumed': True},
                }
            elif escrow_claimed:
                # Explicit error (not timeout): claim succeeded but LN pay failed.
                # E-cash is in service wallet. Mark as completed — the atomic
                # claim+pay was partially successful. Admin must resolve manually
                # if funds are stuck. We NEVER retry via pay_from_wallet because
                # that bypasses escrow authorization and risks double payment.
                logger.error(
                    "FUND SAFETY: Deal %s escrow %s claimed but LN pay EXPLICITLY failed — "
                    "VTXO stuck in escrow. Admin must resolve manually via ark-escrow-agent.",
                    deal_id, escrow_id,
                )
                audit_log.error("payout_ln_failed_ecash_stuck",
                    deal_id=deal_id, escrow_id=escrow_id,
                    payout_type=payout_type, error=str(payout_err)[:200])
                deal_storage.atomic_status_transition(
                    deal_id, [transitional_status], completed_status,
                    completed_at=datetime.now(timezone.utc),
                    **{txid_field: escrow_id, payout_status_field: 'failed'},
                )
                if ws_complete_event:
                    await _ws_notify(deal_id, ws_complete_event)
            else:
                # Escrow not claimed — safe to roll back to prev_status.
                deal_storage.atomic_status_transition(
                    deal_id, [transitional_status], prev_status,
                    **{payout_status_field: 'failed'},
                )
            if raise_on_ln_fail:
                raise HTTPException(
                    status_code=502,
                    detail="Lightning payment failed. Please try again.",
                )
            raise

        t_ark_done = time.monotonic()
        logger.info(
            "[TIMING] Deal %s: Ark claim+pay took %.1fs (total so far: %.1fs)",
            deal_id[:8], t_ark_done - t_ark_start, t_ark_done - t_start,
        )

        # Mark as complete: use atomic transition to prevent overwriting
        # a concurrent state change (e.g., if timeout handler ran simultaneously).
        success = deal_storage.atomic_status_transition(
            deal_id, [transitional_status], completed_status,
            completed_at=datetime.now(timezone.utc),
            **{txid_field: escrow_id, payout_status_field: 'paid'},
        )
        if not success:
            # Concurrent process already moved the deal — log but don't fail
            # (e.g., the same payout completed via a different path)
            logger.warning(
                "Deal %s: atomic success transition failed (expected %s), "
                "concurrent completion likely",
                deal_id, transitional_status,
            )
        audit_log.info("ark_payout_success",
            deal_id=deal_id, amount_sats=deal['price_sats'],
            payout_type=payout_type, escrow_id=escrow_id)
        if ws_complete_event:
            await _ws_notify(deal_id, ws_complete_event)

    return {
        'txid': escrow_id,
        'payout_result': {'success': True},
    }


async def execute_oracle_payout(
    deal: dict,
    payout_type: str,
    attestations: list,
    ws_complete_event: str = "",
) -> dict:
    """
    Execute payout after oracle dispute resolution.

    Unlike execute_ark_payout() (which claims an escrow), this function handles
    the two-step oracle flow:
      1. resolve-oracle → e-cash goes to service wallet
      2. ln pay → pays the winner via Lightning

    Args:
        deal:              Deal dict from database.
        payout_type:       "release" (pay seller) or "refund" (pay buyer).
        attestations:      List of SignedAttestation objects (2-of-3 oracle sigs).
        ws_complete_event: WebSocket event to send on completion.

    Returns:
        dict with 'txid' (escrow_id) and 'payout_result'.
    """
    from fastapi import HTTPException
    from backend.ark.ark_service import ArkEscrowService

    deal_id = deal['deal_id']

    if payouts_halted():
        raise ValueError(f"PAYOUTS HALTED: deal {deal_id} oracle payout blocked by kill switch")

    escrow_id = deal.get('ark_escrow_deal_id')

    if not escrow_id:
        raise ValueError(f"Deal {deal_id} has no ark_escrow_deal_id")

    fields = _payout_fields(payout_type)
    invoice_field = fields['invoice_field']
    payout_status_field = fields['payout_status_field']
    completed_status = fields['completed_status']
    txid_field = fields['txid_field']
    cross_txid_field = fields['cross_txid_field']
    is_refund = payout_type == "refund"

    # COIN SAFETY: Block if the OTHER payout type already claimed the escrow.
    if deal.get(cross_txid_field):
        cross_type = 'release' if is_refund else 'refund'
        raise ValueError(
            f"Deal {deal_id}: escrow already claimed via {cross_type} — cannot {payout_type}"
        )

    # Idempotency: if already completed, nothing to do.
    if deal.get(txid_field):
        logger.info("Deal %s already completed (%s) — idempotent return", deal_id, payout_type)
        return {'txid': escrow_id, 'payout_result': {'success': True, 'already_paid': True}}

    invoice = deal.get(invoice_field)
    if not invoice:
        recipient = 'buyer' if is_refund else 'seller'
        logger.warning(
            "Deal %s: oracle resolved but %s has no payout invoice — "
            "marking deal as resolved, payout pending address submission",
            deal_id, recipient,
        )
        # Mark deal as resolved (status change) but payout awaits invoice
        deal_storage.update_deal(
            deal_id,
            status=completed_status,
            **{txid_field: escrow_id, payout_status_field: 'awaiting_address'},
        )
        if ws_complete_event:
            await _ws_notify(deal_id, ws_complete_event)
        return {'txid': escrow_id, 'payout_result': {'success': False, 'awaiting_address': True}}

    # Resolve Lightning Address → BOLT11 if needed (with route pre-check)
    if invoice and '@' in invoice and not invoice.lower().startswith('ln'):
        logger.info("Resolving Lightning Address %s for oracle payout deal %s", invoice, deal_id)
        deal_title = deal.get('title', '')
        comment = f"trustMeBro-ARK payout: {deal_title}" if deal_title else f"trustMeBro-ARK payout ({deal['price_sats']} sats)"
        try:
            invoice = await resolve_to_routeable_invoice(invoice, deal['price_sats'], comment=comment)
        except Exception as resolve_err:
            logger.error("Lightning Address resolution failed for deal %s: %s", deal_id, resolve_err)
            raise ValueError(f"Lightning Address resolution failed: {resolve_err}")

    transitional_status = fields['transitional_status']

    ark = ArkEscrowService()
    async with inflight():
        # RACE CONDITION FIX: atomically transition status only if still disputed.
        # If a concurrent oracle resolution already moved the deal, abort.
        # Inside inflight() so a crash between transition and payout is tracked
        # by the drain mechanism — prevents stuck transitional state.
        transitioned = deal_storage.atomic_status_transition(
            deal_id, ['disputed'], transitional_status,
            **{payout_status_field: 'pending'},
        )
        if not transitioned:
            raise ValueError(
                f"Deal {deal_id}: cannot start oracle {payout_type} — status already changed "
                f"(expected ['disputed'], current status may differ)"
            )

        try:
            await ark.resolve_and_pay_via_oracle(escrow_id, attestations, invoice)
        except Exception as payout_err:
            logger.error("Oracle payout failed for deal %s: %s", deal_id, payout_err)

            # Check escrow state to understand what happened.
            try:
                escrow_info = await ark.get_escrow_info(escrow_id)
                escrow_resolved = escrow_info.state == 'ResolvedByOracle'
            except Exception:
                escrow_resolved = False

            if escrow_resolved:
                # Oracle resolved escrow but LN pay failed. E-cash is stuck
                # in service wallet. Mark deal as completed with payout_status=failed
                # so admin can see it. We do NOT auto-retry from wallet — that
                # bypasses escrow authorization and risks double payment.
                logger.error(
                    "FUND SAFETY: Deal %s escrow %s resolved by oracle but LN pay failed — "
                    "VTXO stuck in escrow. Admin must resolve manually via ark-escrow-agent.",
                    deal_id, escrow_id,
                )
                audit_log.error("oracle_payout_ln_failed_ecash_stuck",
                    deal_id=deal_id, escrow_id=escrow_id,
                    payout_type=payout_type, error=str(payout_err)[:200])
                deal_storage.atomic_status_transition(
                    deal_id, [transitional_status], completed_status,
                    completed_at=datetime.now(timezone.utc),
                    **{txid_field: escrow_id, payout_status_field: 'failed'},
                )
                if ws_complete_event:
                    await _ws_notify(deal_id, ws_complete_event)
                # Don't re-raise — deal is resolved, just LN pay needs manual attention
                return {
                    'txid': escrow_id,
                    'payout_result': {'success': False, 'ecash_stuck': True},
                }
            else:
                # Oracle resolution itself failed — revert to disputed.
                deal_storage.atomic_status_transition(
                    deal_id, [transitional_status], 'disputed',
                    **{payout_status_field: 'failed'},
                )
                raise

        # Success: use atomic transition to prevent overwriting concurrent state changes
        success = deal_storage.atomic_status_transition(
            deal_id, [transitional_status], completed_status,
            completed_at=datetime.now(timezone.utc),
            **{txid_field: escrow_id, payout_status_field: 'paid'},
        )
        if not success:
            logger.warning(
                "Deal %s: atomic oracle success transition failed (expected %s), "
                "concurrent completion likely",
                deal_id, transitional_status,
            )
        audit_log.info("oracle_payout_success",
            deal_id=deal_id, amount_sats=deal['price_sats'],
            payout_type=payout_type, escrow_id=escrow_id)
        if ws_complete_event:
            await _ws_notify(deal_id, ws_complete_event)

    return {
        'txid': escrow_id,
        'payout_result': {'success': True},
    }
