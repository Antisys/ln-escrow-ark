"""
Graceful shutdown coordinator for in-flight payouts.

Tracks active payout operations so the lifespan shutdown handler can wait
for them to finish before cancelling background tasks.  This prevents the
scenario where a payout is mid-flight (escrow claimed, LN payment pending)
and a SIGTERM aborts it, leaving funds in limbo.

Usage in payout code:

    async with inflight():
        ... critical payout section ...

Usage in lifespan shutdown:

    await drain(timeout=30)
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_count = 0
_lock = asyncio.Lock()
_drained = asyncio.Event()
_shutting_down = False

# Expose read-only state for health checks
def active_count() -> int:
    return _count

def is_shutting_down() -> bool:
    return _shutting_down


class inflight:
    """Async context manager that tracks an in-flight payout operation."""

    async def __aenter__(self):
        global _count
        async with _lock:
            _count += 1
            _drained.clear()
        return self

    async def __aexit__(self, *exc):
        global _count
        async with _lock:
            _count -= 1
            if _count == 0:
                _drained.set()


async def drain(timeout: float = 30) -> bool:
    """
    Signal shutdown and wait for all in-flight payouts to complete.

    Returns True if all payouts drained within timeout, False otherwise.
    """
    global _shutting_down
    _shutting_down = True

    async with _lock:
        if _count == 0:
            logger.info("[Shutdown] No in-flight payouts")
            return True

    logger.info("[Shutdown] Waiting for %d in-flight payout(s) to complete (timeout=%ds)...", _count, timeout)
    try:
        await asyncio.wait_for(_drained.wait(), timeout=timeout)
        logger.info("[Shutdown] All in-flight payouts completed")
        return True
    except asyncio.TimeoutError:
        logger.error("[Shutdown] Timed out with %d payout(s) still in-flight!", _count)
        return False
