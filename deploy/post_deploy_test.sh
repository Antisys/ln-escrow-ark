#!/bin/bash
# Post-deploy verification — runs ON the Pi after service restart.
# Tests the live API at localhost:8001. No funds are moved.
# Exit code 0 = all good, non-zero = deploy is broken.

set -e

BASE="http://localhost:8001"
ADMIN_KEY="${ADMIN_API_KEY:-$(grep ADMIN_API_KEY /home/ralf/ln-escrow/.env 2>/dev/null | cut -d= -f2)}"
PASS=0
FAIL=0
ERRORS=""

check() {
    local desc="$1"
    local expect_status="$2"
    shift 2
    # Remaining args are the full curl command
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" "$@" 2>/dev/null) || status="000"

    if [ "$status" = "$expect_status" ]; then
        PASS=$((PASS + 1))
        echo "  ✓ $desc (HTTP $status)"
    else
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}\n  ✗ $desc — expected $expect_status, got $status"
        echo "  ✗ $desc — expected $expect_status, got $status"
    fi
}

check_json_field() {
    local desc="$1"
    local field="$2"
    shift 2
    local body
    body=$(curl -s "$@" 2>/dev/null) || body=""

    if echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); assert '$field' in d" 2>/dev/null; then
        PASS=$((PASS + 1))
        echo "  ✓ $desc (field '$field' present)"
    else
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}\n  ✗ $desc — field '$field' missing from response"
        echo "  ✗ $desc — field '$field' missing"
    fi
}

echo ""
echo "=== Post-Deploy Verification ==="
echo ""

# --- Health & System ---
echo "[Health]"
check "Health endpoint" 200 -X GET "${BASE}/health"
check "Ready endpoint" 200 -X GET "${BASE}/ready"
check_json_field "System status" "operational" -X GET "${BASE}/system-status"

# --- Deal CRUD (read-only) ---
echo "[Deals]"
check "Stats endpoint" 200 -X GET "${BASE}/deals/stats"
check "Get non-existent deal" 404 -X GET "${BASE}/deals/nonexistent-deal-id-12345"
check "Get non-existent token" 404 -X GET "${BASE}/deals/token/nonexistent-token-12345"

# --- Auth ---
echo "[Auth]"
check "LNURL info" 200 -X GET "${BASE}/auth/lnurl/info"

# --- Admin (read-only) ---
echo "[Admin]"
check "Admin config (no key)" 401 -X GET "${BASE}/deals/admin/config"
check "Admin config (with key)" 200 -X GET -H "X-Admin-Key: ${ADMIN_KEY}" "${BASE}/deals/admin/config"
check "Admin deals list" 200 -X GET -H "X-Admin-Key: ${ADMIN_KEY}" "${BASE}/deals/admin/deals"
check "Settings limits" 200 -X GET "${BASE}/deals/settings/limits"

# --- Signing (requires valid deal) ---
echo "[Signing]"
check "Signing status (no deal)" 404 -X GET "${BASE}/deals/nonexistent/signing-status"

# --- Funding ---
echo "[Funding]"
check "Create invoice (no deal)" 404 \
    -X POST -H "Content-Type: application/json" \
    -d '{"amount_sats":50000,"secret_code_hash":"abc123"}' \
    "${BASE}/deals/nonexistent/create-ln-invoice"

# --- Payout (should reject without valid deal) ---
echo "[Payout]"
# POST endpoints validate request body (422) before checking deal existence (404)
# So we test with valid-shaped bodies to confirm they reach deal lookup
check "Submit invoice (no deal)" 404 \
    -X POST -H "Content-Type: application/json" \
    -d '{"user_id":"test","invoice":"lnbc1test","signature":"aabbccdd","timestamp":1700000000}' \
    "${BASE}/deals/nonexistent/submit-payout-invoice"

# --- Release (should reject without valid deal) ---
echo "[Release]"
check "Release (no deal)" 404 \
    -X POST -H "Content-Type: application/json" \
    -d '{"buyer_id":"test","signature":"aabbccdd","timestamp":1700000000}' \
    "${BASE}/deals/nonexistent/release"

# --- Refund (should reject without valid deal) ---
echo "[Refund]"
check "Refund (no deal)" 404 \
    -X POST -H "Content-Type: application/json" \
    -d '{"user_id":"test","reason":"test","signature":"aabbccdd","timestamp":1700000000}' \
    "${BASE}/deals/nonexistent/refund"

# --- Verify no stale processes ---
echo "[Process]"
UVICORN_COUNT=$(ps aux | grep '[u]vicorn.*8001' | wc -l)
if [ "$UVICORN_COUNT" -eq 1 ]; then
    PASS=$((PASS + 1))
    echo "  ✓ Exactly 1 uvicorn process on port 8001"
else
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}\n  ✗ Expected 1 uvicorn process, found $UVICORN_COUNT"
    echo "  ✗ Expected 1 uvicorn process, found $UVICORN_COUNT"
fi

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "FAILURES:"
    echo -e "$ERRORS"
    echo ""
    echo "⚠ DEPLOY VERIFICATION FAILED — check logs with:"
    echo "  sudo journalctl -u escrow-api --since '2 min ago' --no-pager"
    exit 1
fi

echo ""
echo "All checks passed."
exit 0
