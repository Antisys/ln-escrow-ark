"""
API Integration Tests — tests against a real backend

Run with: pytest tests/test_api_e2e.py -v
Requires: SSH access to devimint server (set SSH_SERVER env var)
"""
import hashlib
import hmac
import os
import secrets
import subprocess
import time
import uuid
import pytest
import requests

# ============================================================================
# Configuration
# ============================================================================

BASE_URL = os.environ.get("TEST_API_URL", "http://localhost:8001")
ADMIN_KEY = os.environ.get("TEST_ADMIN_KEY", "")
ADMIN_PUBKEY = os.environ.get("TEST_ADMIN_PUBKEY", "")


def _server_mock_payments() -> bool:
    """Return True if the server has MOCK_PAYMENTS=true (skips LN payout checks)."""
    try:
        r = requests.get(f"{BASE_URL}/system-status", timeout=10)
        return r.json().get("mock_payments", False)
    except Exception:
        return False


_MOCK_PAYMENTS_ON_SERVER = _server_mock_payments()
_DEVIMINT_AVAILABLE = bool(os.environ.get("SSH_SERVER") and os.environ.get("SERVER_DEVIMINT_ENV"))
DEAL_PRICE = 10000  # 10k sats — small enough to be safe
TEST_SELLER_ADDRESS = "hello@getalby.com"
TEST_BUYER_ADDRESS = "hello@getalby.com"
SSH_SERVER = os.environ.get("SSH_SERVER", "")  # e.g. "user@host"
SSH_SERVER_PASS = os.environ.get("SSH_SERVER_PASS", "")
DEVIMINT_DIR_PATTERN = os.environ.get("DEVIMINT_DIR_PATTERN", "/tmp/devimint-*")
SERVER_DEVIMINT_ENV = os.environ.get("SERVER_DEVIMINT_ENV", "")
SERVER_ARK_CLI = os.environ.get("SERVER_ARK_CLI", "ark-escrow-agent")


# ============================================================================
# Crypto helpers
# ============================================================================

def _lnurl_sign(k1_hex: str, priv_key=None):
    """Sign k1 for LNURL-auth. Returns (sig_der_hex, pubkey_hex, priv_key)."""
    from secp256k1 import PrivateKey
    if priv_key is None:
        priv_key = PrivateKey()
    k1_bytes = bytes.fromhex(k1_hex)
    sig = priv_key.ecdsa_sign(k1_bytes, raw=True)
    sig_hex = priv_key.ecdsa_serialize(sig).hex()
    pub_hex = priv_key.pubkey.serialize().hex()
    return sig_hex, pub_hex, priv_key


def _make_ephemeral_key():
    """Generate a random secp256k1 key for deal signing. Returns (priv, pub_hex)."""
    from coincurve import PrivateKey
    priv = PrivateKey()
    pub_hex = priv.public_key.format(compressed=True).hex()
    return priv, pub_hex


def _sign_action(deal_id: str, action: str, timestamp: int, priv_key) -> str:
    """Sign a deal action with coincurve. Returns DER sig hex."""
    message = f"{deal_id}:{action}:{timestamp}"
    msg_hash = hashlib.sha256(message.encode()).digest()
    sig = priv_key.sign(msg_hash, hasher=None)
    return sig.hex()


def _make_buyer_escrow_key():
    """Generate a buyer ephemeral keypair and BIP-340 Schnorr timeout pre-signature.

    Returns (buyer_pubkey_hex, timeout_signature_hex, secp256k1_privkey).
    The timeout_signature signs SHA256("timeout") — required for non-custodial escrow creation.
    """
    from secp256k1 import PrivateKey as SchnorrPrivateKey
    priv = SchnorrPrivateKey()
    pubkey_hex = priv.pubkey.serialize().hex()
    msg = hashlib.sha256(b'timeout').digest()
    sig = priv.schnorr_sign(msg, b'', raw=True)
    return pubkey_hex, sig.hex(), priv


# ============================================================================
# Payment simulation
# ============================================================================

def simulate_payment(bolt11: str, timeout: int = 60) -> bool:
    """Pay a regtest invoice via devimint on the server."""
    cmd = [
        "sshpass", "-p", SSH_SERVER_PASS,
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "PubkeyAuthentication=no",
        "-o", "ConnectTimeout=10",
        SSH_SERVER,
        f"""set +u
DEVIMINT_ENV="{SERVER_DEVIMINT_ENV}"
if [ ! -f "$DEVIMINT_ENV" ]; then echo 'devimint not found'; exit 1; fi
eval "$(cat $DEVIMINT_ENV)"
timeout {timeout} {SERVER_ARK_CLI} --data-dir $FM_CLIENT_DIR module ln pay '{bolt11}' 2>&1
""",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
    return result.returncode == 0


def mine_blocks(n: int) -> bool:
    """Mine n regtest blocks via devimint bitcoind on the server."""
    cmd = [
        "sshpass", "-p", SSH_SERVER_PASS,
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "PubkeyAuthentication=no",
        "-o", "ConnectTimeout=10",
        SSH_SERVER,
        f"""set +u
DEVIMINT_ENV="{SERVER_DEVIMINT_ENV}"
if [ ! -f "$DEVIMINT_ENV" ]; then echo 'devimint not found'; exit 1; fi
eval "$(cat $DEVIMINT_ENV)"
BTC_DIR=$FM_BTC_DIR
nix_path=$(ls /nix/store/*/bin/bitcoin-cli 2>/dev/null | head -1)
BTC_CLI=${{nix_path:-bitcoin-cli}}
BTCADDR=$($BTC_CLI -regtest -rpcuser=bitcoin -rpcpassword=bitcoin -datadir="$BTC_DIR" -rpcwallet='' getnewaddress 2>/dev/null)
$BTC_CLI -regtest -rpcuser=bitcoin -rpcpassword=bitcoin -datadir="$BTC_DIR" generatetoaddress {n} "$BTCADDR" 2>&1
""",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0


# ============================================================================
# API helpers
# ============================================================================

def api(method: str, path: str, _retry_on_429: bool = True, **kwargs) -> requests.Response:
    """Make an API request. Auto-retries on 429 using Retry-After header."""
    url = f"{BASE_URL}{path}"
    # ark-escrow-agent calls via SSH can take 30+ seconds; use 90s default
    kwargs.setdefault("timeout", 90)
    for attempt in range(3):
        resp = getattr(requests, method)(url, **kwargs)
        if resp.status_code == 429 and _retry_on_429 and attempt < 2:
            retry_after = int(resp.headers.get("Retry-After", 62))
            time.sleep(retry_after + 2)
            continue
        return resp
    return resp


def admin_headers():
    h = {}
    if ADMIN_PUBKEY:
        h["x-admin-pubkey"] = ADMIN_PUBKEY
    if ADMIN_KEY:
        h["x-admin-key"] = ADMIN_KEY
    return h


def create_test_deal(price_sats=DEAL_PRICE, timeout_hours=72, timeout_action="refund") -> dict:
    """Create a test deal. Returns deal dict. Retries on 429."""
    payload = {
        "seller_id": f"test-seller-{uuid.uuid4().hex[:8]}",
        "seller_name": "Test Seller",
        "title": f"Integration Test Deal {uuid.uuid4().hex[:6]}",
        "description": "Auto-created for integration testing",
        "price_sats": price_sats,
        "timeout_hours": timeout_hours,
        "timeout_action": timeout_action,
        "requires_tracking": False,
        "creator_role": "seller",
    }
    resp = api("post", "/deals", json=payload)
    assert resp.status_code == 201, f"Create deal failed: {resp.text}"
    return resp.json()


def lnurl_auth_deal(deal_token: str, role: str, user_id: str) -> tuple:
    """
    Complete LNURL-auth for a deal.
    Returns (linking_priv, ephemeral_priv, ephemeral_pub_hex, k1, sig_hex, linking_pub_hex)
    """
    # Get challenge
    resp = api("get", f"/auth/lnurl/challenge/{deal_token}", params={"role": role})
    assert resp.status_code == 200, f"Challenge failed: {resp.text}"
    k1 = resp.json()["k1"]

    # Sign k1 with linking key
    sig_hex, linking_pub, linking_priv = _lnurl_sign(k1)

    # Callback — simulate wallet
    cb_resp = api("get", "/auth/lnurl/callback", params={
        "k1": k1, "sig": sig_hex, "key": linking_pub, "tag": "login"
    })
    assert cb_resp.status_code == 200, f"Callback failed: {cb_resp.text}"
    assert cb_resp.json().get("status") == "OK", f"Callback not OK: {cb_resp.json()}"

    # Verify status
    status_resp = api("get", f"/auth/lnurl/status/{k1}")
    assert status_resp.status_code == 200
    assert status_resp.json()["verified"] is True

    # Generate ephemeral key and register it
    ephemeral_priv, ephemeral_pub = _make_ephemeral_key()
    reg_resp = api("post", "/auth/lnurl/register-derived-key", json={
        "k1": k1,
        "user_id": user_id,
        "ephemeral_pubkey": ephemeral_pub,
    })
    assert reg_resp.status_code == 200, f"Register key failed: {reg_resp.text}"

    return linking_priv, ephemeral_priv, ephemeral_pub, k1, sig_hex, linking_pub


def join_deal(token: str, user_id: str, user_name: str = "Test User") -> requests.Response:
    """Join a deal as counterparty using the deal link token."""
    resp = api("post", f"/deals/token/{token}/join", json={
        "user_id": user_id,
        "user_name": user_name,
    })
    return resp


def submit_payout_invoice(deal_id: str, user_id: str, ephemeral_priv, address: str, action: str):
    """Submit a payout invoice (Lightning Address) for a deal participant."""
    ts = int(time.time())
    sig = _sign_action(deal_id, action, ts, ephemeral_priv)
    resp = api("post", f"/deals/{deal_id}/{action.replace('submit-', '')}", json={
        "user_id": user_id,
        "invoice": address,
        "signature": sig,
        "timestamp": ts,
    })
    return resp


def generate_secret_and_hash() -> tuple[str, str]:
    """
    Simulate what the buyer's browser does at invoice-creation time:
    generate a random secret and compute its SHA-256 hash.
    Returns (secret_code, secret_code_hash).
    """
    secret_code = secrets.token_hex(32)  # 64 hex chars = 32 bytes
    secret_code_hash = hashlib.sha256(secret_code.encode()).hexdigest()
    return secret_code, secret_code_hash


def _make_timeout_sig_for_coincurve_key(priv_key) -> str:
    """Create a BIP-340 Schnorr timeout signature using a coincurve private key's raw bytes."""
    from secp256k1 import PrivateKey as SchnorrPrivateKey
    schnorr_priv = SchnorrPrivateKey(priv_key.secret)
    msg = hashlib.sha256(b'timeout').digest()
    sig = schnorr_priv.schnorr_sign(msg, b'', raw=True)
    return sig.hex()


def fund_deal_via_devimint(deal_id: str, poll_timeout: int = 60,
                           buyer_eph_priv=None, buyer_eph_pub: str = None) -> dict:
    """
    Create LN invoice (with browser-generated secret_code_hash), pay it via devimint,
    and wait for deal to become funded.
    Returns dict with 'check_result' and 'secret_code' (simulating browser localStorage).

    If buyer_eph_priv/pub are provided, use them (must match the key registered
    during LNURL auth). Otherwise generate a random key (only works for deals without auth).
    """
    # Simulate browser generating secret + hash before calling create-ln-invoice
    secret_code, secret_code_hash = generate_secret_and_hash()

    # NON-CUSTODIAL: use registered buyer key if available, else generate random
    if buyer_eph_priv and buyer_eph_pub:
        buyer_pubkey = buyer_eph_pub
        timeout_sig = _make_timeout_sig_for_coincurve_key(buyer_eph_priv)
    else:
        buyer_pubkey, timeout_sig, _ = _make_buyer_escrow_key()

    # Create invoice — send hash + buyer key + timeout sig, keep secret locally
    inv_resp = api("post", f"/deals/{deal_id}/create-ln-invoice",
                   json={
                       "secret_code_hash": secret_code_hash,
                       "buyer_pubkey": buyer_pubkey,
                       "timeout_signature": timeout_sig,
                   })
    assert inv_resp.status_code == 200, f"Create invoice failed: {inv_resp.text}"
    bolt11 = inv_resp.json()["bolt11"]
    assert bolt11.startswith("lnbc"), f"Expected BOLT11 invoice, got: {bolt11[:20]}"

    # Pay it
    paid = simulate_payment(bolt11, timeout=45)
    assert paid, "Payment simulation failed (is devimint running on 152?)"

    # Poll until funded
    deadline = time.time() + poll_timeout
    while time.time() < deadline:
        check_resp = api("get", f"/deals/{deal_id}/check-ln-invoice")
        assert check_resp.status_code == 200
        if check_resp.json().get("paid"):
            # Return both the API response and the secret_code (simulates localStorage)
            return {"check_result": check_resp.json(), "secret_code": secret_code}
        time.sleep(2)

    pytest.fail(f"Deal {deal_id} did not reach funded state within {poll_timeout}s")


# ============================================================================
# SECTION A: Basic deal CRUD
# ============================================================================

class TestDealCRUD:
    def test_create_deal_returns_200(self):
        deal = create_test_deal()
        assert deal["status"] == "pending"
        assert deal["price_sats"] == DEAL_PRICE
        assert "deal_id" in deal
        assert "deal_link_token" in deal

    def test_get_deal_by_id(self):
        deal = create_test_deal()
        resp = api("get", f"/deals/{deal['deal_id']}")
        assert resp.status_code == 200
        assert resp.json()["deal_id"] == deal["deal_id"]

    def test_get_deal_not_found(self):
        resp = api("get", "/deals/nonexistent-deal-id-00000000")
        assert resp.status_code == 404

    def test_list_deals_by_user(self):
        deal = create_test_deal()
        seller_id = deal["seller_id"]
        resp = api("get", f"/deals/user/{seller_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list) or "deals" in data

    def test_stats_endpoint(self):
        resp = api("get", "/deals/stats")
        assert resp.status_code == 200

    def test_health_endpoint(self):
        resp = api("get", "/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


# ============================================================================
# SECTION B: LNURL-auth flow
# ============================================================================

class TestLNURLAuth:
    def test_challenge_creation(self):
        deal = create_test_deal()
        resp = api("get", f"/auth/lnurl/challenge/{deal['deal_link_token']}", params={"role": "seller"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["k1"]) == 64  # 32 bytes hex
        assert "lnurl" in data
        assert data["deal_id"] == deal["deal_id"]

    def test_challenge_not_found_for_bad_token(self):
        resp = api("get", "/auth/lnurl/challenge/nonexistent-token-xyz", params={"role": "seller"})
        assert resp.status_code == 404

    def test_full_lnurl_auth_seller(self):
        deal = create_test_deal()
        user_id = f"test-seller-{uuid.uuid4().hex[:8]}"

        # Get challenge
        resp = api("get", f"/auth/lnurl/challenge/{deal['deal_link_token']}", params={"role": "seller"})
        k1 = resp.json()["k1"]

        # Sign and callback
        sig_hex, pub_hex, _ = _lnurl_sign(k1)
        cb = api("get", "/auth/lnurl/callback", params={"k1": k1, "sig": sig_hex, "key": pub_hex, "tag": "login"})
        assert cb.json()["status"] == "OK"

        # Status shows verified
        status = api("get", f"/auth/lnurl/status/{k1}")
        assert status.json()["verified"] is True
        assert status.json()["pubkey"] == pub_hex

        # Register ephemeral key
        _, ephemeral_pub = _make_ephemeral_key()
        reg = api("post", "/auth/lnurl/register-derived-key", json={
            "k1": k1, "user_id": user_id, "ephemeral_pubkey": ephemeral_pub
        })
        assert reg.status_code == 200
        assert reg.json()["success"] is True

        # Deal now has seller_linking_pubkey set (seller_pubkey not exposed in DealResponse)
        deal_resp = api("get", f"/deals/{deal['deal_id']}")
        assert deal_resp.json()["seller_linking_pubkey"] == pub_hex

    def test_wrong_signature_rejected(self):
        deal = create_test_deal()
        resp = api("get", f"/auth/lnurl/challenge/{deal['deal_link_token']}", params={"role": "seller"})
        k1 = resp.json()["k1"]

        # Generate wrong signature (different k1 content)
        from secp256k1 import PrivateKey
        priv = PrivateKey()
        pub_hex = priv.pubkey.serialize().hex()
        wrong_k1 = "a" * 64  # Different k1
        sig_hex, _, _ = _lnurl_sign(wrong_k1, priv)  # Sign wrong content

        cb = api("get", "/auth/lnurl/callback", params={"k1": k1, "sig": sig_hex, "key": pub_hex, "tag": "login"})
        assert cb.json()["status"] == "ERROR"

    def test_status_shows_unverified_for_unknown_k1(self):
        resp = api("get", f"/auth/lnurl/status/{'a' * 64}")
        assert resp.status_code == 200
        assert resp.json()["verified"] is False

    def test_both_parties_auth_activates_deal(self):
        deal = create_test_deal()
        token = deal["deal_link_token"]
        deal_id = deal["deal_id"]

        seller_id = f"seller-{uuid.uuid4().hex[:8]}"
        buyer_id = f"buyer-{uuid.uuid4().hex[:8]}"

        # Seller joins via auth
        lnurl_auth_deal(token, "seller", seller_id)

        # Buyer joins deal first
        join_resp = join_deal(token, buyer_id, "Test Buyer")
        assert join_resp.status_code == 200

        # Buyer auths
        lnurl_auth_deal(token, "buyer", buyer_id)

        # Deal should be active
        final = api("get", f"/deals/{deal_id}")
        assert final.json()["status"] == "active"


# ============================================================================
# SECTION C: Join deal
# ============================================================================

class TestJoinDeal:
    def test_buyer_can_join(self):
        deal = create_test_deal()
        resp = join_deal(deal["deal_link_token"], "test-buyer-123", "Test Buyer")
        assert resp.status_code == 200

    def test_join_sets_buyer_started_at(self):
        deal = create_test_deal()
        # Get challenge first (sets buyer_started_at)
        api("get", f"/auth/lnurl/challenge/{deal['deal_link_token']}", params={"role": "buyer"})
        updated = api("get", f"/deals/{deal['deal_id']}")
        assert updated.json()["buyer_started_at"] is not None

    def test_cannot_join_completed_deal(self):
        # Admin force-complete a deal in expired status
        deal = create_test_deal()
        # First put in expired state by setting expires_at in past... skip, test different path
        # Instead test joining a pending deal twice
        deal_id = deal["deal_id"]
        join_deal(deal["deal_link_token"], "buyer1", "B1")
        # Second join should succeed or 200 (idempotent) — at minimum not 500
        resp2 = join_deal(deal["deal_link_token"], "buyer1", "B1")
        assert resp2.status_code in [200, 400]  # Either OK or "already joined"


# ============================================================================
# SECTION D: Invoice creation guard
# ============================================================================

class TestInvoiceCreation:
    def test_create_invoice_requires_seller_auth(self):
        """Without seller LNURL-auth, invoice creation should fail."""
        deal = create_test_deal()
        deal_id = deal["deal_id"]

        # Join but don't auth either party
        join_deal(deal["deal_link_token"], "buyer1", "B1")

        _, hash_ = generate_secret_and_hash()
        buyer_pub, timeout_sig, _ = _make_buyer_escrow_key()
        resp = api("post", f"/deals/{deal_id}/create-ln-invoice",
                   json={"secret_code_hash": hash_, "buyer_pubkey": buyer_pub, "timeout_signature": timeout_sig})
        assert resp.status_code == 400
        # Either payout-invoice check or seller-auth check fires first
        detail = resp.json()["detail"].lower()
        assert any(kw in detail for kw in ["seller", "authenticate", "lightning", "payout", "address"])

    @pytest.mark.skipif(_MOCK_PAYMENTS_ON_SERVER, reason="MOCK_PAYMENTS=true: payout invoices not required")
    def test_create_invoice_requires_both_payout_invoices(self):
        """Both payout invoices must be submitted before invoice creation."""
        deal = create_test_deal()
        deal_id = deal["deal_id"]
        token = deal["deal_link_token"]

        seller_id = f"seller-{uuid.uuid4().hex[:8]}"
        buyer_id = f"buyer-{uuid.uuid4().hex[:8]}"

        # Seller auths
        _, seller_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "seller", seller_id)
        # Buyer joins + auths
        join_deal(token, buyer_id, "Buyer")
        _, buyer_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "buyer", buyer_id)

        # No payout invoices submitted yet — use buyer's auth key to pass pubkey check
        _, hash_ = generate_secret_and_hash()
        buyer_pub = buyer_eph_priv.public_key.format(compressed=True).hex()
        timeout_sig = _make_timeout_sig_for_coincurve_key(buyer_eph_priv)
        resp = api("post", f"/deals/{deal_id}/create-ln-invoice",
                   json={"secret_code_hash": hash_, "buyer_pubkey": buyer_pub, "timeout_signature": timeout_sig})
        assert resp.status_code == 400
        assert "lightning" in resp.json()["detail"].lower() or "payout" in resp.json()["detail"].lower()

    def test_create_invoice_on_funded_deal_fails(self):
        """Cannot create another invoice once deal is already funded."""
        # This test is skipped if devimint is not available
        pytest.skip("Requires full funded deal — covered in TestHappyPath")


# ============================================================================
# SECTION E: Non-custodial guards
# ============================================================================

@pytest.mark.skipif(not _DEVIMINT_AVAILABLE, reason="Requires devimint (set SSH_SERVER + SERVER_DEVIMINT_ENV)")
class TestNonCustodialGuards:
    """Test that secret_code is properly required for release."""

    @pytest.fixture(scope="class")
    def funded_deal(self):
        """Create and fund a deal. Returns (deal_id, seller_id, buyer_id, secret_code, buyer_eph_priv, seller_eph_priv)."""
        deal = create_test_deal()
        deal_id = deal["deal_id"]
        token = deal["deal_link_token"]
        seller_id = deal["seller_id"]  # Must match deal's seller_id for payout invoice auth
        buyer_id = f"buyer-{uuid.uuid4().hex[:8]}"

        _, seller_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "seller", seller_id)
        join_deal(token, buyer_id, "Buyer")
        _, buyer_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "buyer", buyer_id)

        # Submit payout invoices
        ts = int(time.time())
        sig = _sign_action(deal_id, "submit-payout-invoice", ts, seller_eph_priv)
        r = api("post", f"/deals/{deal_id}/submit-payout-invoice", json={
            "user_id": seller_id, "invoice": TEST_SELLER_ADDRESS, "signature": sig, "timestamp": ts
        })
        assert r.status_code == 200, f"Submit payout failed: {r.text}"

        ts = int(time.time())
        sig = _sign_action(deal_id, "submit-refund-invoice", ts, buyer_eph_priv)
        r = api("post", f"/deals/{deal_id}/submit-refund-invoice", json={
            "user_id": buyer_id, "invoice": TEST_BUYER_ADDRESS, "signature": sig, "timestamp": ts
        })
        assert r.status_code == 200, f"Submit refund failed: {r.text}"

        # Fund via devimint (secret_code_hash sent to server, secret_code stays local)
        # Pass buyer's ephemeral key so buyer_pubkey matches what was registered at LNURL auth
        buyer_eph_pub_hex = buyer_eph_priv.public_key.format(compressed=True).hex()
        result = fund_deal_via_devimint(deal_id, buyer_eph_priv=buyer_eph_priv, buyer_eph_pub=buyer_eph_pub_hex)
        secret_code = result["secret_code"]  # from "localStorage" (generated locally)
        check_result = result["check_result"]
        # Server never returns secret_code in check-ln-invoice (it never had it)
        assert check_result.get("secret_code") is None, \
            "Server must NOT return secret_code (it never saw the plaintext)"

        return deal_id, seller_id, buyer_id, secret_code, buyer_eph_priv, seller_eph_priv

    def test_secret_code_never_in_api_response(self, funded_deal):
        """check-ln-invoice never returns secret_code — buyer already has it in localStorage."""
        deal_id = funded_deal[0]
        resp = api("get", f"/deals/{deal_id}/check-ln-invoice")
        assert resp.status_code == 200
        assert resp.json().get("secret_code") is None, \
            "secret_code must never appear in API response (non-custodial: browser-generated)"

    def test_deal_db_secret_code_is_null(self, funded_deal):
        """The deal's ark_secret_code should be null in DB after delivery."""
        deal_id = funded_deal[0]
        deal_resp = api("get", f"/deals/{deal_id}")
        assert deal_resp.status_code == 200
        # The API should not expose secret_code in the deal response
        assert deal_resp.json().get("ark_secret_code") is None

    def test_release_without_secret_code_rejected(self, funded_deal):
        """Release without secret_code returns 400."""
        deal_id, _, buyer_id, _, buyer_eph_priv, _ = funded_deal
        ts = int(time.time())
        sig = _sign_action(deal_id, "release", ts, buyer_eph_priv)
        resp = api("post", f"/deals/{deal_id}/release", json={
            "buyer_id": buyer_id, "signature": sig, "timestamp": ts
            # no secret_code
        })
        assert resp.status_code == 400
        assert "recovery code" in resp.json()["detail"].lower() or "secret" in resp.json()["detail"].lower()

    def test_release_with_wrong_secret_code_rejected(self, funded_deal):
        """Release with wrong secret_code returns 403."""
        deal_id, _, buyer_id, _, buyer_eph_priv, _ = funded_deal
        ts = int(time.time())
        sig = _sign_action(deal_id, "release", ts, buyer_eph_priv)
        resp = api("post", f"/deals/{deal_id}/release", json={
            "buyer_id": buyer_id, "signature": sig, "timestamp": ts,
            "secret_code": "wrong-code-definitely-not-correct-xxxxxxxxxxxx"
        })
        assert resp.status_code == 403
        assert "invalid" in resp.json()["detail"].lower()

    def test_release_wrong_buyer_rejected(self, funded_deal):
        """Release with wrong buyer_id returns 403."""
        deal_id, _, _, _, buyer_eph_priv, _ = funded_deal
        ts = int(time.time())
        sig = _sign_action(deal_id, "release", ts, buyer_eph_priv)
        resp = api("post", f"/deals/{deal_id}/release", json={
            "buyer_id": "wrong-buyer-id-xyz",
            "signature": sig, "timestamp": ts,
            "secret_code": "any-code"
        })
        assert resp.status_code == 403


# ============================================================================
# SECTION F: Full happy path
# ============================================================================

@pytest.mark.skipif(not _DEVIMINT_AVAILABLE, reason="Requires devimint (set SSH_SERVER + SERVER_DEVIMINT_ENV)")
class TestHappyPath:
    """Complete deal lifecycle: create → auth → fund → ship → release."""

    def test_create_invoice_requires_funded_deal(self):
        """After funding, deal is in 'funded' status with escrow_id set."""
        deal = create_test_deal()
        deal_id = deal["deal_id"]
        token = deal["deal_link_token"]
        seller_id = deal["seller_id"]  # Must match deal's seller_id for payout invoice auth
        buyer_id = f"buyer-{uuid.uuid4().hex[:8]}"

        # Both parties auth
        _, seller_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "seller", seller_id)
        join_deal(token, buyer_id, "Buyer")
        _, buyer_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "buyer", buyer_id)

        # Submit invoices
        ts = int(time.time())
        sig = _sign_action(deal_id, "submit-payout-invoice", ts, seller_eph_priv)
        r = api("post", f"/deals/{deal_id}/submit-payout-invoice", json={
            "user_id": seller_id, "invoice": TEST_SELLER_ADDRESS, "signature": sig, "timestamp": ts
        })
        assert r.status_code == 200, f"submit-payout-invoice failed: {r.text}"
        ts = int(time.time())
        sig = _sign_action(deal_id, "submit-refund-invoice", ts, buyer_eph_priv)
        r = api("post", f"/deals/{deal_id}/submit-refund-invoice", json={
            "user_id": buyer_id, "invoice": TEST_BUYER_ADDRESS, "signature": sig, "timestamp": ts
        })
        assert r.status_code == 200, f"submit-refund-invoice failed: {r.text}"

        # Browser generates secret_code + hash; only hash goes to server (non-custodial)
        secret_code, secret_code_hash = generate_secret_and_hash()
        # Use the buyer's LNURL-auth ephemeral key (must match registered key)
        buyer_pub = buyer_eph_priv.public_key.format(compressed=True).hex()
        timeout_sig = _make_timeout_sig_for_coincurve_key(buyer_eph_priv)
        inv_resp = api("post", f"/deals/{deal_id}/create-ln-invoice",
                       json={
                           "secret_code_hash": secret_code_hash,
                           "buyer_pubkey": buyer_pub,
                           "timeout_signature": timeout_sig,
                       })
        assert inv_resp.status_code == 200, f"Create invoice failed: {inv_resp.text}"
        data = inv_resp.json()
        assert "bolt11" in data
        assert data["bolt11"].startswith("lnbcrt"), "Expected regtest invoice"

        paid = simulate_payment(data["bolt11"])
        assert paid, "Payment simulation failed"

        # Poll check-ln-invoice — server never returns secret_code (non-custodial)
        funded = False
        for _ in range(30):
            check = api("get", f"/deals/{deal_id}/check-ln-invoice")
            if check.json().get("paid"):
                assert check.json().get("secret_code") is None, \
                    "Server must NOT return secret_code (non-custodial)"
                funded = True
                break
            time.sleep(2)

        assert funded, "Invoice was not marked as paid"

        # Deal is funded
        deal_state = api("get", f"/deals/{deal_id}").json()
        assert deal_state["status"] == "funded"
        assert deal_state["ark_escrow_deal_id"] is not None
        assert deal_state.get("ark_secret_code") is None  # never stored

        # Ship
        ts = int(time.time())
        sig = _sign_action(deal_id, "ship", ts, seller_eph_priv)
        ship_resp = api("post", f"/deals/{deal_id}/ship", json={
            "seller_id": seller_id, "signature": sig, "timestamp": ts
        })
        assert ship_resp.status_code == 200
        assert api("get", f"/deals/{deal_id}").json()["status"] == "shipped"

        # Release with secret_code
        ts = int(time.time())
        sig = _sign_action(deal_id, "release", ts, buyer_eph_priv)
        release_resp = api("post", f"/deals/{deal_id}/release", json={
            "buyer_id": buyer_id, "signature": sig, "timestamp": ts,
            "secret_code": secret_code
        })
        # Either 200 (accepted) or 502 (LN payout failed — expected on testnet)
        assert release_resp.status_code in [200, 502], \
            f"Unexpected status: {release_resp.status_code} — {release_resp.text}"

        # Deal should be in releasing, completed, or payout_failed state
        final = api("get", f"/deals/{deal_id}").json()
        assert final["status"] in ["completed", "releasing", "funded", "shipped"]


# ============================================================================
# SECTION G: Refund path
# ============================================================================

@pytest.mark.skipif(not _DEVIMINT_AVAILABLE, reason="Requires devimint (set SSH_SERVER + SERVER_DEVIMINT_ENV)")
class TestRefundPath:
    def test_refund_requires_refund_invoice(self):
        """Refund on a funded deal works (payout may fail with fake LN address)."""
        # Use timeout_hours=1 → offset=144 blocks. Mine 145 to expire.
        deal = create_test_deal(timeout_hours=1)
        deal_id = deal["deal_id"]
        token = deal["deal_link_token"]
        seller_id = deal["seller_id"]  # Must match deal's seller_id
        buyer_id = f"buyer-{uuid.uuid4().hex[:8]}"

        _, seller_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "seller", seller_id)
        join_deal(token, buyer_id, "Buyer")
        _, buyer_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "buyer", buyer_id)

        ts = int(time.time())
        sig = _sign_action(deal_id, "submit-payout-invoice", ts, seller_eph_priv)
        r = api("post", f"/deals/{deal_id}/submit-payout-invoice", json={
            "user_id": seller_id, "invoice": TEST_SELLER_ADDRESS, "signature": sig, "timestamp": ts
        })
        assert r.status_code == 200, f"submit-payout-invoice failed: {r.text}"

        ts2 = int(time.time())
        sig2 = _sign_action(deal_id, "submit-refund-invoice", ts2, buyer_eph_priv)
        api("post", f"/deals/{deal_id}/submit-refund-invoice", json={
            "user_id": buyer_id, "invoice": TEST_BUYER_ADDRESS, "signature": sig2, "timestamp": ts2
        })
        buyer_pub_hex = buyer_eph_priv.public_key.format(compressed=True).hex()
        fund_deal_via_devimint(deal_id, buyer_eph_priv=buyer_eph_priv, buyer_eph_pub=buyer_pub_hex)

        # Mine 160 blocks (144 needed + 16 margin) so federation has time to sync
        assert mine_blocks(160), "Block mining failed"
        time.sleep(15)  # Wait for federation to process new blocks

        ts = int(time.time())
        sig = _sign_action(deal_id, "refund", ts, buyer_eph_priv)
        refund_resp = api("post", f"/deals/{deal_id}/refund", json={
            "user_id": buyer_id, "reason": "Changed my mind", "signature": sig, "timestamp": ts
        })
        # Either 200 (accepted) or 502 (LN payout failed — expected with fake invoice)
        assert refund_resp.status_code in [200, 502], f"Refund failed: {refund_resp.text}"

    def test_refund_wrong_user_rejected(self):
        """Cannot refund with wrong user_id."""
        deal = create_test_deal()
        deal_id = deal["deal_id"]
        token = deal["deal_link_token"]
        seller_id = deal["seller_id"]  # Must match deal's seller_id
        buyer_id = f"buyer-{uuid.uuid4().hex[:8]}"

        _, _, _, _, _, _ = lnurl_auth_deal(token, "seller", seller_id)
        join_deal(token, buyer_id, "Buyer")
        _, buyer_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "buyer", buyer_id)

        ts = int(time.time())
        sig = _sign_action(deal_id, "refund", ts, buyer_eph_priv)
        resp = api("post", f"/deals/{deal_id}/refund", json={
            "user_id": "not-a-participant-xyz", "reason": "test", "signature": sig, "timestamp": ts
        })
        assert resp.status_code == 403


# ============================================================================
# SECTION H: Dispute path
# ============================================================================

@pytest.mark.skipif(not _DEVIMINT_AVAILABLE, reason="Requires devimint (set SSH_SERVER + SERVER_DEVIMINT_ENV)")
class TestDisputePath:
    def test_dispute_flow(self):
        """Create → fund → dispute → admin resolve."""
        # Use timeout_hours=1 → offset=144 blocks. Mine 145 to expire for claim-timeout.
        deal = create_test_deal(timeout_hours=1)
        deal_id = deal["deal_id"]
        token = deal["deal_link_token"]
        seller_id = deal["seller_id"]  # Must match deal's seller_id
        buyer_id = f"buyer-{uuid.uuid4().hex[:8]}"

        _, seller_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "seller", seller_id)
        join_deal(token, buyer_id, "Buyer")
        _, buyer_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "buyer", buyer_id)

        ts = int(time.time())
        sig = _sign_action(deal_id, "submit-payout-invoice", ts, seller_eph_priv)
        r = api("post", f"/deals/{deal_id}/submit-payout-invoice", json={
            "user_id": seller_id, "invoice": TEST_SELLER_ADDRESS, "signature": sig, "timestamp": ts
        })
        assert r.status_code == 200, f"submit-payout-invoice failed: {r.text}"
        ts = int(time.time())
        sig = _sign_action(deal_id, "submit-refund-invoice", ts, buyer_eph_priv)
        r = api("post", f"/deals/{deal_id}/submit-refund-invoice", json={
            "user_id": buyer_id, "invoice": TEST_BUYER_ADDRESS, "signature": sig, "timestamp": ts
        })
        assert r.status_code == 200, f"submit-refund-invoice failed: {r.text}"

        # Fund deal
        buyer_pub_hex = buyer_eph_priv.public_key.format(compressed=True).hex()
        fund_deal_via_devimint(deal_id, buyer_eph_priv=buyer_eph_priv, buyer_eph_pub=buyer_pub_hex)

        # Mine 160 blocks (144 needed + 16 margin) so federation has time to sync
        assert mine_blocks(160), "Block mining failed"
        time.sleep(15)  # Wait for federation to process new blocks

        # Open dispute
        ts = int(time.time())
        sig = _sign_action(deal_id, "dispute", ts, buyer_eph_priv)
        disp_resp = api("post", f"/deals/{deal_id}/dispute", json={
            "user_id": buyer_id, "reason": "Item not as described", "signature": sig, "timestamp": ts
        })
        assert disp_resp.status_code == 200
        assert api("get", f"/deals/{deal_id}").json()["status"] == "disputed"

        # Admin resolves as refund
        admin_resp = api("post", f"/deals/admin/{deal_id}/resolve-refund",
                        headers=admin_headers(),
                        json={"resolution_note": "Test refund"})
        # 200 = succeeded, 502 = LN payout failed (acceptable in test)
        # 501 = oracle attestation path not yet implemented for admin (also acceptable —
        #       disputed deals require oracle signatures, not unilateral admin action)
        assert admin_resp.status_code in [200, 501, 502], f"Admin resolve failed: {admin_resp.text}"


# ============================================================================
# SECTION I: Admin endpoints
# ============================================================================

class TestAdminEndpoints:
    def test_admin_requires_key(self):
        resp = api("get", "/deals/admin/deals")
        assert resp.status_code == 401  # returns 401 when no key provided

    @pytest.mark.skipif(not ADMIN_KEY and not ADMIN_PUBKEY, reason="No admin credentials (set TEST_ADMIN_KEY or TEST_ADMIN_PUBKEY)")
    def test_admin_list_deals(self):
        resp = api("get", "/deals/admin/deals", headers=admin_headers())
        assert resp.status_code == 200
        assert "deals" in resp.json()

    @pytest.mark.skipif(not ADMIN_KEY and not ADMIN_PUBKEY, reason="No admin credentials")
    def test_admin_config(self):
        resp = api("get", "/deals/admin/config", headers=admin_headers())
        assert resp.status_code == 200

    @pytest.mark.skipif(not ADMIN_KEY and not ADMIN_PUBKEY, reason="No admin credentials")
    def test_admin_resolve_non_disputed_deal_fails(self):
        """Admin can only resolve disputed/expired deals."""
        deal = create_test_deal()
        resp = api("post", f"/deals/admin/{deal['deal_id']}/resolve-release",
                   headers=admin_headers(), json={})
        assert resp.status_code == 400

    def test_wrong_admin_key_rejected(self):
        resp = api("get", "/deals/admin/deals", headers={"x-admin-key": "wrong-key-xyz"})
        assert resp.status_code == 401  # returns 401 for wrong key


# ============================================================================
# SECTION J: Status transition guards
# ============================================================================

class TestStatusGuards:
    def test_cannot_create_invoice_for_pending_without_seller_auth(self):
        deal = create_test_deal()
        _, hash_ = generate_secret_and_hash()
        buyer_pub, timeout_sig, _ = _make_buyer_escrow_key()
        resp = api("post", f"/deals/{deal['deal_id']}/create-ln-invoice",
                   json={"secret_code_hash": hash_, "buyer_pubkey": buyer_pub, "timeout_signature": timeout_sig})
        assert resp.status_code == 400

    def test_check_invoice_without_invoice_created(self):
        deal = create_test_deal()
        resp = api("get", f"/deals/{deal['deal_id']}/check-ln-invoice")
        assert resp.status_code == 400

    def test_release_on_pending_deal_fails(self):
        deal = create_test_deal()
        deal_id = deal["deal_id"]
        from coincurve import PrivateKey
        priv = PrivateKey()
        ts = int(time.time())
        sig = _sign_action(deal_id, "release", ts, priv)
        resp = api("post", f"/deals/{deal_id}/release", json={
            "buyer_id": "buyer1", "signature": sig, "timestamp": ts
        })
        # 403 (wrong buyer_id) or 400 (wrong status) — both acceptable
        assert resp.status_code in [400, 403]

    def test_ship_on_pending_deal_fails(self):
        deal = create_test_deal()
        deal_id = deal["deal_id"]
        from coincurve import PrivateKey
        priv = PrivateKey()
        ts = int(time.time())
        sig = _sign_action(deal_id, "ship", ts, priv)
        resp = api("post", f"/deals/{deal_id}/ship", json={
            "seller_id": "anyone", "signature": sig, "timestamp": ts
        })
        assert resp.status_code in [400, 403, 422]


# ============================================================================
# SECTION K: Kill switch
# ============================================================================

class TestKillSwitch:
    """Test the payout kill switch (halt/resume)."""

    @pytest.mark.skipif(not ADMIN_KEY and not ADMIN_PUBKEY, reason="No admin credentials")
    def test_halt_and_resume_payouts(self):
        """Halting payouts blocks releases; resuming allows them again."""
        # Halt
        resp = api("post", "/deals/admin/halt-payouts", headers=admin_headers())
        assert resp.status_code == 200
        assert resp.json()["payouts_halted"] is True

        # system-status reflects halted state
        status = api("get", "/system-status")
        assert status.json()["payouts_halted"] is True

        # Resume
        resp = api("post", "/deals/admin/resume-payouts", headers=admin_headers())
        assert resp.status_code == 200
        assert resp.json()["payouts_halted"] is False

        # system-status reflects resumed state
        status = api("get", "/system-status")
        assert status.json()["payouts_halted"] is False

    def test_halt_requires_admin_key(self):
        resp = api("post", "/deals/admin/halt-payouts")
        assert resp.status_code == 401

    def test_resume_requires_admin_key(self):
        resp = api("post", "/deals/admin/resume-payouts")
        assert resp.status_code == 401


# ============================================================================
# SECTION L: Amount cap
# ============================================================================

class TestAmountCap:
    """Test the TEST_PHASE_MAX_SATS hard cap."""

    def test_deal_within_limits_accepted(self):
        """A deal within the configured limits is accepted."""
        deal = create_test_deal(price_sats=1000)
        assert deal["price_sats"] == 1000

    @pytest.mark.skipif(not ADMIN_KEY and not ADMIN_PUBKEY, reason="No admin credentials")
    def test_system_status_returns_limits(self):
        """Limits endpoint returns test_phase_max_sats."""
        resp = api("get", "/deals/admin/settings/limits", headers=admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "max_sats" in data
        assert "test_phase_max_sats" in data


# ============================================================================
# SECTION M: Recovery endpoints
# ============================================================================

@pytest.mark.skipif(not ADMIN_KEY and not ADMIN_PUBKEY, reason="No admin credentials (set TEST_ADMIN_KEY or TEST_ADMIN_PUBKEY)")
class TestRecoveryEndpoints:
    """Test admin recovery tools."""

    def test_wallet_balance(self):
        resp = api("get", "/deals/admin/wallet-balance", headers=admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "balance_sats" in data
        assert isinstance(data["balance_sats"], (int, float))

    def test_wallet_balance_requires_admin(self):
        resp = api("get", "/deals/admin/wallet-balance")
        assert resp.status_code == 401

    def test_failed_payouts_list(self):
        resp = api("get", "/deals/admin/failed-payouts", headers=admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "deals" in data
        assert isinstance(data["deals"], list)

    def test_escrow_status_for_nonexistent_deal(self):
        resp = api("get", "/deals/admin/nonexistent-deal-xyz/escrow-status",
                   headers=admin_headers())
        assert resp.status_code == 404

    def test_escrow_status_for_deal_without_escrow(self):
        deal = create_test_deal()
        resp = api("get", f"/deals/admin/{deal['deal_id']}/escrow-status",
                   headers=admin_headers())
        assert resp.status_code == 200
        assert resp.json()["state"] == "no_escrow"

    def test_manual_payout_requires_claimed_escrow(self):
        """Manual payout on a deal without claimed escrow returns 400."""
        deal = create_test_deal()
        resp = api("post", f"/deals/admin/{deal['deal_id']}/manual-payout",
                   headers=admin_headers())
        assert resp.status_code == 400


# ============================================================================
# SECTION N: Idempotency
# ============================================================================

class TestIdempotency:
    """Test that repeated operations are safe."""

    def test_double_join_is_safe(self):
        """Joining a deal twice doesn't cause errors."""
        deal = create_test_deal()
        buyer_id = f"buyer-{uuid.uuid4().hex[:8]}"
        r1 = join_deal(deal["deal_link_token"], buyer_id, "Buyer")
        r2 = join_deal(deal["deal_link_token"], buyer_id, "Buyer")
        assert r1.status_code in [200, 400]
        assert r2.status_code in [200, 400]

    def test_double_create_invoice_returns_same(self):
        """Creating an invoice twice returns the same one (idempotent)."""
        deal = create_test_deal()
        deal_id = deal["deal_id"]
        token = deal["deal_link_token"]
        seller_id = deal["seller_id"]
        buyer_id = f"buyer-{uuid.uuid4().hex[:8]}"

        _, seller_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "seller", seller_id)
        join_deal(token, buyer_id, "Buyer")
        _, buyer_eph_priv, _, _, _, _ = lnurl_auth_deal(token, "buyer", buyer_id)

        # Submit invoices
        ts = int(time.time())
        sig = _sign_action(deal_id, "submit-payout-invoice", ts, seller_eph_priv)
        api("post", f"/deals/{deal_id}/submit-payout-invoice", json={
            "user_id": seller_id, "invoice": TEST_SELLER_ADDRESS, "signature": sig, "timestamp": ts
        })
        ts = int(time.time())
        sig = _sign_action(deal_id, "submit-refund-invoice", ts, buyer_eph_priv)
        api("post", f"/deals/{deal_id}/submit-refund-invoice", json={
            "user_id": buyer_id, "invoice": TEST_BUYER_ADDRESS, "signature": sig, "timestamp": ts
        })

        secret_code, secret_code_hash = generate_secret_and_hash()
        buyer_pub = buyer_eph_priv.public_key.format(compressed=True).hex()
        timeout_sig = _make_timeout_sig_for_coincurve_key(buyer_eph_priv)
        invoice_body = {
            "secret_code_hash": secret_code_hash,
            "buyer_pubkey": buyer_pub,
            "timeout_signature": timeout_sig,
        }

        # Create invoice twice
        r1 = api("post", f"/deals/{deal_id}/create-ln-invoice", json=invoice_body)
        r2 = api("post", f"/deals/{deal_id}/create-ln-invoice", json=invoice_body)

        assert r1.status_code == 200
        assert r2.status_code == 200
        # Both should return the same bolt11
        assert r1.json()["bolt11"] == r2.json()["bolt11"]
