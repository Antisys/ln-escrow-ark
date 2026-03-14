"""
Startup reconciliation for deals stuck in intermediate states.

After a crash, deals may be stuck in 'releasing' or 'refunding' status —
meaning the write-ahead intent was recorded but the final status was never confirmed.

In Ark mode there is no chain to check — we simply log and leave the deals
in their intermediate state so the retry loop in timeout_handler can pick them up.
"""
import logging

from backend.database import deal_storage
from backend.database.models import DealStatus

logger = logging.getLogger(__name__)


def reconcile_stuck_deals():
    """
    Find deals in releasing/refunding state and log them for operator awareness.

    In Ark mode we cannot check chain state, so we leave these deals as-is.
    The process_stalled_payouts() loop in timeout_handler will retry the LN payout
    if the Ark escrow was already claimed (release_txid/refund_txid set).
    """
    from backend.database.connection import get_db_session
    from backend.database.models import DealModel

    with get_db_session() as db:
        stuck = db.query(DealModel).filter(
            DealModel.status.in_([
                DealStatus.RELEASING.value,
                DealStatus.REFUNDING.value,
            ])
        ).all()

        if not stuck:
            return 0

        stuck_deals = [d.to_dict() for d in stuck]

    logger.warning(
        f"[Reconcile] Found {len(stuck_deals)} deal(s) in intermediate state — "
        "stalled-payout retry loop will handle them"
    )
    for deal in stuck_deals:
        logger.warning(
            f"[Reconcile] Stuck deal {deal['deal_id'][:8]} "
            f"status={deal['status']} "
            f"release_txid={deal.get('release_txid')} "
            f"refund_txid={deal.get('refund_txid')}"
        )

    return len(stuck_deals)
