"""
Smoke tests — catch broken imports, missing functions, and endpoint registration.

These run BEFORE deploy. If any fail, deploy is aborted.
No mocks needed — these just verify the code loads without crashing.
"""
import os
import importlib
import pytest

# Minimal env so modules can load without real LND/DB
os.environ.setdefault("NETWORK", "testnet")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("ADMIN_PUBKEYS", "02test_pubkey_for_smoke_tests")
os.environ.setdefault("LND_REST_HOST", "localhost:8080")
os.environ.setdefault("LND_MACAROON_HEX", "00")
os.environ.setdefault("LND_TLS_CERT_PATH", "/dev/null")
os.environ.setdefault("DISABLE_RATE_LIMIT", "true")


# ---------------------------------------------------------------------------
# 1. Every backend module imports without error
# ---------------------------------------------------------------------------

BACKEND_MODULES = [
    # Route modules (most likely to have broken imports after refactoring)
    "backend.api.routes._shared",
    "backend.api.routes._payout",
    "backend.api.routes.crud",
    "backend.api.routes.signing",
    "backend.api.routes.funding",
    "backend.api.routes.payout",
    "backend.api.routes.release",
    "backend.api.routes.refund",
    "backend.api.routes.admin",
    "backend.api.routes.auth",
    "backend.api.routes.health",
    "backend.api.routes.qr",
    "backend.api.routes.websockets",
    # Lightning
    "backend.lightning.lnd_client",
    # Database
    "backend.database.models",
    "backend.database.deal_storage",
    "backend.database.connection",
    # Auth
    "backend.auth.lnurl_auth",
    "backend.auth.sig_verify",
    # Tasks
    "backend.tasks.timeout_handler",
    # Config
    "backend.config",
]


@pytest.mark.parametrize("module_name", BACKEND_MODULES)
def test_module_imports(module_name):
    """Every backend module must import without error."""
    try:
        importlib.import_module(module_name)
    except Exception as e:
        pytest.fail(f"Failed to import {module_name}: {e}")


# ---------------------------------------------------------------------------
# 2. The FastAPI app assembles without crashing
# ---------------------------------------------------------------------------

def test_app_creates():
    """The main app object must exist and have routes registered."""
    from backend.api.routes.crud import router as crud_router
    from backend.api.routes.signing import router as signing_router
    from backend.api.routes.funding import router as funding_router
    from backend.api.routes.payout import router as payout_router
    from backend.api.routes.release import router as release_router
    from backend.api.routes.refund import router as refund_router
    from backend.api.routes.admin import router as admin_router
    from backend.api.routes.auth import router as auth_router
    from backend.api.routes.health import router as health_router

    # Verify each router has routes
    for name, router in [
        ("crud", crud_router),
        ("signing", signing_router),
        ("funding", funding_router),
        ("payout", payout_router),
        ("release", release_router),
        ("refund", refund_router),
        ("admin", admin_router),
        ("auth", auth_router),
        ("health", health_router),
    ]:
        assert len(router.routes) > 0, f"Router '{name}' has no routes registered"


# ---------------------------------------------------------------------------
# 3. Critical functions exist and are callable
# ---------------------------------------------------------------------------

def test_execute_ark_payout_exists():
    """execute_ark_payout must exist (Ark-only resolution path)."""
    from backend.api.routes._payout import execute_ark_payout
    assert callable(execute_ark_payout)


def test_verify_action_signature_exists():
    """Signature verification must exist."""
    from backend.auth.sig_verify import verify_action_signature
    assert callable(verify_action_signature)


def test_deal_storage_functions():
    """Deal storage CRUD functions must exist."""
    from backend.database import deal_storage
    for fn_name in [
        "create_deal", "get_deal_by_id", "get_deal_by_token",
        "update_deal", "find_expired_deals",
    ]:
        fn = getattr(deal_storage, fn_name, None)
        assert fn is not None, f"deal_storage.{fn_name} missing"
        assert callable(fn), f"deal_storage.{fn_name} not callable"


def test_deal_storage_functions_extended():
    """Ark-related deal storage functions must exist."""
    from backend.database import deal_storage
    for fn_name in ["set_deal_funded", "update_deal"]:
        fn = getattr(deal_storage, fn_name, None)
        assert fn is not None, f"deal_storage.{fn_name} missing"
        assert callable(fn), f"deal_storage.{fn_name} not callable"


def test_db_session_function():
    """Database session function must exist at correct import path."""
    from backend.database.connection import get_db_session
    assert callable(get_db_session)


# ---------------------------------------------------------------------------
# 4. Pydantic models validate correctly
# ---------------------------------------------------------------------------

def test_deal_response_model():
    """DealResponse must accept all expected fields without crashing."""
    from backend.api.routes._shared import DealResponse
    # All required fields for DealResponse
    resp = DealResponse(
        deal_id="test",
        deal_link_token="tok",
        deal_link="https://example.com/join/tok",
        creator_role="seller",
        status="funded",
        title="Test",
        description=None,
        price_sats=50000,
        timeout_hours=48,
        timeout_action="refund",
        requires_tracking=False,
        seller_id=None, seller_name=None,
        buyer_id=None, buyer_name=None,
        seller_linking_pubkey=None, buyer_linking_pubkey=None,
        invoice_bolt11=None, ln_invoice=None, ln_payment_hash=None,
        tracking_carrier=None, tracking_number=None, shipping_notes=None,
        created_at="2026-01-01T00:00:00",
        buyer_started_at=None, buyer_joined_at=None,
        funded_at=None, shipped_at=None, completed_at=None,
        expires_at=None, disputed_at=None, disputed_by=None, dispute_reason=None,
    )
    assert resp.deal_id == "test"


def test_signing_status_response_model():
    """SigningStatusResponse fields must match what signing.py returns."""
    from backend.api.routes._shared import SigningStatusResponse
    resp = SigningStatusResponse(
        deal_id="test",
        phase="setup",
        buyer_pubkey_registered=False,
        seller_pubkey_registered=False,
        buyer_signed=False,
        seller_signed=False,
        multisig_address=None,
        ready_for_funding=False,
        ready_for_resolution=False,
    )
    # HTLC fields must NOT exist (removed in HTLC cleanup)
    assert not hasattr(resp, 'htlc_tx_hex')
    assert not hasattr(resp, 'htlc_refund_tx_hex')
    # admin_refund fields must NOT exist (dead code removed)
    assert not hasattr(resp, 'admin_refund_tx_hex')


# ---------------------------------------------------------------------------
# 5. Config loads without error
# ---------------------------------------------------------------------------

def test_config_loads():
    """Config must load with sensible defaults."""
    from backend.config import CONFIG
    # At least one admin auth method must be configured
    assert CONFIG.admin_api_key or CONFIG.admin_pubkeys


# ---------------------------------------------------------------------------
# 6. Money-critical: timeout_handler imports payout from correct location
# ---------------------------------------------------------------------------

def test_timeout_handler_payout_import():
    """
    timeout_handler must import process_gateway_payout from _payout, NOT deals.
    This was a real bug — wrong import path caused silent failures on deal expiry,
    meaning expired deals never got their LN payout.
    """
    import ast
    import inspect
    from backend.tasks import timeout_handler

    source = inspect.getsource(timeout_handler)
    # Check that no import references the old location
    assert "from backend.api.routes.deals import process_gateway_payout" not in source, \
        "timeout_handler still imports process_gateway_payout from deals (moved to _payout)"


# ---------------------------------------------------------------------------
# 7. VaultService has no undefined attribute access
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 8. No print() statements in production code (should use logger)
# ---------------------------------------------------------------------------

def test_no_print_in_routes():
    """Route modules should use logger, not print()."""
    import ast
    import inspect
    import importlib
    route_modules = [
        "backend.api.routes._payout",
        "backend.api.routes.crud",
        "backend.api.routes.signing",
        "backend.api.routes.funding",
        "backend.api.routes.release",
        "backend.api.routes.refund",
        "backend.api.routes.admin",
    ]
    violations = []
    for mod_name in route_modules:
        mod = importlib.import_module(mod_name)
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == 'print':
                    violations.append(f"{mod_name}:{node.lineno}")
    assert not violations, \
        f"print() found in route modules (use logger instead): {violations}"

