# Non-Custodial Escrow Architecture

## Overview

trustMeBro-ARK uses Fedimint as the escrow layer. Users interact exclusively via Lightning Network — Fedimint is invisible to them.

The core guarantee: **the service operator cannot move escrowed funds unilaterally.** Every claim operation requires cryptographic authorization from the rightful party.

```
Buyer (Lightning) → Fedimint Escrow Module → Release/Refund → Seller/Buyer (Lightning)
```

---

## Participants

| Role | What they hold | What they can do |
|------|---------------|-----------------|
| **Buyer** | Ephemeral private key, secret_code | Fund escrow, release to seller, open dispute, claim refund after timeout |
| **Seller** | Ephemeral private key | Claim with secret_code, open dispute, claim release after timeout |
| **Service** | Service key (federation member) | Submit delegated transactions on behalf of users, cannot claim without user signatures |
| **Oracles** (3) | Independent signing keys | Resolve disputes via 2-of-3 attestation |

---

## Key Management

### Ephemeral Keys (User-Controlled)

Each party derives an ephemeral key pair per deal:

```
LNURL-auth challenge (k1) = SHA256(deal_id + role + "vault-auth")   // deterministic
Wallet signs k1 → auth_signature
Ephemeral private key = HMAC-SHA256(auth_signature, deal_id + "ephemeral")
Ephemeral public key = secp256k1(ephemeral_private_key)
```

**Key property**: same wallet + same deal = same challenge = same signature = same ephemeral key. This enables recovery by re-authenticating with the same Lightning wallet.

Keys are stored in the browser's localStorage. The server never sees the private keys — only the public keys are registered.

### Secret Code (Buyer-Generated)

```
secret_code = random 32 bytes (generated in browser)
secret_code_hash = SHA256(secret_code)
```

- Only the hash is sent to the server and stored in the database
- The plaintext secret_code stays in the buyer's browser
- Release requires submitting the plaintext (server verifies against hash)

### Oracle Keys

Three independent Nostr keypairs. The service operator must NOT hold any of them.

Dispute resolution requires 2-of-3 agreeing attestations signed with BIP-340 Schnorr signatures.

---

## Escrow Lifecycle

### 1. Funding

```
Buyer pays LN invoice
    → Fedimint Lightning Gateway receives payment
    → Gateway creates Fedimint escrow (atomic: no intermediate e-cash)
    → Escrow registered with: buyer_pubkey, seller_pubkey, oracle_pubkeys,
       secret_code_hash, timeout_block, timeout_action
```

The escrow is a custom Fedimint module. Funds are held by the federation consensus — no single party (including the service) can extract them.

### 2. Release (Happy Path)

Buyer confirms delivery and releases funds to seller:

```
Buyer's browser:
    1. Signs release message with ephemeral private key (Schnorr)
    2. Sends secret_code + signature to service

Service:
    3. Submits ClaimDelegated transaction to federation:
       - secret_code (verified against hash)
       - buyer's Schnorr signature (verified against buyer_pubkey)
       - submitter_pubkey = service key (receives e-cash for LN payout)
    4. Federation validates: correct secret + valid buyer signature → releases funds
    5. Service pays seller via Lightning (atomic claim+pay)
```

**Why non-custodial**: the federation requires BOTH the secret_code AND the buyer's signature. The service has neither.

### 3. Refund

Same as release but without secret_code — requires the deal to be in a refundable state (disputed + oracle resolution, or admin action).

### 4. Timeout

Each deal has a `timeout_block` (Bitcoin block height) and `timeout_action` (release or refund).

At deal creation, both parties pre-sign timeout authorization messages:

```
Buyer signs: "timeout_claim:{deal_id}:{escrow_id}" with ephemeral key
Seller signs: "timeout_claim:{deal_id}:{escrow_id}" with ephemeral key
```

These signatures are stored on the server. After the timeout block is reached:

```
Service submits TimeoutClaimDelegated to federation:
    - Pre-signed Schnorr signature from authorized party
    - submitter_pubkey = service key
Federation validates:
    - Current block height ≥ timeout_block ✓
    - Signature valid for the authorized party ✓
    → Releases funds per timeout_action
```

**Why non-custodial**: the service cannot claim before the timeout (federation enforces block height). The pre-signed signature only authorizes the specific timeout action — it cannot be used for anything else.

### 5. Dispute Resolution

Either party can open a dispute by signing with their ephemeral key.

Resolution requires 2-of-3 oracle attestations:

```
Oracle attestation = {
    escrow_id,
    outcome: "Buyer" | "Seller",
    decided_at: timestamp,
    signature: BIP-340 Schnorr over attestation_signing_bytes
}

Service submits OracleAttestation to federation:
    - 2+ agreeing attestations from registered oracle pubkeys
    - submitter_pubkey = service key
Federation validates:
    - Each attestation pubkey is in the escrow's registered oracle set ✓
    - Each Schnorr signature is valid ✓
    - At least 2 attestations agree on outcome ✓
    → Releases funds to winner
```

**Why non-custodial**: oracles are independent third parties. The service cannot forge attestations. 2-of-3 threshold prevents any single oracle from deciding unilaterally.

---

## What If the Service Disappears?

Users can recover funds without the service:

1. **After timeout**: join the federation with any Fedimint client, submit `claim-timeout` with their ephemeral key (derived from their Lightning wallet)
2. **With secret_code**: buyer can submit `claim` directly to the federation
3. **With oracle help**: oracles can sign attestations that any Fedimint client can submit

The ephemeral key is deterministically derived from the wallet's LNURL-auth signature. Same wallet = same key = can always claim.

---

## Attack Analysis

### Malicious Service Operator

| Attack | Prevented by |
|--------|-------------|
| Claim escrow directly | Service key is submitter only — federation requires user signatures or oracle attestations |
| Forge buyer's release | Needs secret_code (random, never sent to server) + buyer's Schnorr signature |
| Claim before timeout | Federation enforces block height check |
| Redirect payout to own address | User submits their own payout invoice; if service substitutes, user can dispute |
| Forge oracle attestation | Needs oracle private keys (held by independent parties) |

### Malicious Buyer

| Attack | Prevented by |
|--------|-------------|
| Double-spend (release then claim back) | Fedimint consensus — escrow can only be claimed once |
| Refuse to release | Seller opens dispute → oracle resolution; or timeout releases to seller |

### Malicious Seller

| Attack | Prevented by |
|--------|-------------|
| Claim without delivering | Needs secret_code from buyer |
| Fake delivery proof | Oracles verify independently |

### Malicious Oracle (1 of 3)

| Attack | Prevented by |
|--------|-------------|
| Unilateral decision | 2-of-3 threshold — needs a second oracle to agree |
| Collude with service | Service is not an oracle; collusion with 1 oracle insufficient |

---

## Known Gaps (March 2026)

1. **Oracle keys not distributed**: All 3 dev keys are on the server. Must distribute to independent parties before significant funds.
2. **No standalone recovery tool**: Users would need technical knowledge to use `fedimint-cli` directly. A user-friendly recovery tool is planned.
3. **Payout address substitution**: The service resolves Lightning Addresses to BOLT11 at payout time. A malicious operator could theoretically substitute their own invoice. Mitigation: users can verify payment arrived in their wallet.

---

## Invariants

These must hold for the system to be non-custodial:

1. The service holds NO keys that can move funds unilaterally
2. Funding bypasses the service wallet (Fedimint gateway, atomic escrow creation)
3. `secret_code` is never stored on the server (only hash)
4. Oracle keys are held by 3 independent parties
5. If the service disappears, users recover without service involvement
