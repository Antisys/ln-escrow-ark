"""
Background task that checks for expired deals and executes timeout actions.
Runs periodically via asyncio in the FastAPI lifespan.

Two responsibilities:
1. process_expired_deals() — find newly expired deals, execute Ark timeout + LN payout
2. process_stalled_payouts() — retry failed LN payouts (Ark escrow already claimed)
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

from backend.database import deal_storage
from backend.database.models import DealStatus

logger = logging.getLogger(__name__)

# How often to check for expired deals (seconds)
CHECK_INTERVAL = 60

# Retry configuration for stalled LN payouts
MAX_RETRY_COUNT = 100
MIN_RETRY_INTERVAL = 60       # 1 minute
MAX_RETRY_INTERVAL = 1800     # 30 minutes
BACKOFF_MULTIPLIER = 2

# In-memory retry state: deal_id -> {'count': int, 'next_at': float, 'interval': int}
_retry_state: dict[str, dict] = {}


def _get_retry_info(deal_id: str) -> dict:
    """Get or create retry state for a deal."""
    if deal_id not in _retry_state:
        _retry_state[deal_id] = {
            'count': 0,
            'next_at': 0,
            'interval': MIN_RETRY_INTERVAL,
        }
    return _retry_state[deal_id]


def _bump_retry(deal_id: str):
    """Increment retry count and backoff interval after a failure."""
    info = _get_retry_info(deal_id)
    info['count'] += 1
    info['interval'] = min(info['interval'] * BACKOFF_MULTIPLIER, MAX_RETRY_INTERVAL)
    info['next_at'] = asyncio.get_running_loop().time() + info['interval']


def _clear_retry(deal_id: str):
    """Clear retry state after success."""
    _retry_state.pop(deal_id, None)


def _should_retry(deal_id: str) -> bool:
    """Check if enough time has passed and retry count is within limits."""
    info = _get_retry_info(deal_id)
    if info['count'] >= MAX_RETRY_COUNT:
        return False
    now = asyncio.get_running_loop().time()
    return now >= info['next_at']


# Regex to extract block heights from Ark timelock error
_TIMELOCK_RE = re.compile(r'Timelock has not expired yet \(current:\s*(\d+),\s*required:\s*(\d+)\)')

def _parse_timelock_error(error_str: str) -> tuple[int, int] | None:
    """Extract (current_block, required_block) from a Ark timelock error, or None."""
    m = _TIMELOCK_RE.search(error_str)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def _defer_until_timelock(retry_key: str, blocks_remaining: int):
    """Set retry delay based on remaining blocks (~10 min/block avg, check every 30 min minimum)."""
    # ~10 min per block on average, check a bit before expected time
    estimated_secs = max(blocks_remaining * 10 * 60 - 300, MIN_RETRY_INTERVAL)
    # Cap at 12 hours — don't want to wait forever if block times are slow
    estimated_secs = min(estimated_secs, 43200)
    info = _get_retry_info(retry_key)
    # Don't increment retry count for timelock waits — this is expected, not a failure
    info['next_at'] = asyncio.get_running_loop().time() + estimated_secs
    info['interval'] = estimated_secs
    logger.warning("[Retry] %s: timelock %d blocks away, deferring %ds", retry_key, blocks_remaining, estimated_secs)


# Maximum time to spend on a single deal before moving to the next
PER_DEAL_TIMEOUT = 120  # seconds


async def process_expired_deals(vault_service=None):
    """
    Find expired deals and execute their timeout_action via Ark.
    - 'refund': claim Ark escrow → pay buyer via LN
    - 'release': claim Ark escrow → pay seller via LN
    """
    expired = deal_storage.find_expired_deals()
    if not expired:
        return 0

    processed = 0
    for deal in expired:
        deal_id = deal['deal_id']
        action = deal.get('timeout_action', 'refund')

        if not deal.get('ark_escrow_deal_id'):
            logger.warning("[Timeout] Deal %s expired but has no Ark escrow, marking expired", deal_id[:8])
            deal_storage.update_deal(deal_id, status='expired')
            await _notify_timeout(deal_id, deal)
            processed += 1
            continue

        try:
            if action in ('release', 'refund'):
                await asyncio.wait_for(
                    _execute_timeout_action(deal, action),
                    timeout=PER_DEAL_TIMEOUT,
                )
            else:
                # Unknown timeout_action — mark expired to prevent infinite retry loop.
                # Funds remain safe in escrow; admin must resolve manually.
                logger.error("[Timeout] Deal %s has unhandled timeout_action '%s' — marking expired", deal_id[:8], action)
                deal_storage.update_deal(deal_id, status='expired')
                await _notify_timeout(deal_id, deal)

            processed += 1

        except asyncio.TimeoutError:
            logger.error("[Timeout] Deal %s timed out after %ds", deal_id[:8], PER_DEAL_TIMEOUT)
        except Exception as e:
            logger.error("[Timeout] Failed to process deal %s: %s", deal_id[:8], e)

    if processed:
        logger.info("[Timeout] Processed %d expired deal(s)", processed)
    return processed


async def _execute_timeout_action(deal, payout_type: str):
    """Execute timeout action (release or refund): claim Ark escrow → pay via LN."""
    deal_id = deal['deal_id']

    if payout_type == 'release':
        invoice_field, ws_event = 'seller_payout_invoice', 'deal:timeout_released'
    else:
        invoice_field, ws_event = 'buyer_payout_invoice', 'deal:timeout_refunded'

    invoice = deal.get(invoice_field)
    if not invoice:
        # Recipient has no payout address — cannot pay out.
        # Mark as expired; funds remain safe in escrow until address is submitted.
        # NOTE: We do NOT fall back to refunding the buyer when timeout_action='release',
        # because the Ark escrow's claim-timeout-delegated requires the seller's
        # signature for release, and the non-delegated claim-timeout requires the service
        # key to be registered in the escrow (which is no longer true for new deals).
        logger.warning(
            "[Timeout] Deal %s expired but no payout address for %s — "
            "marking expired, funds remain in escrow until address is submitted",
            deal_id[:8], payout_type,
        )
        deal_storage.update_deal(deal_id, status='expired')
        await _notify_timeout(deal_id, deal)
        return

    # PRE-CHECK: verify the Bitcoin timelock has actually expired before calling
    # Ark. Each Ark call creates a client operation that retries at the
    # protocol level FOREVER if the timelock hasn't passed. 520 such zombie
    # operations accumulated and caused 81% CPU on escrow-httpd.
    timeout_block = deal.get('ark_timeout_block')
    if timeout_block:
        try:
            from backend.ark.ark_service import ArkEscrowService
            ark = ArkEscrowService()
            current_height = await ark._get_block_height_cached()
            if current_height < timeout_block:
                blocks_remaining = timeout_block - current_height
                logger.info(
                    "[Timeout] Deal %s: timelock not expired (current=%d, required=%d, %d blocks away) — "
                    "deferring, marking expired for retry later",
                    deal_id[:8], current_height, timeout_block, blocks_remaining,
                )
                deal_storage.update_deal(deal_id, status='expired')
                return
        except Exception as height_err:
            logger.warning("[Timeout] Deal %s: could not check block height (%s), proceeding with claim",
                           deal_id[:8], height_err)

    logger.info("[Timeout] Deal %s executing Ark %s payout", deal_id[:8], payout_type)
    try:
        from backend.api.routes._payout import execute_ark_payout
        await execute_ark_payout(
            deal=deal,
            payout_type=payout_type,
            ws_complete_event=ws_event,
            timeout_claim=True,  # Both release and refund use timeout path (no secret_code)
        )
    except Exception as e:
        logger.error("[Timeout] Deal %s %s failed: %s", deal_id[:8], payout_type, e)

        # Check if the escrow was already claimed.
        # DOUBLE PAYMENT PREVENTION: claim-timeout-delegated-and-pay is ATOMIC.
        # If we got a timeout and escrow is claimed, the payment likely succeeded.
        # Do NOT mark for retry — that causes pay_from_wallet → double payment.
        payout_status_field = 'buyer_payout_status' if payout_type == 'refund' else 'payout_status'
        txid_field = 'refund_txid' if payout_type == 'refund' else 'release_txid'
        is_timeout = "timed out" in str(e).lower()
        escrow_claimed = False
        escrow_id = deal.get('ark_escrow_deal_id')
        try:
            from backend.ark.ark_service import ArkEscrowService
            ark = ArkEscrowService()
            if escrow_id:
                escrow_info = await ark.get_escrow_info(escrow_id)
                escrow_claimed = escrow_info.state not in ('Open', 'DisputedByBuyer', 'DisputedBySeller')
        except Exception as check_err:
            logger.debug("[Timeout] Could not check escrow state for deal %s: %s", deal_id[:8], check_err)

        transitional = 'releasing' if payout_type == 'release' else 'refunding'
        final_status = 'completed' if payout_type == 'release' else 'refunded'

        if escrow_claimed and is_timeout:
            # Atomic claim+pay likely succeeded — mark completed, don't retry
            logger.warning(
                "[Timeout] TIMEOUT SAFETY: Deal %s escrow %s claimed after HTTP timeout — "
                "marking COMPLETED (atomic claim+pay likely succeeded). "
                "Admin: verify payment arrived; if not, manual payout from wallet needed.",
                deal_id[:8], escrow_id,
            )
            allowed_from = [deal['status'], transitional]
            deal_storage.atomic_status_transition(
                deal_id, allowed_from, final_status,
                completed_at=datetime.now(timezone.utc),
                **{txid_field: escrow_id, payout_status_field: 'paid'},
            )
        elif escrow_claimed:
            # Explicit LN failure — escrow claimed but pay failed, mark for retry
            logger.info(
                "[Timeout] Deal %s: escrow %s claimed (state=%s) but LN pay explicitly failed, "
                "recording txid for LN-only retry",
                deal_id[:8], escrow_id, escrow_info.state if escrow_claimed else '?',
            )
            allowed_rollback = [deal['status'], transitional]
            rolled_back = deal_storage.atomic_status_transition(
                deal_id, allowed_rollback, 'expired',
                **{txid_field: escrow_id, payout_status_field: 'failed'},
            )
            if not rolled_back:
                logger.info("[Timeout] Deal %s: status already changed by concurrent process, skipping rollback", deal_id[:8])
            else:
                await _notify_timeout(deal_id, deal)
        else:
            # Escrow not claimed — safe to mark expired for full retry
            allowed_rollback = [deal['status'], transitional]
            rolled_back = deal_storage.atomic_status_transition(
                deal_id, allowed_rollback, 'expired',
                **{payout_status_field: 'failed'},
            )
            if not rolled_back:
                logger.info("[Timeout] Deal %s: status already changed by concurrent process, skipping rollback", deal_id[:8])
            else:
                await _notify_timeout(deal_id, deal)


async def _notify_timeout(deal_id, deal):
    """Send timeout notification via WebSocket."""
    try:
        from backend.api.routes.websockets import manager as ws_manager
        await ws_manager.broadcast(deal_id, 'deal:timeout_expired')
    except Exception:
        pass


async def process_stalled_payouts():
    """
    Retry failed timeout claim+pay operations.

    Only retries FULL claim+pay (atomic operations with user authorization).
    NEVER retries LN-only payments from wallet — that bypasses escrow
    authorization and caused a double-payment bug (2026-03-12).

    Covers deals where the Ark timeout block wasn't reached yet when the
    initial timeout handler ran, or where claim-timeout-delegated-and-pay failed
    for transient reasons (network, DB lock, etc).

    Uses exponential backoff: 1min → 2min → 4min → ... → max 30min.
    After 100 retries, parks deal as payout_stuck.
    """
    from backend.api.routes._payout import execute_ark_payout

    candidates = deal_storage.get_deals_by_statuses(
        ['expired']
    )

    # Each tuple: (txid_field, status_field, invoice_field, final_status, fee_field, label)
    PAYOUT_PATHS = [
        ('release_txid', 'payout_status', 'seller_payout_invoice', 'completed', 'payout_fee_sat', 'release'),
        ('refund_txid', 'buyer_payout_status', 'buyer_payout_invoice', 'refunded', 'buyer_payout_fee_sat', 'refund'),
    ]

    retried = 0
    for deal in candidates:
        deal_id = deal['deal_id']


        # --- Full claim retries (escrow claim failed, txid NOT set) ---
        # This covers deals where the Ark timeout block wasn't reached yet
        # when the initial timeout handler ran, or where claim-timeout-and-pay
        # failed for transient reasons (DB lock, network, etc).
        if deal.get('status') != 'expired' or not deal.get('ark_escrow_deal_id'):
            continue

        for txid_f, status_f, invoice_f, final_status, fee_f, label in PAYOUT_PATHS:
            # Only if claim itself failed: txid NOT set, but payout_status is failed, and invoice exists
            if deal.get(txid_f) or deal.get(status_f) != 'failed' or not deal.get(invoice_f):
                continue

            retry_key = f"{deal_id}:claim_{label}"
            if not _should_retry(retry_key):
                info = _get_retry_info(retry_key)
                if info['count'] >= MAX_RETRY_COUNT:
                    deal_storage.update_deal(deal_id, **{status_f: 'payout_stuck'})
                    logger.error("[Retry] Deal %s %s escrow claim STUCK after %d retries", deal_id[:8], label, MAX_RETRY_COUNT)
                continue

            # PRE-CHECK: verify timelock has expired before calling Ark.
            # Without this, each call creates a Ark operation that retries
            # forever at the protocol level, causing zombie operations and high CPU.
            timeout_block = deal.get('ark_timeout_block')
            if timeout_block:
                try:
                    from backend.ark.ark_service import ArkEscrowService
                    ark_svc = ArkEscrowService()
                    current_height = await ark_svc._get_block_height_cached()
                    if current_height < timeout_block:
                        blocks_remaining = timeout_block - current_height
                        _defer_until_timelock(retry_key, blocks_remaining)
                        continue
                except Exception as height_err:
                    logger.warning("[Retry] Deal %s: could not check block height (%s), proceeding",
                                   deal_id[:8], height_err)

            attempt = _get_retry_info(retry_key)['count'] + 1
            logger.info("[Retry] Retrying full %s claim+pay for deal %s (attempt %d)", label, deal_id[:8], attempt)
            try:
                # Re-read deal to get fresh state
                fresh_deal = deal_storage.get_deal_by_id(deal_id)
                if not fresh_deal:
                    continue
                ws_event = f'deal:timeout_{"released" if label == "release" else "refunded"}'
                await execute_ark_payout(
                    deal=fresh_deal,
                    payout_type=label,
                    ws_complete_event=ws_event,
                    timeout_claim=True,
                )
                logger.info("[Retry] Full %s claim+pay succeeded for deal %s", label, deal_id[:8])
                _clear_retry(retry_key)
                retried += 1
            except Exception as e:
                error_str = str(e)

                # Check for timelock errors FIRST — "Transaction was rejected"
                # can wrap a timelock error, so we must parse before treating
                # rejection as permanent
                timelock = _parse_timelock_error(error_str)
                if timelock:
                    current_block, required_block = timelock
                    blocks_remaining = required_block - current_block
                    _defer_until_timelock(retry_key, blocks_remaining)
                    continue

                # Permanent failures — stop retrying
                if 'Escrow not found' in error_str:
                    deal_storage.update_deal(deal_id, **{status_f: 'payout_stuck'})
                    logger.error("[Retry] Deal %s %s: permanent failure (%s) — marking payout_stuck", deal_id[:8], label, error_str[:100])
                    _clear_retry(retry_key)
                    continue

                # "Transaction was rejected" without timelock info — could be
                # transient (e.g. timelock not reached but error wrapped differently).
                # Use normal backoff instead of parking permanently.
                if 'Transaction was rejected' in error_str:
                    _bump_retry(retry_key)
                    info = _get_retry_info(retry_key)
                    logger.warning("[Retry] Full %s claim+pay still failing for deal %s: %s (attempt %d, next in %ds)", label, deal_id[:8], e, info['count'], info['interval'])

    if retried:
        logger.info("[Retry] Successfully retried %d stalled payout(s)", retried)
    return retried


async def timeout_loop(vault_service=None):
    """Background loop that periodically checks for expired deals and retries stalled payouts."""
    from backend.api.shutdown import is_shutting_down
    logger.warning("[Timeout] Handler started (checking every %ds)", CHECK_INTERVAL)
    while True:
        if is_shutting_down():
            logger.info("[Timeout] Shutdown in progress — stopping timeout loop")
            return
        try:
            await asyncio.wait_for(process_expired_deals(), timeout=300)
        except asyncio.TimeoutError:
            logger.error("[Timeout] process_expired_deals() timed out after 300s")
        except Exception as e:
            logger.error("[Timeout] Loop error: %s", e)
        if is_shutting_down():
            logger.info("[Timeout] Shutdown in progress — stopping timeout loop")
            return
        try:
            await asyncio.wait_for(process_stalled_payouts(), timeout=300)
        except asyncio.TimeoutError:
            logger.error("[Retry] process_stalled_payouts() timed out after 300s")
        except Exception as e:
            logger.error("[Retry] Loop error: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)
