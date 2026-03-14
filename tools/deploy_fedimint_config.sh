#!/bin/bash
# Deploy Fedimint config + updated code to server
# Run this when server is back online
set -e

SERVER="${DEPLOY_SERVER:?Set DEPLOY_SERVER env var (e.g. user@host)}"
SERVER_PASS="${DEPLOY_PASS:?Set DEPLOY_PASS env var}"
REMOTE_DIR="/home/ralf/ln-escrow"

echo "=== Deploying updated escrow_client.py ==="
sshpass -p "$SERVER_PASS" scp -o StrictHostKeyChecking=no \
  "$REMOTE_DIR/backend/fedimint/escrow_client.py" \
  "$SERVER:$REMOTE_DIR/backend/fedimint/escrow_client.py"

echo "=== Installing websockets on server ==="
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "$SERVER" \
  "source $REMOTE_DIR/venv/bin/activate && pip install websockets -q"

echo "=== Restarting backend ==="
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no "$SERVER" \
  "echo '$SERVER_PASS' | sudo -S systemctl restart escrow-api && sleep 4 && systemctl is-active escrow-api"

echo "=== Done ==="
