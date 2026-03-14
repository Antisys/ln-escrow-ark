#!/bin/bash
set -e

SERVER="${DEPLOY_SERVER:?Set DEPLOY_SERVER env var (e.g. user@host)}"
SERVER_PASS="${DEPLOY_PASS:?Set DEPLOY_PASS env var}"
REMOTE_DIR="/home/ralf/ln-escrow"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ───────────────────────────────────────────────────────────────
# PRE-DEPLOY: Run tests locally before touching the server
# ───────────────────────────────────────────────────────────────

echo "=== Step 0: Pre-deploy tests (local) ==="
cd "$SCRIPT_DIR"
source venv/bin/activate

echo "Running all tests..."
python -m pytest tests/ -x -q --tb=short --ignore=tests/test_api_e2e.py 2>&1
echo ""
echo "All local tests passed."

# ───────────────────────────────────────────────────────────────
# DEPLOY: Build, sync, restart
# ───────────────────────────────────────────────────────────────

echo ""
echo "=== Step 1: Build frontend ==="
cd "$SCRIPT_DIR/frontend-svelte"
npm run build
cd "$SCRIPT_DIR"

echo ""
echo "=== Step 2: Rsync to server ==="
sshpass -p "$SERVER_PASS" rsync -avz --delete \
  -e "ssh -o StrictHostKeyChecking=no" \
  --exclude 'node_modules/' \
  --exclude 'venv/' \
  --exclude '.git/' \
  --exclude 'frontend/' \
  --exclude 'data/testnet_wallet/test_keys.json' \
  --exclude 'data/escrow.db' \
  --exclude '.env' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'frontend-svelte/node_modules/' \
  --exclude 'frontend-svelte/.svelte-kit/' \
  ./ "${SERVER}:${REMOTE_DIR}/"

echo ""
echo "=== Step 3: Sync frontend build to nginx webroot (clean) ==="
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "$SERVER" "
  echo '$SERVER_PASS' | sudo -S rsync -a --delete ${REMOTE_DIR}/frontend-svelte/build/ /var/www/html/
  echo 'Frontend synced to /var/www/html/ (stale files removed)'
"

echo ""
echo "=== Step 4: Restart backend ==="
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "$SERVER" "
  echo '$SERVER_PASS' | sudo -S systemctl restart escrow-api
  echo 'escrow-api restarted, waiting for startup...'
  sleep 5
  systemctl is-active escrow-api
"

# ───────────────────────────────────────────────────────────────
# POST-DEPLOY: Verify the live service works
# ───────────────────────────────────────────────────────────────

echo ""
echo "=== Step 5: Post-deploy verification ==="
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "$SERVER" "bash ${REMOTE_DIR}/deploy/post_deploy_test.sh"

POST_RESULT=$?
if [ $POST_RESULT -ne 0 ]; then
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  ⚠ POST-DEPLOY TESTS FAILED                 ║"
    echo "║  The service is running but something broke. ║"
    echo "║  Check the failures above.                   ║"
    echo "╚══════════════════════════════════════════════╝"
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  ✓ Deploy complete — all tests passed        ║"
echo "╚══════════════════════════════════════════════╝"
