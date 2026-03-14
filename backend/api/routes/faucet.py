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


class FaucetRequest(BaseModel):
    address: str
    amount_sats: int = 100000


class FaucetResponse(BaseModel):
    txid: str
    amount_sats: int
    address: str


@router.post("/faucet", response_model=FaucetResponse)
async def faucet(body: FaucetRequest):
    """Send regtest coins to an address via nigiri faucet."""
    if os.getenv("MOCK_PAYMENTS", "").lower() != "true":
        raise HTTPException(status_code=403, detail="Faucet only available in regtest/dev mode")

    if not body.address or len(body.address) < 10:
        raise HTTPException(status_code=400, detail="Invalid address")

    amount_btc = body.amount_sats / 100_000_000

    try:
        # Try nigiri faucet via chopsticks API
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "http://chopsticks:3000/faucet",
                json={"address": body.address, "amount": amount_btc},
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
