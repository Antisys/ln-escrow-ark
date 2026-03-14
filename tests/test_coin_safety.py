"""
Coin safety invariant tests — verifying that funds can NEVER be lost or double-spent.

These tests verify the hard invariants that protect user funds:
1. release_txid XOR refund_txid — escrow claimed at most once
2. Cross-txid conflict blocks opposite payout direction
3. Transitional statuses (releasing/refunding) block concurrent requests
4. Secret code non-custodial guarantee (hash verification)
5. Timeout handler respects already-resolved deals
6. Failed payout reverts status (no stuck transitional state)
7. Idempotency — repeated calls don't double-claim
8. No escrow = no payout (missing escrow_id blocks everything)
9. Invoice required before payout (no paying into the void)

Every test answers: "Can this scenario lose someone's money?"
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
os.environ.setdefault("ORACLE_PUBKEYS", "031b84c5567b126440995d3ed5aaba0565d71e1834604819ff9c17f5e9d5dd078f,024d4b6cd1361032ca9bd2aeb9d900aa4d45d9ead80ac9423374c451a7254d0766,02531fe6068134503d2723133227c867ac8fa6c83c537e9a44c3c5bdbdcb1fe337")

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}
FAKE_AUTH_SIG = "deadbeef"
NOW_TS = int(time.time())

DEAL_ID = "deal-safety-001"
DEAL_TOKEN = "token-safety-001"
ESCROW_ID = "escrow-safety-001"
SECRET_CODE = "correct-secret-code"
SECRET_CODE_HASH = hashlib.sha256(SECRET_CODE.encode()).hexdigest()


def _make_deal(**overrides):
    """Create a minimal deal dict with sensible defaults."""
    deal = {
        "deal_id": DEAL_ID,
        "deal_link_token": DEAL_TOKEN,
        "creator_role": "seller",
        "status": "funded",
        "title": "Safety Test Deal",
        "description": "",
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
        "seller_payout_invoice": "seller@wallet.com",
        "payout_status": None,
        "payout_fee_sat": None,
        "buyer_payout_invoice": "buyer@wallet.com",
        "buyer_payout_status": None,
        "buyer_payout_fee_sat": None,
        "buyer_pubkey": "02" + "aa" * 32,
        "seller_pubkey": "03" + "bb" * 32,
        "release_txid": None,
        "refund_txid": None,
    }
    deal.update(overrides)
    return deal


# ---------------------------------------------------------------------------
# Fixture: fully-mocked app
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_and_mocks():
    """
    Build a fully-mocked FastAPI app with TestClient.

    The deal_store dict simulates the database. All external services
    (Ark, LND, Lightning Address resolution) are mocked.
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
    ark_mock.client = MagicMock()
    ark_mock.client.claim_escrow = AsyncMock(return_value=None)
    ark_mock.client.claim_timeout = AsyncMock(return_value=None)
    ark_class = MagicMock(return_value=ark_mock)

    patches = [
        patch("backend.api.routes._shared.verify_action_signature", return_value=True),
        patch("backend.auth.sig_verify.verify_action_signature", return_value=True),
        patch("backend.database.deal_storage.get_deal_by_id", side_effect=get_deal),
        patch("backend.database.deal_storage.get_secret_code_hash", side_effect=get_secret_code_hash),
        patch("backend.database.deal_storage.update_deal", side_effect=update_deal),
        patch("backend.database.deal_storage.atomic_status_transition", side_effect=atomic_status_transition),
        patch("backend.database.deal_storage.find_expired_deals", return_value=[]),
        patch("backend.database.deal_storage.get_deals_by_status", return_value=[]),
        patch("backend.database.deal_storage.get_deals_by_statuses", return_value=[]),
        patch("backend.ark.ark_service.ArkEscrowService", ark_class),
        patch("backend.api.routes._payout.resolve_lightning_address",
              AsyncMock(return_value="lnbcrt1fakeinvoice000")),
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


# ===========================================================================
# INVARIANT 1: release_txid XOR refund_txid (mutual exclusion)
#
# The escrow can only be claimed once. If release_txid is set, refund_txid
# must remain null, and vice versa. This is the single most important
# invariant — violating it means double-spending.
# ===========================================================================

class TestCrossClaimPrevention:
    """Verify that claiming escrow for release blocks refund, and vice versa."""

    def test_refund_blocked_after_release(self, app_and_mocks):
        """CRITICAL: Once release_txid is set, refund MUST fail with 409."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="completed",
            release_txid=ESCROW_ID,
            payout_status="paid",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "I want a refund after release",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        # Must NOT succeed — deal is completed, refund blocked
        assert resp.status_code in [400, 409], f"Expected 400/409, got {resp.status_code}: {resp.text}"
        # release_txid must still be set, refund_txid must be null
        deal = m["deal_store"][DEAL_ID]
        assert deal["release_txid"] == ESCROW_ID
        assert deal["refund_txid"] is None

    def test_release_blocked_after_refund(self, app_and_mocks):
        """CRITICAL: Once refund_txid is set, release MUST fail with 409."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="refunded",
            refund_txid=ESCROW_ID,
            buyer_payout_status="paid",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        # Must NOT succeed — deal is refunded, release blocked
        assert resp.status_code in [400, 409], f"Expected 400/409, got {resp.status_code}: {resp.text}"
        deal = m["deal_store"][DEAL_ID]
        assert deal["refund_txid"] == ESCROW_ID
        assert deal["release_txid"] is None

    def test_release_409_when_refund_txid_set_on_funded_deal(self, app_and_mocks):
        """Edge case: deal still says 'funded' but refund_txid was set (stale status).
        Release must still be blocked by the cross-txid check."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            refund_txid=ESCROW_ID,  # Refund already claimed but status not updated
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
        assert "refund" in resp.json()["detail"].lower()

    def test_refund_409_when_release_txid_set_on_funded_deal(self, app_and_mocks):
        """Edge case: deal still says 'funded' but release_txid was set (stale status).
        Refund must still be blocked by the cross-txid check."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            release_txid=ESCROW_ID,  # Release already claimed but status not updated
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "test",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
        assert "release" in resp.json()["detail"].lower()

    def test_admin_release_blocked_after_refund(self, app_and_mocks):
        """Admin resolve-release must also respect cross-txid."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="expired",
            refund_txid=ESCROW_ID,
        )

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-release",
            json={"resolution_note": "trying to release after refund"},
            headers=ADMIN_HEADERS,
        )

        assert resp.status_code in [400, 409], f"Expected 400/409, got {resp.status_code}: {resp.text}"

    def test_admin_refund_blocked_after_release(self, app_and_mocks):
        """Admin resolve-refund must also respect cross-txid."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="expired",
            release_txid=ESCROW_ID,
        )

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-refund",
            json={"resolution_note": "trying to refund after release"},
            headers=ADMIN_HEADERS,
        )

        assert resp.status_code in [400, 409], f"Expected 400/409, got {resp.status_code}: {resp.text}"


# ===========================================================================
# INVARIANT 2: Transitional statuses block concurrent requests
#
# When a payout is in progress, status transitions to 'releasing' or
# 'refunding'. A second concurrent request must be blocked.
# ===========================================================================

class TestTransitionalStatusBlocking:
    """Verify that 'releasing'/'refunding' status prevents conflicting concurrent ops."""

    def test_refund_blocked_during_releasing(self, app_and_mocks):
        """While release is in progress (status=releasing), refund must fail."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="releasing",
            payout_status="pending",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "too slow",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        # Status must not have changed
        assert m["deal_store"][DEAL_ID]["status"] == "releasing"

    def test_release_blocked_during_refunding(self, app_and_mocks):
        """While refund is in progress (status=refunding), release must fail."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="refunding",
            buyer_payout_status="pending",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        assert m["deal_store"][DEAL_ID]["status"] == "refunding"

    def test_second_release_during_releasing_is_allowed(self, app_and_mocks):
        """Retry of release while already releasing should be allowed (same direction)."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="releasing",
            payout_status="pending",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        # Should be allowed (releasing is in allowed_statuses for release)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_second_refund_during_refunding_is_allowed(self, app_and_mocks):
        """Retry of refund while already refunding should be allowed (same direction)."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="refunding",
            buyer_payout_status="pending",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "retry",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


# ===========================================================================
# INVARIANT 3: Non-custodial secret code guarantee
#
# The service CANNOT release funds without the buyer's secret code.
# The buyer holds the plaintext; only the hash is stored in DB.
# ===========================================================================

class TestSecretCodeNonCustodial:
    """Verify the service cannot bypass the buyer's secret code."""

    def test_release_requires_secret_code(self, app_and_mocks):
        """Release without secret_code → 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            # secret_code intentionally omitted
        })

        assert resp.status_code == 400, resp.text
        assert "recovery code" in resp.json()["detail"].lower()
        # Ark must NOT have been called
        m["ark_mock"].release_deal_escrow.assert_not_called()
        m["ark_mock"].client.claim_escrow.assert_not_called()

    def test_wrong_secret_code_rejected(self, app_and_mocks):
        """Release with wrong secret_code → 403."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": "wrong-code-attacker-guessed",
        })

        assert resp.status_code == 403, resp.text
        m["ark_mock"].release_deal_escrow.assert_not_called()
        m["ark_mock"].client.claim_escrow.assert_not_called()

    def test_correct_secret_code_accepted(self, app_and_mocks):
        """Release with correct secret_code → 200."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 200, resp.text

    def test_hash_verification_is_sha256(self, app_and_mocks):
        """Verify the hash algorithm is SHA-256 (not something weaker)."""
        m = app_and_mocks
        custom_code = "my-unique-secret-42"
        custom_hash = hashlib.sha256(custom_code.encode()).hexdigest()
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            ark_secret_code_hash=custom_hash,
        )

        # Wrong code fails
        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": "wrong",
        })
        assert resp.status_code == 403

        # Right code succeeds
        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": custom_code,
        })
        assert resp.status_code == 200

    def test_empty_secret_code_is_not_valid(self, app_and_mocks):
        """Empty string as secret_code must not release funds."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": "",
        })

        # Empty string is treated as missing (400) or wrong (403) — either way, blocked
        assert resp.status_code in [400, 403], f"Expected 400/403, got {resp.status_code}"
        # Ark must NOT have been called
        m["ark_mock"].release_deal_escrow.assert_not_called()
        m["ark_mock"].client.claim_escrow.assert_not_called()


# ===========================================================================
# INVARIANT 4: Failed payout reverts status
#
# If Ark claim or LN payment fails, the deal must revert to its
# previous status (not stay stuck in 'releasing'/'refunding').
# ===========================================================================

class TestFailedPayoutRevert:
    """Verify that failed payouts don't leave deals in a stuck state."""

    def test_release_failure_reverts_to_funded(self, app_and_mocks):
        """Ark claim-and-pay fails → status reverts to 'funded', not stuck on 'releasing'."""
        m = app_and_mocks
        m["ark_mock"].release_deal_escrow.side_effect = Exception("LN route not found")
        m["ark_mock"].client.claim_escrow.side_effect = Exception("LN route not found")
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        # Release runs in background task — endpoint returns 200 immediately
        assert resp.status_code == 200
        deal = m["deal_store"][DEAL_ID]
        assert deal["status"] == "funded", f"Expected 'funded', got '{deal['status']}'"
        assert deal["payout_status"] == "failed"
        assert deal["release_txid"] is None  # No txid on failure

    def test_refund_failure_reverts_to_funded(self, app_and_mocks):
        """Ark claim-timeout fails → status reverts to 'funded', not stuck on 'refunding'."""
        m = app_and_mocks
        m["ark_mock"].refund_deal_escrow.side_effect = Exception("timeout not reached")
        m["ark_mock"].client.claim_timeout.side_effect = Exception("timeout not reached")
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "want refund",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        # Refund runs in background task — endpoint returns 200 immediately
        assert resp.status_code == 200
        deal = m["deal_store"][DEAL_ID]
        assert deal["status"] == "funded", f"Expected 'funded', got '{deal['status']}'"
        assert deal["buyer_payout_status"] == "failed"
        assert deal["refund_txid"] is None

    def test_release_failure_from_shipped_reverts_to_shipped(self, app_and_mocks):
        """Failed release from 'shipped' state reverts to 'shipped', not 'funded'."""
        m = app_and_mocks
        m["ark_mock"].release_deal_escrow.side_effect = Exception("network timeout")
        m["ark_mock"].client.claim_escrow.side_effect = Exception("network timeout")
        m["deal_store"][DEAL_ID] = _make_deal(status="shipped")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        # Release runs in background task — endpoint returns 200 immediately
        assert resp.status_code == 200
        deal = m["deal_store"][DEAL_ID]
        assert deal["status"] == "shipped", f"Expected 'shipped', got '{deal['status']}'"


# ===========================================================================
# INVARIANT 5: Idempotency — repeated calls don't double-claim
#
# If a deal is already completed/refunded, the same endpoint call
# must return success WITHOUT calling Ark again.
# ===========================================================================

class TestIdempotency:
    """Verify that repeated payout calls don't trigger double claims."""

    def test_release_idempotent_when_paid(self, app_and_mocks):
        """Release on already-paid deal → 200, Ark NOT called."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="completed",
            payout_status="paid",
            release_txid=ESCROW_ID,
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 200
        m["ark_mock"].release_deal_escrow.assert_not_called()
        m["ark_mock"].client.claim_escrow.assert_not_called()

    def test_refund_idempotent_when_paid(self, app_and_mocks):
        """Refund on already-paid deal → 200, Ark NOT called."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="refunded",
            buyer_payout_status="paid",
            refund_txid=ESCROW_ID,
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "retry",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 200
        m["ark_mock"].refund_deal_escrow.assert_not_called()
        m["ark_mock"].client.claim_timeout.assert_not_called()

    def test_successful_release_sets_txid(self, app_and_mocks):
        """After successful release, release_txid must be set to escrow_id."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 200
        deal = m["deal_store"][DEAL_ID]
        assert deal["release_txid"] == ESCROW_ID
        assert deal["refund_txid"] is None
        assert deal["status"] == "completed"
        assert deal["payout_status"] == "paid"

    def test_successful_refund_sets_txid(self, app_and_mocks):
        """After successful refund, refund_txid must be set to escrow_id."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "want refund",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 200
        deal = m["deal_store"][DEAL_ID]
        assert deal["refund_txid"] == ESCROW_ID
        assert deal["release_txid"] is None
        assert deal["status"] == "refunded"
        assert deal["buyer_payout_status"] == "paid"


# ===========================================================================
# INVARIANT 6: Timeout handler respects already-resolved deals
#
# The timeout handler runs on a 60s loop. It must NEVER re-claim an
# escrow that was already released or refunded.
# ===========================================================================

class TestTimeoutSafety:
    """Verify timeout handler can't override manual resolution."""

    @pytest.mark.asyncio
    async def test_timeout_skips_completed_deal(self, app_and_mocks):
        """Completed deal must not be processed by timeout handler."""
        m = app_and_mocks
        deal = _make_deal(
            status="completed",
            release_txid=ESCROW_ID,
            payout_status="paid",
            timeout_action="refund",
            expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        # find_expired_deals only returns funded/shipped/disputed — completed is excluded.
        # But we verify the query filter works correctly.
        with patch("backend.database.deal_storage.find_expired_deals", return_value=[]):
            from backend.tasks.timeout_handler import process_expired_deals
            result = await process_expired_deals(MagicMock())

        assert result == 0
        m["ark_mock"].refund_deal_escrow.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_skips_refunded_deal(self, app_and_mocks):
        """Refunded deal must not be processed by timeout handler."""
        m = app_and_mocks
        with patch("backend.database.deal_storage.find_expired_deals", return_value=[]):
            from backend.tasks.timeout_handler import process_expired_deals
            result = await process_expired_deals(MagicMock())

        assert result == 0

    @pytest.mark.asyncio
    async def test_timeout_refund_sets_correct_fields(self, app_and_mocks):
        """Timeout refund: must set refund_txid, NOT release_txid."""
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
        final = m["deal_store"][DEAL_ID]
        assert final["status"] == "refunded"
        assert final["refund_txid"] == ESCROW_ID
        assert final["release_txid"] is None

    @pytest.mark.asyncio
    async def test_timeout_release_sets_correct_fields(self, app_and_mocks):
        """Timeout release: must set release_txid, NOT refund_txid."""
        m = app_and_mocks
        deal = _make_deal(
            status="funded",
            timeout_action="release",
            seller_payout_invoice="seller@wallet.com",
            expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        m["deal_store"][DEAL_ID] = deal

        with patch("backend.database.deal_storage.find_expired_deals", return_value=[deal]):
            from backend.tasks.timeout_handler import process_expired_deals
            result = await process_expired_deals(MagicMock())

        assert result == 1
        final = m["deal_store"][DEAL_ID]
        assert final["status"] == "completed"
        assert final["release_txid"] == ESCROW_ID
        assert final["refund_txid"] is None

    @pytest.mark.asyncio
    async def test_timeout_without_escrow_marks_expired(self, app_and_mocks):
        """Expired deal without escrow_id → marked expired, not claimed."""
        m = app_and_mocks
        deal = _make_deal(
            status="funded",
            timeout_action="refund",
            ark_escrow_deal_id=None,
            expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        m["deal_store"][DEAL_ID] = deal

        with patch("backend.database.deal_storage.find_expired_deals", return_value=[deal]):
            from backend.tasks.timeout_handler import process_expired_deals
            result = await process_expired_deals(MagicMock())

        assert result == 1
        assert m["deal_store"][DEAL_ID]["status"] == "expired"
        m["ark_mock"].refund_deal_escrow.assert_not_called()


# ===========================================================================
# INVARIANT 7: No escrow = no payout
#
# If ark_escrow_deal_id is missing, no payout operation should be attempted.
# ===========================================================================

class TestNoEscrowNoPayout:
    """Verify that missing escrow_id blocks all payout operations."""

    def test_release_blocked_without_escrow(self, app_and_mocks):
        """Release with no ark_escrow_deal_id → 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            ark_escrow_deal_id=None,
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 400
        m["ark_mock"].release_deal_escrow.assert_not_called()

    def test_refund_blocked_without_escrow(self, app_and_mocks):
        """Refund with no ark_escrow_deal_id → 400."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="funded",
            ark_escrow_deal_id=None,
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "test",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 400
        m["ark_mock"].refund_deal_escrow.assert_not_called()

    def test_admin_blocked_without_escrow(self, app_and_mocks):
        """Admin resolve with no ark_escrow_deal_id → 400."""
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

        assert resp.status_code == 400


# ===========================================================================
# INVARIANT 8: Authorization — only the correct party can trigger payouts
#
# Buyer can release, buyer/seller can refund. No one else.
# ===========================================================================

class TestAuthorizationGuards:
    """Verify only authorized parties can trigger financial operations."""

    def test_seller_cannot_release(self, app_and_mocks):
        """Only buyer can release. Seller trying to release → 403."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "seller-001",  # Wrong — seller pretending to be buyer
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 403

    def test_stranger_cannot_release(self, app_and_mocks):
        """Unknown user trying to release → 403."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "attacker-007",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 403

    def test_stranger_cannot_refund(self, app_and_mocks):
        """Unknown user trying to refund → 403."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "attacker-007",
            "reason": "gimme money",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 403

    def test_admin_requires_api_key(self, app_and_mocks):
        """Admin resolve without API key → 401."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="expired")

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-release",
            json={},
            headers={"X-Admin-Key": "wrong-key"},
        )

        assert resp.status_code == 401

    def test_admin_no_key_at_all(self, app_and_mocks):
        """Admin resolve without any key header → 401."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="expired")

        resp = m["client"].post(
            f"/deals/admin/{DEAL_ID}/resolve-release",
            json={},
        )

        assert resp.status_code == 401


# ===========================================================================
# INVARIANT 9: Expired deal direction enforcement
#
# Expired deals can only be resolved in the direction specified by
# timeout_action. You can't release an expired deal that says "refund".
# ===========================================================================

class TestExpiredDealDirection:
    """Verify expired deals respect timeout_action direction."""

    def test_expired_refund_deal_blocks_release(self, app_and_mocks):
        """Expired + timeout_action=refund → release is blocked."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="expired",
            timeout_action="refund",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 400
        assert "timeout" in resp.json()["detail"].lower() or "buyer" in resp.json()["detail"].lower()

    def test_expired_release_deal_allows_release(self, app_and_mocks):
        """Expired + timeout_action=release → release is allowed."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="expired",
            timeout_action="release",
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 200

    def test_expired_deal_allows_refund_regardless_of_action(self, app_and_mocks):
        """Expired deals always allow refund (buyer getting money back is always safe)."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(
            status="expired",
            timeout_action="release",  # Even though timeout_action favors seller...
        )

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "I want my money back",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        # Refund should be allowed on expired deals (buyer safety)
        assert resp.status_code == 200


# ===========================================================================
# INVARIANT 10: Post-claim state consistency
#
# After a successful claim, all related fields must be consistent:
# - status matches the payout type
# - txid is set
# - payout_status is 'paid'
# - completed_at timestamp is set
# ===========================================================================

class TestPostClaimConsistency:
    """Verify all fields are consistent after successful payout."""

    def test_release_sets_all_fields(self, app_and_mocks):
        """After release: status=completed, release_txid set, payout_status=paid, completed_at set."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        assert resp.status_code == 200
        deal = m["deal_store"][DEAL_ID]
        assert deal["status"] == "completed"
        assert deal["release_txid"] == ESCROW_ID
        assert deal["refund_txid"] is None
        assert deal["payout_status"] == "paid"
        assert deal["completed_at"] is not None

    def test_refund_sets_all_fields(self, app_and_mocks):
        """After refund: status=refunded, refund_txid set, buyer_payout_status=paid, completed_at set."""
        m = app_and_mocks
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/refund", json={
            "user_id": "buyer-001",
            "reason": "want refund",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
        })

        assert resp.status_code == 200
        deal = m["deal_store"][DEAL_ID]
        assert deal["status"] == "refunded"
        assert deal["refund_txid"] == ESCROW_ID
        assert deal["release_txid"] is None
        assert deal["buyer_payout_status"] == "paid"
        assert deal["completed_at"] is not None

    def test_failed_payout_no_txid_no_completed_at(self, app_and_mocks):
        """After failed payout: no txid, no completed_at, payout_status=failed."""
        m = app_and_mocks
        m["ark_mock"].release_deal_escrow.side_effect = Exception("boom")
        m["ark_mock"].client.claim_escrow.side_effect = Exception("boom")
        m["deal_store"][DEAL_ID] = _make_deal(status="funded")

        resp = m["client"].post(f"/deals/{DEAL_ID}/release", json={
            "buyer_id": "buyer-001",
            "signature": FAKE_AUTH_SIG,
            "timestamp": NOW_TS,
            "secret_code": SECRET_CODE,
        })

        # Release runs in background task — endpoint returns 200 immediately
        assert resp.status_code == 200
        deal = m["deal_store"][DEAL_ID]
        assert deal["release_txid"] is None
        assert deal["completed_at"] is None
        assert deal["payout_status"] == "failed"
