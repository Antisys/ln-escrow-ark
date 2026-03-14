#!/bin/bash
# Monitor script for ln-escrow service
# Usage: ADMIN_PUBKEY=<hex> bash tools/monitor.sh [api_url]
# Legacy: ADMIN_API_KEY=<key> bash tools/monitor.sh [api_url]

API="${1:-http://localhost:8001}"
PUBKEY="${ADMIN_PUBKEY:-}"
KEY="${ADMIN_API_KEY:-}"

# Build auth header
if [ -n "$PUBKEY" ]; then
    AUTH_HEADER="X-Admin-Pubkey: $PUBKEY"
elif [ -n "$KEY" ]; then
    AUTH_HEADER="X-Admin-Key: $KEY"
else
    echo "ERROR: Set ADMIN_PUBKEY (preferred) or ADMIN_API_KEY"
    exit 1
fi

echo "=== Health ==="
curl -s "$API/health" | python3 -m json.tool 2>/dev/null || echo "FAILED"

echo ""
echo "=== System Status ==="
STATUS=$(curl -s "$API/system-status")
echo "$STATUS" | python3 -m json.tool 2>/dev/null || echo "FAILED"

# Check for warnings
if echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('payouts_halted') else 1)" 2>/dev/null; then
    echo "WARNING: PAYOUTS ARE HALTED!"
fi

echo ""
echo "=== Wallet Balance ==="
curl -s -H "$AUTH_HEADER" "$API/deals/admin/wallet-balance" | python3 -m json.tool 2>/dev/null || echo "FAILED (check credentials)"

echo ""
echo "=== Failed Payouts ==="
FAILED=$(curl -s -H "$AUTH_HEADER" "$API/deals/admin/failed-payouts")
echo "$FAILED" | python3 -m json.tool 2>/dev/null || echo "FAILED (check credentials)"

COUNT=$(echo "$FAILED" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null)
if [ "$COUNT" != "0" ] && [ -n "$COUNT" ]; then
    echo "WARNING: $COUNT deal(s) with failed/stuck payouts!"
fi

echo ""
echo "=== Done ==="
