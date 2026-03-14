"""
Health check and system status endpoints.
"""
import asyncio
import os
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel
from datetime import datetime, timezone

from backend.config import VERSION, DEV_ORACLE_KEYS

# Cache for system status checks
_status_cache = {
    "gateway": {"result": None, "timestamp": 0},
}
_CACHE_TTL = 60  # seconds

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Basic health check"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=VERSION
    )


@router.get("/ready")
async def readiness_check(request: Request):
    """
    Readiness check - verifies service dependencies
    """
    service = request.app.state.escrow_service

    checks = {
        "escrow_service": service is not None,
    }

    all_ready = all(checks.values())

    return {
        "ready": all_ready,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


async def _check_gateway() -> dict:
    """Check Ark gateway connectivity via ark-escrow-agent."""
    now = time.time()
    cached = _status_cache["gateway"]
    if cached["result"] is not None and (now - cached["timestamp"]) < _CACHE_TTL:
        return cached["result"]

    try:
        from backend.ark.ark_service import ArkEscrowService
        ark = ArkEscrowService()
        pubkey = await asyncio.wait_for(ark.get_service_pubkey(), timeout=10)
        result = {"ok": True, "pubkey": pubkey[:16] + "..."}
    except Exception as e:
        # Keep reporting OK for 5 minutes after last success
        if cached["result"] and cached["result"].get("ok") and (now - cached["timestamp"]) < _CACHE_TTL * 5:
            return cached["result"]
        result = {"ok": False, "error": "gateway unreachable"}
    _status_cache["gateway"]["result"] = result
    _status_cache["gateway"]["timestamp"] = now
    return result


@router.get("/system-status")
async def system_status():
    """Check gateway availability for the frontend."""
    gw_result = await _check_gateway()
    from backend.api.shutdown import active_count, is_shutting_down
    from backend.api.routes._payout import payouts_halted
    return {
        "operational": gw_result["ok"],
        "ark_mode": True,
        "payouts_halted": payouts_halted(),
        "inflight_payouts": active_count(),
        "shutting_down": is_shutting_down(),
        "services": {
            "gateway": gw_result,
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
