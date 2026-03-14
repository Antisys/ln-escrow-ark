# trustMeBro-ARK — Roadmap

Stand: 2026-03-12

## Current Status: MAINNET — Non-Custodial Escrow via Fedimint

Live at [trustbro.trade](https://trustbro.trade). Full deal lifecycle working:
Deal create → LNURL-auth → LN fund → Fedimint escrow → Release/Refund via LN.

---

## What's Working

### Core Escrow Flow
- [x] Deal creation with configurable timeout and timeout action (release/refund)
- [x] Buyer funding via Lightning invoice (Fedimint gateway, atomic escrow creation)
- [x] Release: buyer provides secret_code + Schnorr signature → seller paid via LN
- [x] Refund: buyer submits refund invoice → refunded via LN
- [x] Timeout: automatic payout when deadline expires (delegated Schnorr signatures)
- [x] Dispute: 2-of-3 oracle attestation resolution

### Non-Custodial Architecture
- [x] Buyer-generated secret_code (only hash stored on server)
- [x] Ephemeral keys derived from LNURL-auth (deterministic, recoverable)
- [x] Delegated Schnorr signatures for all Fedimint claim operations
- [x] Atomic claim+pay (no intermediate e-cash in service wallet)
- [x] Pre-signed timeout signatures stored for automatic expiry payout
- [x] Encrypted vault backup (AES-256-GCM, key derived from ephemeral key)

### Authentication
- [x] LNURL-auth (LUD-04) for buyer + seller + admin
- [x] QR code scanning (Phoenix, Zeus, Breez, any LNURL-auth wallet)
- [x] WebLN support (Alby browser extension)
- [x] Admin authentication via LNURL-auth with pubkey allowlist

### Backend
- [x] FastAPI with async endpoints
- [x] Fedimint escrow client (CLI + HTTP daemon modes)
- [x] LND REST client for Lightning payments
- [x] WebSocket real-time deal status updates
- [x] Background timeout handler with exponential backoff retry
- [x] Payout kill switch (admin can halt all payouts)
- [x] Rate limiting with category-aware exclusions
- [x] Atomic status transitions (race condition safe)
- [x] Graceful shutdown with in-flight request drain

### Frontend (SvelteKit + Svelte 5)
- [x] Deal create/join/view pages
- [x] LNURL-auth QR component with WebLN fallback
- [x] Real-time status updates via WebSocket
- [x] Client-side Schnorr signing (secp256k1)
- [x] Encrypted key backup/recovery
- [x] Admin panel (deals, disputes, balances, settings, failed payouts)
- [x] Dark theme, responsive design

### Deployment
- [x] Server deployment via rsync + systemd
- [x] Cloudflare Tunnel (HTTPS)
- [x] nginx for frontend, uvicorn for backend
- [x] Fedimint federation (4 guardians via Docker)
- [x] LND gateway for Lightning routing

---

## Known Gaps

### Security (Must Fix)
- [ ] **Oracle key distribution**: All 3 oracle private keys are dev keys on the server. Must distribute to 3 independent parties before significant funds are at stake.
- [ ] **Standalone recovery tool**: Users can technically recover via `fedimint-cli` after timeout, but no user-friendly tool exists yet.

### Code Quality
- [ ] Extract shared Modal/Button/Spinner components (CSS duplicated 5-8x)
- [ ] Deal page too large (794 lines) — split into smaller components
- [ ] Connection pooling for Fedimint HTTP client
- [ ] Bounded retry state dicts (currently grow unbounded)
- [ ] CI/CD pipeline (GitHub Actions)

### Features
- [ ] In-app messaging between buyer and seller
- [ ] Deal templates / recurring deals
- [ ] Multi-currency support (different denominations)
- [ ] Mobile-optimized PWA
- [ ] Nostr integration for oracle attestation publishing

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│         Frontend (SvelteKit, static build)           │
│              trustbro.trade                          │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS + WebSocket
┌──────────────────────▼──────────────────────────────┐
│            Backend API (FastAPI, port 8001)           │
│              k9f2.trustbro.trade                     │
│  - /deals/* /auth/* /funding/* /release/* /refund/*  │
│  - timeout_handler (deal expiry, 60s loop)           │
│  - oracle attestation signing (admin bridge)         │
└──────────────────────┬──────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│  Fedimint  │  │    LND     │  │  SQLite    │
│ Federation │  │  Gateway   │  │    DB      │
│ (4 guards) │  │            │  │            │
│ + escrow   │  │            │  │            │
│   module   │  │            │  │            │
└────────────┘  └────────────┘  └────────────┘
```
