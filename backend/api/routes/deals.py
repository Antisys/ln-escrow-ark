"""
Deal API endpoints — backward-compatible shim.

All route code now lives in split modules:
    crud.py      — create, get, list, join
    signing.py   — register-key, signing-status, buyer-release
    funding.py   — create-ln-invoice, check-ln-invoice
    payout.py    — ship, submit-payout-invoice (seller)
    release.py   — Ark release
    refund.py    — submit-refund-invoice, Ark refund, dispute
    admin.py     — admin endpoints, limits, fees

This file combines all sub-routers into a single `router` and re-exports
helpers used by other parts of the codebase (timeout_handler).
"""
from fastapi import APIRouter

# Import sub-routers
from backend.api.routes.crud import router as crud_router
from backend.api.routes.signing import router as signing_router
from backend.api.routes.funding import router as funding_router
from backend.api.routes.payout import router as payout_router
from backend.api.routes.release import router as release_router
from backend.api.routes.refund import router as refund_router
from backend.api.routes.admin import router as admin_router

# Combine all sub-routers into one
router = APIRouter()
router.include_router(crud_router)
router.include_router(signing_router)
router.include_router(funding_router)
router.include_router(payout_router)
router.include_router(release_router)
router.include_router(refund_router)
router.include_router(admin_router)
