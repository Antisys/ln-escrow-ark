# Mainnet Checklist

## Prerequisites

### Federation & Gateway
- [x] Fedimint federation running with escrow module (all guardians healthy)
- [x] LND gateway has sufficient inbound + outbound liquidity
- [x] `GET /system-status` shows `gateway.ok: true` and `federation.ok: true`

### Configuration
- [x] `MOCK_PAYMENTS=false` in production .env
- [ ] `ORACLE_PUBKEYS` set to 3 independent parties (NOT the service operator)
- [ ] Oracle private keys NOT on the server (only pubkeys)
- [x] `ADMIN_PUBKEYS` set to your wallet's LNURL-auth linking pubkey
- [x] `FEDIMINT_CLI_PATH` and `FEDIMINT_DATA_DIR` point to correct binaries/data
- [x] Federation client data dir backed up

### Testing
- [x] All unit tests pass: `pytest tests/ -x`
- [x] Full deal cycle tested: create → fund → release → verify seller received
- [x] Refund cycle tested: create → fund → refund → verify buyer received
- [x] Timeout tested: create → fund → wait for expiry → verify auto-payout
- [x] Dispute tested: create → fund → dispute → oracle resolve → verify payout
- [x] Kill switch tested: halt-payouts → verify blocked → resume → verify unblocked

---

## Progressive Amount Testing

| Round | Amount | Tests |
|-------|--------|-------|
| 1 | 1,000 sats | Create → fund → release → verify |
| 2 | 5,000 sats | Release + Refund |
| 3 | 10,000 sats | Release + Refund + Timeout auto-payout |
| 4 | 50,000 sats | Soak test: leave funded 1 hour, then release |
| 5 | 100,000 sats | Full flow including dispute (oracle attestation) |

### After Each Round
- [x] Check admin ledger — net sats matches expected
- [x] Check escrow status for all test deals: all resolved, none orphaned
- [x] No entries in failed payouts list
- [x] No errors in backend logs

---

## Monitoring

### Alert Conditions
- `gateway_payout_failed` in logs → investigate immediately
- `liquidity_insufficient` → add liquidity to gateway
- `payouts_halted: true` in system-status → kill switch active
- `payout_status: payout_stuck` in failed payouts → manual resolution needed

---

## Rollback Plan

1. **Kill switch**: POST to halt-payouts endpoint (admin panel or API)
2. **Check failed payouts**: admin panel Failed Payouts tab
3. **Set `MOCK_PAYMENTS=true`** to prevent further real payments while investigating
4. **For stuck escrows**: query escrow status via admin panel or `fedimint-cli`
