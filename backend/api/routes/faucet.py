"""
Regtest faucet endpoint — sends test coins to a given address.
Only works when MOCK_PAYMENTS=true (regtest/dev mode).
"""
import os
import logging
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

BECH32M_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def _hex_to_bcrt1p(script_hex: str) -> str:
    """Convert a P2TR hex scriptPubKey (5120...) to bcrt1p... bech32m address."""
    witness = bytes.fromhex(script_hex[4:])  # strip OP_1 OP_PUSHBYTES_32

    def _polymod(values):
        GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
        chk = 1
        for v in values:
            b = chk >> 25
            chk = ((chk & 0x1ffffff) << 5) ^ v
            for i in range(5):
                chk ^= GEN[i] if ((b >> i) & 1) else 0
        return chk

    def _hrp_expand(hrp):
        return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]

    def _convertbits(data, frombits, tobits):
        acc, bits, ret = 0, 0, []
        for v in data:
            acc = (acc << frombits) | v
            bits += frombits
            while bits >= tobits:
                bits -= tobits
                ret.append((acc >> bits) & ((1 << tobits) - 1))
        if bits:
            ret.append((acc << (tobits - bits)) & ((1 << tobits) - 1))
        return ret

    data = [1] + _convertbits(witness, 8, 5)  # version 1 = taproot
    values = _hrp_expand("bcrt") + data + [0, 0, 0, 0, 0, 0]
    polymod = _polymod(values) ^ 0x2bc830a3  # bech32m constant
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return "bcrt1" + "".join(BECH32M_CHARSET[d] for d in data) + "".join(BECH32M_CHARSET[c] for c in checksum)


class FaucetRequest(BaseModel):
    address: str
    amount_sats: int = 100000


class FaucetResponse(BaseModel):
    txid: str
    amount_sats: int
    address: str


@router.get("/faucet/address")
async def faucet_address():
    """Get a fresh regtest address from the Bitcoin node."""
    if os.getenv("MOCK_PAYMENTS", "").lower() != "true":
        raise HTTPException(status_code=403, detail="Only in regtest mode")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "http://bitcoin:18443",
                json={"jsonrpc": "1.0", "method": "getnewaddress", "params": []},
                auth=("admin1", "123"),
            )
            if resp.status_code == 200:
                addr = resp.json().get("result", "")
                if addr:
                    return {"address": addr}
        raise HTTPException(status_code=502, detail="Could not get address from node")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Node unreachable: {e}")


@router.post("/faucet", response_model=FaucetResponse)
async def faucet(body: FaucetRequest):
    """Send regtest coins to an address via nigiri faucet."""
    if os.getenv("MOCK_PAYMENTS", "").lower() != "true":
        raise HTTPException(status_code=403, detail="Faucet only available in regtest/dev mode")

    if not body.address or len(body.address) < 10:
        raise HTTPException(status_code=400, detail="Invalid address")

    address = body.address
    # Convert 5120... hex scriptPubKey to bcrt1p... bech32m address
    if address.startswith("5120") and len(address) == 68:
        address = _hex_to_bcrt1p(address)

    amount_btc = body.amount_sats / 100_000_000

    try:
        # Try nigiri faucet via chopsticks API
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "http://chopsticks:3000/faucet",
                json={"address": address, "amount": amount_btc},
            )
            if resp.status_code == 200:
                data = resp.json()
                txid = data.get("txId", data.get("txid", "unknown"))

                # Mine a block to confirm
                try:
                    await client.post("http://chopsticks:3000/faucet", json={"address": body.address, "amount": 0})
                except Exception:
                    pass  # non-fatal

                logger.info("Faucet: sent %d sats to %s txid=%s", body.amount_sats, body.address[:20], txid[:12])
                return FaucetResponse(txid=txid, amount_sats=body.amount_sats, address=body.address)
            else:
                raise HTTPException(status_code=502, detail=f"Faucet failed: {resp.text}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Faucet error: %s", e)
        raise HTTPException(status_code=502, detail=f"Faucet unavailable: {str(e)}")
