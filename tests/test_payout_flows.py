"""
Comprehensive payout flow tests — covering release, refund, admin resolve, and timeout paths.

All escrow operations go through ArkEscrowService.

Mocks at three layers:
1. Signature verification → always passes
2. Deal storage → in-memory dicts
3. External services → ArkEscrowService (release_deal_escrow, refund_deal_escrow), resolve_lightning_address, WebSocket, notifications
"""
import hashlib
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

# Set env vars BEFORE importing any backend code
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("NETWORK", "testnet")
os.environ.setdefault("DISABLE_RATE_LIMIT", "true")
os.environ.setdefault("LND_REST_HOST", "localhost:8080")
os.environ.setdefault("LND_MACAROON_HEX", "00")
os.environ.setdefault("LND_TLS_CERT_PATH", "/dev/null")
# Oracle pubkeys (privkeys removed — non-custodial: service must not hold oracle keys)
os.environ.setdefault("ORACLE_PUBKEYS", "031b84c5567b126440995d3ed5aaba0565d71e1834604819ff9c17f5e9d5dd078f,024d4b6cd1361032ca9bd2aeb9d900aa4d45d9ead80ac9423374c451a7254d0766,02531fe6068134503d2723133227c867ac8fa6c83c537e9a44c3c5bdbdcb1fe337")

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}
FAKE_AUTH_SIG = "deadbeef"
NOW_TS = int(time.time())

DEAL_ID = "deal-test-001"
DEAL_TOKEN = "token-test-001"
ESCROW_ID = "escrow-test-001"
SECRET_CODE = "secret-code-test"
SECRET_CODE_HASH = hashlib.sha256(SECRET_CODE.encode()).hexdigest()


def _make_deal(**overrides):
    """Create a minimal deal dict with sensible defaults."""
    deal = {
        "deal_id": DEAL_ID,
        "deal_link_token": DEAL_TOKEN,
        "creator_role": "seller",
        "status": "funded",
        "title": "Test Deal",
        "description": "A test deal",
        "price_sats": 50000,
        "timeout_hours": 72,
        "timeout_action": "refund",
        "requires_tracking": False,
        "seller_id": "seller-001",
        "seller_name": "Alice",
        "buyer_id": "buyer-001",
        "buyer_name": "Bob",
        "seller_linking_pubkey": None,
        "buyer_linking_pubkey": None,
        "ark_escrow_deal_id": ESCROW_ID,
        "ark_secret_code_hash": SECRET_CODE_HASH,
        "invoice_bolt11": None,
        "ln_invoice": None,
        "ln_payment_hash": None,
        "tracking_carrier": None,
        "tracking_number": None,
        "shipping_notes": None,
        "created_at": "2026-01-01T00:00:00",
        "buyer_started_at": None,
        "buyer_joined_at": None,
        "funded_at": "2026-01-01T01:00:00",
        "shipped_at": None,
        "completed_at": None,
        "expires_at": None,
        "disputed_at": None,
        "disputed_by": None,
        "dispute_reason": None,
        "seller_payout_invoice": None,
        "payout_status": None,
        "payout_fee_sat": None,
        "buyer_payout_invoice": None,
        "buyer_payout_status": None,
        "buyer_payout_fee_sat": None,
        "buyer_pubkey": "02" + "aa" * 32,
        "seller_pubkey": "03" + "bb" * 32,
        "release_txid": None,
        "refund_txid": None,
    }
    deal.update(overrides)
    return deal


def _payout_success(**kw):
    """Return a successful payout result dict."""
    return {
        "success": True,
        "status": "SUCCEEDED",
        "amount_sats": 50000,
        "fee_sat": 5,
        "payment_preimage": "ab" * 32,
        "payout_type": "release",
        **kw,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_and_mocks():
    """
    Build a fully-mocked FastAPI app with TestClient.

    Patches:
    - deal_storage.get_deal_by_id / update_deal
    - sig_verify.verify_action_signature
    - ArkEscrowService (claim + pay_ln_invoice)
    - resolve_lightning_address (no real HTTP calls)
    - WebSocket manager
    - Notifications
    """
    deal_store = {}

    def get_deal(did):
        return deal_store.get(did)

    def get_secret_code_hash(did):
        deal = deal_store.get(did)
        return deal.get('ark_secret_code_hash') if deal else None

    def update_deal(did, **kw):
        if did in deal_store:
            for k, v in kw.items():
                if isinstance(v, datetime):
                    kw[k] = v.isoformat()
            deal_store[did].update(kw)
        return deal_store.get(did)

    def atomic_status_transition(did, expected_statuses, new_status, **extra):
        deal = deal_store.get(did)
        if not deal or deal.get('status') not in expected_statuses:
            return None
        deal['status'] = new_status
        for k, v in extra.items():
            if isinstance(v, datetime):
                extra[k] = v.isoformat()
            deal[k] = extra[k]
        return deal

    # Mock ArkEscrowService
    ark_mock = MagicMock()
    ark_mock.release_deal_escrow = AsyncMock(return_value=None)
    ark_mock.refund_deal_escrow = AsyncMock(return_value=None)
    ark_mock.resolve_deal_escrow_via_oracle = AsyncMock(return_value=None)
    ark_mock.resolve_and_pay_via_oracle = AsyncMock(return_value={"status": "success"})
    ark_mock.pay_from_wallet = AsyncMock(return_value={"status": "success"})
    # get_escrow_info returns a mock with default state (used by admin dispute resolution)
    _mock_escrow_info = MagicMock()
    _mock_escrow_info.state = "DisputedByBuyer"
    ark_mock.get_escrow_info = AsyncMock(return_value=_mock_escrow_info)
    # Mock the underlying client methods (used by recovery fallback paths)
    ark_mock.client = MagicMock()
    ark_mock.client.claim_escrow = AsyncMock(return_value=None)
    ark_mock.client.claim_timeout = AsyncMock(return_value=None)
    ark_class = MagicMock(return_value=ark_mock)

    patches = [
        # Sig verification — no-op
        patch("backend.api.routes._shared.verify_action_signature", return_value=True),
        patch("backend.auth.sig_verify.verify_action_signature", return_value=True),

        # Deal storage
        patch("backend.database.deal_storage.get_deal_by_id", side_effect=get_deal),
        patch("backend.database.deal_storage.get_secret_code_hash", side_effect=get_secret_code_hash),
        patch("backend.database.deal_storage.update_deal", side_effect=update_deal),
        patch("backend.database.deal_storage.atomic_status_transition", side_effect=atomic_status_transition),
        patch("backend.database.deal_storage.find_expired_deals", return_value=[]),
        patch("backend.database.deal_storage.get_deals_by_status", return_value=[]),
        patch("backend.database.deal_storage.get_deals_by_statuses", return_value=[]),

        # Ark escrow service
        patch("backend.ark.ark_service.ArkEscrowService", ark_class),

        # Lightning Address resolution — return a fake regtest BOLT11 (no real HTTP)
        patch("backend.api.routes._payout.resolve_lightning_address",
              AsyncMock(return_value="lnbcrt1fakeinvoice000")),

        # WebSocket — no-op
        patch("backend.api.routes._shared.ws_manager", MagicMock()),
        patch("backend.api.routes._shared._ws_notify", new_callable=AsyncMock),

    ]

    started = [p.start() for p in patches]

    from fastapi import FastAPI
    from backend.api.routes.release import router as release_router
    from backend.api.routes.refund import router as refund_router
    from backend.api.routes.admin import router as admin_router

    app = FastAPI()
    app.include_router(release_router, prefix="/deals")
    app.include_router(refund_router, prefix="/deals")
    app.include_router(admin_router, prefix="/deals")

    client = TestClient(app, raise_server_exceptions=False)

    yield {
        "client": client,
        "deal_store": deal_store,
        "ark_mock": ark_mock,
    }

    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# Group 1: Normal release (buyer clicks release)
# ---------------------------------------------------------------------------

class TestNormalRelease:
    """Buyer-initiated release via /release endpoint."""

    def test_release_all_ready(self, app_and_mocks):
        """#1: Buyer releases with invoice + secret_code present → completed + payout paid."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 200, resp.text
        deal = m["deal_store"][DEAL_ID]
        assert deal["status"] == "completed"
        assert deal["payout_status"] == "paid"
        m["ark_mock"].release_deal_escrow.assert_called_once()

    def test_release_rejected_without_secret_code(self, app_and_mocks):
        """#2a: Release without secret_code when hash is stored → HTTP 400 (non-custodial)."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            # secret_code intentionally omitted
        })

        assert resp.status_code == 400, resp.text
        assert "recovery code" in resp.json()["detail"].lower()

    def test_release_rejected_with_wrong_secret_code(self, app_and_mocks):
        """#2b: Release with wrong secret_code → HTTP 403 (non-custodial)."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": "wrong-secret-code",
        })

        assert resp.status_code == 403, resp.text

    def test_release_no_invoice_blocked(self, app_and_mocks):
        """#2: Release without seller invoice → HTTP 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            seller_payout_invoice=None,
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 400, resp.text
        assert "invoice" in resp.json()["detail"].lower() or "lightning" in resp.json()["detail"].lower()

    def test_release_idempotent_already_paid(self, app_and_mocks):
        """#3: Release on already-paid deal → 200, no double payment."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="completed",
            payout_status="paid",
            seller_payout_invoice="user@wallet.com",
            release_txid=ESCROW_ID,
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 200, resp.text
        m["ark_mock"].release_deal_escrow.assert_not_called()

    def test_release_ln_failure_reverts_state(self, app_and_mocks):
        """#4: claim-and-pay fails → 200 (background task), deal has payout_status=failed, no txid stored."""
        m = app_and_mocks
        m["ark_mock"].release_deal_escrow.side_effect = Exception("no route")
        m["ark_mock"].client.claim_escrow.side_effect = Exception("no route")
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        # Release now runs in background task — endpoint returns 200 immediately
        assert resp.status_code == 200, resp.text
        deal = m["deal_store"][DEAL_ID]
        assert deal["payout_status"] == "failed"
        # Claim+pay are atomic — no txid stored on failure
        assert deal.get("release_txid") is None

    def test_release_ark_claim_failure_reverts(self, app_and_mocks):
        """#5: Ark claim-and-pay fails → background task reverts status to funded."""
        m = app_and_mocks
        m["ark_mock"].release_deal_escrow.side_effect = Exception("claim failed")
        m["ark_mock"].client.claim_escrow.side_effect = Exception("claim failed")
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        # Release now runs in background task — endpoint returns 200 immediately
        assert resp.status_code == 200, resp.text
        assert m["deal_store"][DEAL_ID]["status"] == "funded"


# ---------------------------------------------------------------------------
# Group 2: Refund (buyer or seller triggers refund)
# ---------------------------------------------------------------------------

class TestRefund:
    """Refund via /refund endpoint."""

    def test_refund_all_ready(self, app_and_mocks):
        """#6: Refund with invoice → refunded + buyer payout paid."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            buyer_payout_invoice="buyer@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "Item not received",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 200, resp.text
        deal = m["deal_store"][DEAL_ID]
        assert deal["status"] == "refunded"
        assert deal["buyer_payout_status"] == "paid"

    def test_refund_no_invoice_blocked(self, app_and_mocks):
        """#7: Refund without buyer invoice → HTTP 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            buyer_payout_invoice=None,
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "test",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 400, resp.text

    def test_refund_seller_can_initiate(self, app_and_mocks):
        """#8: Seller can also trigger a refund (mutual agreement)."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            buyer_payout_invoice="buyer@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "seller-001",
            "reason": "Seller agrees to refund",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 200, resp.text
        assert m["deal_store"][DEAL_ID]["status"] == "refunded"


# ---------------------------------------------------------------------------
# Group 3: Admin resolve → release
# ---------------------------------------------------------------------------

class TestAdminRelease:
    """Admin resolves deal in seller's favour (non-custodial: no secret_code access)."""

    def test_admin_release_disputed_signs_oracle(self, app_and_mocks):
        """#9: Admin resolves disputed deal by signing oracle attestations server-side."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="disputed",
            seller_payout_invoice="user@wallet.com",
        )

        fake_attestations = [{"pubkey": "02aa", "signature": "sig", "content": {"escrow_id": ESCROW_ID, "outcome": "Seller"}}]
        with patch("backend.api.routes.admin._sign_oracle_attestations", return_value=fake_attestations):
            resp = m["client"].post(
                f"/deals/admin/{DEAL_ID}/resolve-release",
                json={"resolution_note": "Seller wins"},
                headers=ADMIN_HEADERS,
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["resolution"] == "released"
        assert m["deal_store"][DEAL_ID]["status"] == "completed"

    def test_admin_release_no_invoice(self, app_and_mocks):
        """#10: No seller invoice → HTTP 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="disputed",
            seller_payout_invoice=None,
        )

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-release",
            json={},
            headers=ADMIN_HEADERS,
        )

        assert resp.status_code == 400, resp.text
        assert "Lightning Address" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Group 4: Admin resolve → refund
# ---------------------------------------------------------------------------

class TestAdminRefund:
    """Admin resolves deal in buyer's favour (non-custodial)."""

    def test_admin_refund_disputed_signs_oracle(self, app_and_mocks):
        """#12: Admin resolves disputed deal in buyer's favour by signing oracle attestations."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="disputed",
            buyer_payout_invoice="buyer@wallet.com",
        )

        fake_attestations = [{"pubkey": "02aa", "signature": "sig", "content": {"escrow_id": ESCROW_ID, "outcome": "Buyer"}}]
        with patch("backend.api.routes.admin._sign_oracle_attestations", return_value=fake_attestations):
            resp = m["client"].post(
                f"/deals/admin/{DEAL_ID}/resolve-refund",
                json={"resolution_note": "Buyer wins"},
                headers=ADMIN_HEADERS,
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["resolution"] == "refunded"
        assert m["deal_store"][DEAL_ID]["status"] == "refunded"

    def test_admin_refund_no_invoice(self, app_and_mocks):
        """#13: No buyer invoice → HTTP 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="disputed",
            buyer_payout_invoice=None,
        )

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-refund",
            json={},
            headers=ADMIN_HEADERS,
        )

        assert resp.status_code == 400, resp.text
        assert "Lightning Address" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Group 5: Timeout → release / refund
# ---------------------------------------------------------------------------

class TestTimeoutRelease:
    """Timeout handler auto-releases when timeout_action=release."""

    @pytest.mark.asyncio
    async def test_timeout_release_all_ready(self, app_and_mocks):
        """#14: Invoice ready → completed + payout paid."""
        m = app_and_mocks
        deal = _make_deal(
            status="funded",
            timeout_action="release",
            seller_payout_invoice="user@wallet.com",
            expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        m["deal_store"][DEAL_ID] = deal

        with patch("backend.database.deal_storage.find_expired_deals", return_value=[deal]):
            from backend.tasks.timeout_handler import process_expired_deals
            result = await process_expired_deals(MagicMock())

        assert result == 1
        assert m["deal_store"][DEAL_ID]["status"] == "completed"
        assert m["deal_store"][DEAL_ID]["payout_status"] == "paid"

    @pytest.mark.asyncio
    async def test_timeout_release_no_escrow(self, app_and_mocks):
        """#15: No ark_escrow_deal_id → expired (parked)."""
        m = app_and_mocks
        deal = _make_deal(
            status="funded",
            timeout_action="release",
            seller_payout_invoice="user@wallet.com",
            ark_escrow_deal_id=None,
            expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        m["deal_store"][DEAL_ID] = deal

        with patch("backend.database.deal_storage.find_expired_deals", return_value=[deal]):
            from backend.tasks.timeout_handler import process_expired_deals
            result = await process_expired_deals(MagicMock())

        assert result == 1
        assert m["deal_store"][DEAL_ID]["status"] == "expired"

    @pytest.mark.asyncio
    async def test_timeout_release_no_invoice(self, app_and_mocks):
        """#16: No seller invoice → expired (parked)."""
        m = app_and_mocks
        deal = _make_deal(
            status="funded",
            timeout_action="release",
            seller_payout_invoice=None,
            expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        m["deal_store"][DEAL_ID] = deal

        with patch("backend.database.deal_storage.find_expired_deals", return_value=[deal]):
            from backend.tasks.timeout_handler import process_expired_deals
            result = await process_expired_deals(MagicMock())

        assert result == 1
        assert m["deal_store"][DEAL_ID]["status"] == "expired"


class TestTimeoutRefund:
    """Timeout handler auto-refunds when timeout_action=refund."""

    @pytest.mark.asyncio
    async def test_timeout_refund_all_ready(self, app_and_mocks):
        """#17: Buyer invoice ready → refunded + buyer payout paid."""
        m = app_and_mocks
        deal = _make_deal(
            status="funded",
            timeout_action="refund",
            buyer_payout_invoice="buyer@wallet.com",
            expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        m["deal_store"][DEAL_ID] = deal

        with patch("backend.database.deal_storage.find_expired_deals", return_value=[deal]):
            from backend.tasks.timeout_handler import process_expired_deals
            result = await process_expired_deals(MagicMock())

        assert result == 1
        assert m["deal_store"][DEAL_ID]["status"] == "refunded"
        assert m["deal_store"][DEAL_ID]["buyer_payout_status"] == "paid"

    @pytest.mark.asyncio
    async def test_timeout_refund_no_invoice(self, app_and_mocks):
        """#18: No buyer invoice → expired (parked)."""
        m = app_and_mocks
        deal = _make_deal(
            status="funded",
            timeout_action="refund",
            buyer_payout_invoice=None,
            expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        m["deal_store"][DEAL_ID] = deal

        with patch("backend.database.deal_storage.find_expired_deals", return_value=[deal]):
            from backend.tasks.timeout_handler import process_expired_deals
            result = await process_expired_deals(MagicMock())

        assert result == 1
        assert m["deal_store"][DEAL_ID]["status"] == "expired"


# ---------------------------------------------------------------------------
# Group 6: Auth & status guards
# ---------------------------------------------------------------------------

class TestAuthGuards:
    """Wrong user IDs must be rejected."""

    def test_release_wrong_buyer(self, app_and_mocks):
        """Release with wrong buyer_id → 403."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "wrong-buyer",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 403, resp.text

    def test_refund_wrong_user(self, app_and_mocks):
        """Refund with unknown user_id → 403."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "unknown-user",
            "reason": "test",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 403, resp.text


class TestStatusGuards:
    """Endpoints must reject requests for deals in wrong status."""

    def test_release_rejects_completed(self, app_and_mocks):
        """Cannot release an already completed deal (if not yet paid)."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="completed",
            payout_status=None,
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        # completed + not paid → 400 (not in allowed statuses, not idempotent)
        assert resp.status_code == 400, resp.text

    def test_refund_rejects_completed(self, app_and_mocks):
        """Cannot refund an already completed deal."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="completed",
            buyer_payout_invoice="buyer@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "test",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 400, resp.text

    def test_admin_rejects_funded_deal(self, app_and_mocks):
        """Admin cannot resolve a funded deal (must be disputed or expired)."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-release",
            json={},
            headers=ADMIN_HEADERS,
        )

        assert resp.status_code == 400, resp.text

    def test_admin_rejects_no_escrow(self, app_and_mocks):
        """Admin cannot resolve a deal with no Ark escrow."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="disputed",
            ark_escrow_deal_id=None,
        )

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-release",
            json={},
            headers=ADMIN_HEADERS,
        )

        assert resp.status_code == 400, resp.text

    def test_admin_rejects_without_key(self, app_and_mocks):
        """Admin endpoints require valid API key."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="disputed")

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-release",
            json={},
            headers={"X-Admin-Key": "wrong-key"},
        )

        assert resp.status_code == 401, resp.text


class TestMissingEscrow:
    """Endpoints must fail gracefully when Ark escrow is missing."""

    def test_release_no_escrow_id(self, app_and_mocks):
        """Release with no ark_escrow_deal_id → 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            ark_escrow_deal_id=None,
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 400, resp.text

    def test_refund_no_escrow_id(self, app_and_mocks):
        """Refund with no ark_escrow_deal_id → 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            ark_escrow_deal_id=None,
            buyer_payout_invoice="buyer@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "test",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 400, resp.text

    def test_deal_not_found(self, app_and_mocks):
        """Any endpoint with unknown deal_id → 404."""
        m = app_and_mocks

        resp = m["client"].post("/deals/nonexistent/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Group 7: Expired deal direction guards
# ---------------------------------------------------------------------------

class TestExpiredDealDirectionGuards:
    """Expired deals must respect timeout_action direction."""

    def test_expired_release_allowed(self, app_and_mocks):
        """Expired with timeout_action=release → release OK."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="expired",
            timeout_action="release",
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 200, resp.text

    def test_expired_refund_blocks_release(self, app_and_mocks):
        """Expired with timeout_action=refund → release returns 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="expired",
            timeout_action="refund",
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# Group 8: Admin on expired deals
# ---------------------------------------------------------------------------

class TestAdminOnExpiredDeals:
    """Admin resolve should work on expired deals (not just disputed)."""

    def test_admin_release_expired_deal(self, app_and_mocks):
        """Admin releases an expired deal via timeout claim (no secret_code needed)."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="expired",
            timeout_action="release",
            seller_payout_invoice="user@wallet.com",
        )

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-release",
            json={"resolution_note": "Late release"},
            headers=ADMIN_HEADERS,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["resolution"] == "released"
        assert m["deal_store"][DEAL_ID]["status"] == "completed"

    def test_admin_refund_expired_deal(self, app_and_mocks):
        """Admin refunds an expired deal."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="expired",
            buyer_payout_invoice="buyer@wallet.com",
        )

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-refund",
            json={"resolution_note": "Late refund"},
            headers=ADMIN_HEADERS,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["resolution"] == "refunded"
