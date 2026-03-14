#!/bin/bash
# Simulate LN payment for a regtest invoice via devimint.
# The default devimint federation client pays the invoice.
# Used for testing the funding flow without real money.
#
# Usage: SSH_SERVER=user@host ./tools/simulate_payment.sh <bolt11_invoice>
# Returns: exit 0 on success, exit 1 on failure

set -e

BOLT11="${1:?Usage: $0 <bolt11_invoice>}"
SSH_TARGET="${SSH_SERVER:?Set SSH_SERVER env var (e.g. user@host)}"
DEVIMINT_ENV="${SERVER_DEVIMINT_ENV:-target/devimint/env}"
FEDIMINT_CLI="${SERVER_FEDIMINT_CLI:-fedimint-cli}"

REMOTE_CMD="
set +u
eval \"\$(cat $DEVIMINT_ENV)\"
echo 'Paying invoice via devimint default client...'
timeout 30 $FEDIMINT_CLI --data-dir \$FM_CLIENT_DIR module ln pay '$BOLT11' 2>&1
"

ssh "$SSH_TARGET" "$REMOTE_CMD"
