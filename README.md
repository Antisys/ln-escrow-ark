# trustMeBro-ARK — Non-Custodial Lightning Escrow on Ark Protocol

A non-custodial escrow service for Bitcoin Lightning Network, using [Ark Protocol](https://github.com/arkade-os/arkd) VTXOs as the trustless escrow layer.

Forked from [trustMeBro](https://github.com/Antisys/ln-escrow) (Fedimint version).

## How It Works

```
Buyer (Lightning) → LND → Ark VTXO Escrow → Release/Refund → LND → Seller/Buyer (Lightning)
```

1. **Seller creates a deal** — sets title, price, conditions, timeout
2. **Buyer joins** — authenticates with Lightning wallet (LNURL-auth)
3. **Buyer funds** — pays a Lightning invoice, funds are locked in Ark escrow VTXO
4. **Release** — buyer confirms delivery, escrow agent releases VTXO to seller
5. **Dispute** — if disagreement, 2-of-3 oracle arbitration resolves it
6. **Timeout** — buyer can always exit unilaterally after CSV timelock (Bitcoin Script enforced)

Users only interact with Lightning. Ark is invisible.

## Non-Custodial Architecture (4-Leaf Tapscript)

Every escrow VTXO has 4 spending paths, enforced by Bitcoin Script:

| Leaf | Who Signs | When |
|------|-----------|------|
| 0: Mutual Release | Buyer + Seller + Server | Both agree |
| 1: Escrow → Seller | Seller + Escrow + Server | Escrow approves delivery |
| 2: Escrow → Buyer | Buyer + Escrow + Server | Escrow approves refund |
| 3: Buyer Exit | Buyer alone (after timeout) | Trustless fallback |

**No single party can move funds alone.** Not the service, not the escrow agent, not the server.

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | SvelteKit (Svelte 5) |
| Backend | Python FastAPI |
| Escrow | Ark Protocol VTXOs ([ark-escrow](https://github.com/Antisys/ark-escrow)) |
| Auth | LNURL-auth (LUD-04) — wallet-based, no accounts |
| Payments | Lightning Network via LND |
| Database | SQLite |

## Differences from Fedimint Version

| | Fedimint (trustMeBro) | Ark (trustMeBro-ARK) |
|---|---|---|
| Escrow mechanism | Fedimint E-Cash module | Bitcoin Tapscript VTXO |
| Trust model | Federation consensus (4+ guardians) | Bitcoin Script (trustless) |
| Timeout recovery | Fedimint timeout path | CSV timelock (buyer can claim on-chain) |
| Fees | Fedimint gateway fee | 0 sats (Ark off-chain) |
| Settlement | Fedimint e-cash → LN | Ark VTXO → LN |

## Quick Start

```bash
# Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure ARK_ESCROW_URL, LND settings

# Frontend
cd frontend-svelte && npm install && cd ..

# Run
python -m backend.api.main        # Backend on :8001
cd frontend-svelte && npm run dev  # Frontend on :5173
```

## Related Repositories

- [ark-escrow](https://github.com/Antisys/ark-escrow) — Ark Escrow Agent (Go service)
- [arkd](https://github.com/arkade-os/arkd) — Ark Protocol server
- [ln-escrow](https://github.com/Antisys/ln-escrow) — Original Fedimint version

## License

MIT
