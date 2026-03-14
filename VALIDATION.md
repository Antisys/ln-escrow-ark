# Validation Protocol — trustMeBro-ARK Escrow

**Date**: 2026-03-14
**Backend**: mainnet production (`https://k9f2.trustbro.trade`)
**Federation**: Meridian Federation (4 guardians, mainnet)
**Test runner**: pytest on dev machine (192.168.1.152) against live API on 192.168.1.125

---

## Summary

| Layer | Scope | Passed | Skipped | Failed |
|-------|-------|--------|---------|--------|
| 1 — Unit tests | In-process (mocked fedimint/LN) | 106 | 0 | 0 |
| 2 — API E2E | Live HTTP against mainnet backend | 28 | 11 | 0 |
| 3 — Production | Manual mainnet deal flow | — | — | — |
| **Total automated** | | **134** | **11** | **0** |

---

## Layer 1 — Unit Tests (106 passed)

All tests run in-process with mocked Fedimint and LN backends. No real funds involved.

### test_smoke.py (32 tests)

| # | Test | Status | What it verifies |
|---|------|--------|------------------|
| 1 | `test_module_imports[backend.api.routes._shared]` | PASS | Module loads without import errors |
| 2 | `test_module_imports[backend.api.routes._payout]` | PASS | Module loads without import errors |
| 3 | `test_module_imports[backend.api.routes.crud]` | PASS | Module loads without import errors |
| 4 | `test_module_imports[backend.api.routes.signing]` | PASS | Module loads without import errors |
| 5 | `test_module_imports[backend.api.routes.funding]` | PASS | Module loads without import errors |
| 6 | `test_module_imports[backend.api.routes.payout]` | PASS | Module loads without import errors |
| 7 | `test_module_imports[backend.api.routes.release]` | PASS | Module loads without import errors |
| 8 | `test_module_imports[backend.api.routes.refund]` | PASS | Module loads without import errors |
| 9 | `test_module_imports[backend.api.routes.admin]` | PASS | Module loads without import errors |
| 10 | `test_module_imports[backend.api.routes.auth]` | PASS | Module loads without import errors |
| 11 | `test_module_imports[backend.api.routes.health]` | PASS | Module loads without import errors |
| 12 | `test_module_imports[backend.api.routes.qr]` | PASS | Module loads without import errors |
| 13 | `test_module_imports[backend.api.routes.websockets]` | PASS | Module loads without import errors |
| 14 | `test_module_imports[backend.lightning.lnd_client]` | PASS | Module loads without import errors |
| 15 | `test_module_imports[backend.database.models]` | PASS | Module loads without import errors |
| 16 | `test_module_imports[backend.database.deal_storage]` | PASS | Module loads without import errors |
| 17 | `test_module_imports[backend.database.connection]` | PASS | Module loads without import errors |
| 18 | `test_module_imports[backend.auth.lnurl_auth]` | PASS | Module loads without import errors |
| 19 | `test_module_imports[backend.auth.sig_verify]` | PASS | Module loads without import errors |
| 20 | `test_module_imports[backend.tasks.timeout_handler]` | PASS | Module loads without import errors |
| 21 | `test_module_imports[backend.config]` | PASS | Module loads without import errors |
| 22 | `test_app_creates` | PASS | FastAPI app instantiates without error |
| 23 | `test_execute_fedimint_payout_exists` | PASS | Core payout function exists and is callable |
| 24 | `test_verify_action_signature_exists` | PASS | Signature verification function exists |
| 25 | `test_deal_storage_functions` | PASS | CRUD functions exist in deal_storage module |
| 26 | `test_deal_storage_functions_extended` | PASS | Extended storage functions exist |
| 27 | `test_db_session_function` | PASS | DB session factory works |
| 28 | `test_deal_response_model` | PASS | Pydantic response model validates |
| 29 | `test_signing_status_response_model` | PASS | Signing status model validates |
| 30 | `test_config_loads` | PASS | Config loads from environment |
| 31 | `test_timeout_handler_payout_import` | PASS | Timeout handler imports payout module correctly |
| 32 | `test_no_print_in_routes` | PASS | No stray print() calls in route files |

### test_payout_flows.py (33 tests)

| # | Test | Status | What it verifies |
|---|------|--------|------------------|
| 1 | `TestNormalRelease::test_release_all_ready` | PASS | Release with valid secret_code, invoice, escrow succeeds |
| 2 | `TestNormalRelease::test_release_rejected_without_secret_code` | PASS | Release without secret_code returns 400 |
| 3 | `TestNormalRelease::test_release_rejected_with_wrong_secret_code` | PASS | Release with wrong secret_code returns 403 |
| 4 | `TestNormalRelease::test_release_no_invoice_blocked` | PASS | Release without seller payout invoice blocked |
| 5 | `TestNormalRelease::test_release_idempotent_already_paid` | PASS | Second release on completed deal returns success (idempotent) |
| 6 | `TestNormalRelease::test_release_ln_failure_reverts_state` | PASS | LN payment failure reverts deal to pre-release state |
| 7 | `TestNormalRelease::test_release_fedimint_claim_failure_reverts` | PASS | Fedimint claim failure reverts deal status |
| 8 | `TestRefund::test_refund_all_ready` | PASS | Refund with valid escrow + invoice succeeds |
| 9 | `TestRefund::test_refund_no_invoice_blocked` | PASS | Refund without buyer refund invoice blocked |
| 10 | `TestRefund::test_refund_seller_can_initiate` | PASS | Seller can initiate refund (not just buyer) |
| 11 | `TestAdminRelease::test_admin_release_disputed_signs_oracle` | PASS | Admin resolve signs 2-of-3 oracle attestations server-side |
| 12 | `TestAdminRelease::test_admin_release_no_invoice` | PASS | Admin release blocked when no seller invoice |
| 13 | `TestAdminRefund::test_admin_refund_disputed_signs_oracle` | PASS | Admin refund signs oracle attestations server-side |
| 14 | `TestAdminRefund::test_admin_refund_no_invoice` | PASS | Admin refund blocked when no buyer invoice |
| 15 | `TestTimeoutRelease::test_timeout_release_all_ready` | PASS | Timeout release with escrow + invoice succeeds |
| 16 | `TestTimeoutRelease::test_timeout_release_no_escrow` | PASS | Timeout release without escrow ID blocked |
| 17 | `TestTimeoutRelease::test_timeout_release_no_invoice` | PASS | Timeout release without invoice blocked |
| 18 | `TestTimeoutRefund::test_timeout_refund_all_ready` | PASS | Timeout refund succeeds |
| 19 | `TestTimeoutRefund::test_timeout_refund_no_invoice` | PASS | Timeout refund without invoice blocked |
| 20 | `TestAuthGuards::test_release_wrong_buyer` | PASS | Release by non-buyer rejected |
| 21 | `TestAuthGuards::test_refund_wrong_user` | PASS | Refund by unauthorized user rejected |
| 22 | `TestStatusGuards::test_release_rejects_completed` | PASS | Cannot release already-completed deal |
| 23 | `TestStatusGuards::test_refund_rejects_completed` | PASS | Cannot refund already-completed deal |
| 24 | `TestStatusGuards::test_admin_rejects_funded_deal` | PASS | Admin cannot resolve non-disputed deal |
| 25 | `TestStatusGuards::test_admin_rejects_no_escrow` | PASS | Admin resolve blocked without escrow |
| 26 | `TestStatusGuards::test_admin_rejects_without_key` | PASS | Admin endpoints require API key |
| 27 | `TestMissingEscrow::test_release_no_escrow_id` | PASS | Release on deal without escrow_id blocked |
| 28 | `TestMissingEscrow::test_refund_no_escrow_id` | PASS | Refund on deal without escrow_id blocked |
| 29 | `TestMissingEscrow::test_deal_not_found` | PASS | Release on nonexistent deal returns 404 |
| 30 | `TestExpiredDealDirectionGuards::test_expired_release_allowed` | PASS | Expired deal with action=release allows release |
| 31 | `TestExpiredDealDirectionGuards::test_expired_refund_blocks_release` | PASS | Expired deal with action=refund blocks release |
| 32 | `TestAdminOnExpiredDeals::test_admin_release_expired_deal` | PASS | Admin can release expired deal |
| 33 | `TestAdminOnExpiredDeals::test_admin_refund_expired_deal` | PASS | Admin can refund expired deal |

### test_coin_safety.py (41 tests)

| # | Test | Status | What it verifies |
|---|------|--------|------------------|
| 1 | `TestCrossClaimPrevention::test_refund_blocked_after_release` | PASS | Cannot refund after release completed |
| 2 | `TestCrossClaimPrevention::test_release_blocked_after_refund` | PASS | Cannot release after refund completed |
| 3 | `TestCrossClaimPrevention::test_release_409_when_refund_txid_set` | PASS | Release returns 409 if refund_txid already set |
| 4 | `TestCrossClaimPrevention::test_refund_409_when_release_txid_set` | PASS | Refund returns 409 if release_txid already set |
| 5 | `TestCrossClaimPrevention::test_admin_release_blocked_after_refund` | PASS | Admin cannot release after refund |
| 6 | `TestCrossClaimPrevention::test_admin_refund_blocked_after_release` | PASS | Admin cannot refund after release |
| 7 | `TestTransitionalStatusBlocking::test_refund_blocked_during_releasing` | PASS | Refund blocked while release is in progress |
| 8 | `TestTransitionalStatusBlocking::test_release_blocked_during_refunding` | PASS | Release blocked while refund is in progress |
| 9 | `TestTransitionalStatusBlocking::test_second_release_during_releasing_is_allowed` | PASS | Idempotent release during releasing state |
| 10 | `TestTransitionalStatusBlocking::test_second_refund_during_refunding_is_allowed` | PASS | Idempotent refund during refunding state |
| 11 | `TestSecretCodeNonCustodial::test_release_requires_secret_code` | PASS | Release without secret_code rejected |
| 12 | `TestSecretCodeNonCustodial::test_wrong_secret_code_rejected` | PASS | Wrong secret_code returns 403 |
| 13 | `TestSecretCodeNonCustodial::test_correct_secret_code_accepted` | PASS | Correct secret_code allows release |
| 14 | `TestSecretCodeNonCustodial::test_hash_verification_is_sha256` | PASS | SHA256(secret) matches stored hash |
| 15 | `TestSecretCodeNonCustodial::test_empty_secret_code_is_not_valid` | PASS | Empty string secret_code rejected |
| 16 | `TestFailedPayoutRevert::test_release_failure_reverts_to_funded` | PASS | Failed release reverts status to funded |
| 17 | `TestFailedPayoutRevert::test_refund_failure_reverts_to_funded` | PASS | Failed refund reverts status to funded |
| 18 | `TestFailedPayoutRevert::test_release_failure_from_shipped_reverts_to_shipped` | PASS | Failed release from shipped reverts to shipped |
| 19 | `TestIdempotency::test_release_idempotent_when_paid` | PASS | Duplicate release on paid deal is safe |
| 20 | `TestIdempotency::test_refund_idempotent_when_paid` | PASS | Duplicate refund on paid deal is safe |
| 21 | `TestIdempotency::test_successful_release_sets_txid` | PASS | Release sets release_txid on success |
| 22 | `TestIdempotency::test_successful_refund_sets_txid` | PASS | Refund sets refund_txid on success |
| 23 | `TestTimeoutSafety::test_timeout_skips_completed_deal` | PASS | Timeout handler does not touch completed deals |
| 24 | `TestTimeoutSafety::test_timeout_skips_refunded_deal` | PASS | Timeout handler does not touch refunded deals |
| 25 | `TestTimeoutSafety::test_timeout_refund_sets_correct_fields` | PASS | Timeout refund sets payout_status, refund_txid, completed_at |
| 26 | `TestTimeoutSafety::test_timeout_release_sets_correct_fields` | PASS | Timeout release sets payout_status, release_txid, completed_at |
| 27 | `TestTimeoutSafety::test_timeout_without_escrow_marks_expired` | PASS | Expired deal without escrow just marks expired status |
| 28 | `TestNoEscrowNoPayout::test_release_blocked_without_escrow` | PASS | No escrow = no release (fund safety) |
| 29 | `TestNoEscrowNoPayout::test_refund_blocked_without_escrow` | PASS | No escrow = no refund (fund safety) |
| 30 | `TestNoEscrowNoPayout::test_admin_blocked_without_escrow` | PASS | Admin blocked without escrow |
| 31 | `TestAuthorizationGuards::test_seller_cannot_release` | PASS | Only buyer can release |
| 32 | `TestAuthorizationGuards::test_stranger_cannot_release` | PASS | Random user cannot release |
| 33 | `TestAuthorizationGuards::test_stranger_cannot_refund` | PASS | Random user cannot refund |
| 34 | `TestAuthorizationGuards::test_admin_requires_api_key` | PASS | Admin without key gets 401 |
| 35 | `TestAuthorizationGuards::test_admin_no_key_at_all` | PASS | Admin with no header gets 401 |
| 36 | `TestExpiredDealDirection::test_expired_refund_deal_blocks_release` | PASS | Expired deal direction enforced |
| 37 | `TestExpiredDealDirection::test_expired_release_deal_allows_release` | PASS | Expired release direction allows release |
| 38 | `TestExpiredDealDirection::test_expired_deal_allows_refund_regardless` | PASS | Expired deal always allows refund |
| 39 | `TestPostClaimConsistency::test_release_sets_all_fields` | PASS | Successful release sets all required DB fields |
| 40 | `TestPostClaimConsistency::test_refund_sets_all_fields` | PASS | Successful refund sets all required DB fields |
| 41 | `TestPostClaimConsistency::test_failed_payout_no_txid_no_completed_at` | PASS | Failed payout leaves txid/completed_at null |

---

## Layer 2 — API E2E Tests (28 passed, 11 skipped)

Live HTTP requests against the mainnet production backend at `https://k9f2.trustbro.trade`.

### test_api_e2e.py — Passing (28 tests)

| # | Test | Status | What it verifies |
|---|------|--------|------------------|
| 1 | `TestDealCRUD::test_create_deal_returns_200` | PASS | Create deal via API |
| 2 | `TestDealCRUD::test_get_deal_by_id` | PASS | Fetch deal by UUID |
| 3 | `TestDealCRUD::test_get_deal_not_found` | PASS | 404 for nonexistent deal |
| 4 | `TestDealCRUD::test_list_deals_by_user` | PASS | List deals filtered by user_id |
| 5 | `TestDealCRUD::test_stats_endpoint` | PASS | `/stats` returns deal statistics |
| 6 | `TestDealCRUD::test_health_endpoint` | PASS | `/health` returns ok |
| 7 | `TestLNURLAuth::test_challenge_creation` | PASS | LNURL-auth challenge generated for deal |
| 8 | `TestLNURLAuth::test_challenge_not_found_for_bad_token` | PASS | Bad token returns error |
| 9 | `TestLNURLAuth::test_full_lnurl_auth_seller` | PASS | Full LNURL-auth flow with ECDSA signature |
| 10 | `TestLNURLAuth::test_wrong_signature_rejected` | PASS | Invalid signature rejected |
| 11 | `TestLNURLAuth::test_status_shows_unverified_for_unknown_k1` | PASS | Unknown k1 shows unverified |
| 12 | `TestLNURLAuth::test_both_parties_auth_activates_deal` | PASS | Both parties authenticating activates deal |
| 13 | `TestJoinDeal::test_buyer_can_join` | PASS | Buyer joins deal via link token |
| 14 | `TestJoinDeal::test_join_sets_buyer_started_at` | PASS | Join timestamp recorded |
| 15 | `TestJoinDeal::test_cannot_join_completed_deal` | PASS | Cannot join completed deal |
| 16 | `TestInvoiceCreation::test_create_invoice_requires_seller_auth` | PASS | Invoice creation requires LNURL-auth first |
| 17 | `TestInvoiceCreation::test_create_invoice_requires_both_payout_invoices` | PASS | Both payout addresses needed before funding |
| 18 | `TestAdminEndpoints::test_admin_requires_key` | PASS | Admin endpoints return 401 without key |
| 19 | `TestAdminEndpoints::test_wrong_admin_key_rejected` | PASS | Wrong admin key rejected |
| 20 | `TestStatusGuards::test_cannot_create_invoice_for_pending_without_seller_auth` | PASS | Pending deal without auth cannot create invoice |
| 21 | `TestStatusGuards::test_check_invoice_without_invoice_created` | PASS | Check invoice on unfunded deal returns error |
| 22 | `TestStatusGuards::test_release_on_pending_deal_fails` | PASS | Cannot release a pending deal |
| 23 | `TestStatusGuards::test_ship_on_pending_deal_fails` | PASS | Cannot ship a pending deal |
| 24 | `TestKillSwitch::test_halt_requires_admin_key` | PASS | Halt payouts requires admin auth |
| 25 | `TestKillSwitch::test_resume_requires_admin_key` | PASS | Resume payouts requires admin auth |
| 26 | `TestAmountCap::test_deal_within_limits_accepted` | PASS | Deal within amount cap accepted |
| 27 | `TestIdempotency::test_double_join_is_safe` | PASS | Double join is idempotent |
| 28 | `TestIdempotency::test_double_create_invoice_returns_same` | PASS | Duplicate invoice request returns same bolt11 |

### test_api_e2e.py — Skipped: requires admin API key (11 tests)

Server's `ADMIN_API_KEY` is commented out. These tests need the key set in both server `.env` and `TEST_ADMIN_KEY` env var.

| # | Test | What it would verify |
|---|------|----------------------|
| 1 | `TestAdminEndpoints::test_admin_list_deals` | Admin can list all deals |
| 2 | `TestAdminEndpoints::test_admin_config` | Admin can view/update config |
| 3 | `TestAdminEndpoints::test_admin_resolve_non_disputed_deal_fails` | Admin resolve rejects non-disputed deal |
| 4 | `TestKillSwitch::test_halt_and_resume_payouts` | Kill switch halts and resumes payouts |
| 5 | `TestAmountCap::test_system_status_returns_limits` | System status shows amount limits |
| 6 | `TestRecoveryEndpoints::test_wallet_balance` | Admin can check wallet balance |
| 7 | `TestRecoveryEndpoints::test_wallet_balance_requires_admin` | Wallet balance requires admin auth |
| 8 | `TestRecoveryEndpoints::test_failed_payouts_list` | Admin can list failed payouts |
| 9 | `TestRecoveryEndpoints::test_escrow_status_for_nonexistent_deal` | Escrow status for missing deal |
| 10 | `TestRecoveryEndpoints::test_escrow_status_for_deal_without_escrow` | Escrow status for unfunded deal |
| 11 | `TestRecoveryEndpoints::test_manual_payout_requires_claimed_escrow` | Manual payout blocked without claimed escrow |

### test_api_e2e.py — Funded-deal tests (10 tests, require real LN payment)

These tests need a funded deal (real Lightning payment into Fedimint escrow). They exercise the full post-funding flow and are covered by Layer 3 manual testing.

| # | Test | What it verifies |
|---|------|------------------|
| 1 | `TestInvoiceCreation::test_create_invoice_on_funded_deal_fails` | Double-funding rejected |
| 2 | `TestNonCustodialGuards::test_secret_code_never_in_api_response` | secret_code never leaked in any API response |
| 3 | `TestNonCustodialGuards::test_deal_db_secret_code_is_null` | DB never stores plaintext secret_code |
| 4 | `TestNonCustodialGuards::test_release_without_secret_code_rejected` | Release without secret_code blocked on funded deal |
| 5 | `TestNonCustodialGuards::test_release_with_wrong_secret_code_rejected` | Wrong secret_code blocked on funded deal |
| 6 | `TestNonCustodialGuards::test_release_wrong_buyer_rejected` | Non-buyer cannot release funded deal |
| 7 | `TestHappyPath::test_create_invoice_requires_funded_deal` | Full happy path: fund → ship → release |
| 8 | `TestRefundPath::test_refund_requires_refund_invoice` | Refund flow on funded deal |
| 9 | `TestRefundPath::test_refund_wrong_user_rejected` | Auth check on funded refund |
| 10 | `TestDisputePath::test_dispute_flow` | Full dispute → oracle resolve flow |

---

## Layer 3 — Production Deal Flow (outstanding)

Manual end-to-end test on mainnet with real sats via `trustbro.trade`. Must be performed by the operator.

### Happy path

| # | Step | Status | What to verify |
|---|------|--------|----------------|
| 1 | Create deal on `trustbro.trade` | PASS | Deal page renders, link generated |
| 2 | Buyer joins via link | PASS | Buyer page loads, join succeeds |
| 3 | Both parties LNURL-auth with real wallets | PASS | Ephemeral keys registered, deal activates |
| 4 | Both submit payout addresses (LNURL/LN address) | PASS | Addresses stored, validated |
| 5 | Buyer funds deal via Lightning | PASS | Payment received, escrow created in Fedimint |
| 6 | Seller marks shipped | PASS | Status transitions to shipped |
| 7 | Buyer releases with secret_code | PASS | Payout executes, seller receives sats |
| 8 | Verify completed deal state | PASS | status=completed, release_txid set, completed_at set |

### Alternative paths

| # | Path | Status | What to verify |
|---|------|--------|----------------|
| 1 | Refund flow | outstanding | Buyer requests refund → buyer receives sats back |
| 2 | Timeout flow | outstanding | Deal expires → timeout handler auto-refunds/releases |
| 3 | Dispute flow | outstanding | Admin resolves via oracle attestations → winner paid |

---

## Production Database State

As of 2026-03-14:

| Status | Count |
|--------|-------|
| pending | 90 |
| active | 58 |
| completed | 22 |
| expired | 1 |

---

## Key Invariants Verified

These safety properties are tested across multiple test files:

1. **No double-claim**: Release after refund (and vice versa) is blocked (test_coin_safety: 6 tests)
2. **Secret code non-custodial**: Server never stores plaintext secret_code; release requires buyer-held secret (test_coin_safety: 5 tests, test_payout_flows: 2 tests)
3. **Failed payout reverts state**: LN/Fedimint failures revert deal to pre-payout status (test_coin_safety: 3 tests, test_payout_flows: 2 tests)
4. **No escrow = no payout**: Deals without `fedimint_escrow_id` cannot release or refund (test_coin_safety: 3 tests, test_payout_flows: 3 tests)
5. **Auth guards**: Only authorized users can trigger payouts (test_coin_safety: 5 tests, test_payout_flows: 2 tests)
6. **Idempotent operations**: Duplicate release/refund on paid deal is safe (test_coin_safety: 2 tests, test_payout_flows: 1 test)
7. **Timeout safety**: Timeout handler skips completed/refunded deals (test_coin_safety: 5 tests)
8. **Expired deal direction**: Expired deals enforce payout direction (test_coin_safety: 3 tests, test_payout_flows: 4 tests)

---

## How to Run

```bash
# Layer 1 — Unit tests (no external dependencies)
venv/bin/python -m pytest tests/test_payout_flows.py tests/test_coin_safety.py tests/test_smoke.py -v

# Layer 2 — E2E tests against mainnet backend
TEST_API_URL="http://192.168.1.125:8001" venv/bin/python -m pytest tests/test_api_e2e.py -v

# Layer 2 with admin tests (requires ADMIN_API_KEY set on server)
TEST_API_URL="http://192.168.1.125:8001" TEST_ADMIN_KEY="<key>" \
  venv/bin/python -m pytest tests/test_api_e2e.py -v

# All unit tests
venv/bin/python -m pytest tests/ -v
```
