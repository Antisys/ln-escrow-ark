"""
Low-level async HTTP client for the Ark Escrow Agent service.
Replaces backend/fedimint/escrow_client.py.
"""
import os
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ARK_ESCROW_URL = os.getenv("ARK_ESCROW_URL", "http://localhost:9090")
_TIMEOUT = 30.0


class ArkEscrowError(Exception):
    """Base error for Ark escrow operations."""
    pass


class ArkEscrowNotFoundError(ArkEscrowError):
    """Deal not found in Ark escrow agent."""
    pass


class ArkEscrowStateError(ArkEscrowError):
    """Invalid state transition in Ark escrow."""
    pass


@dataclass
class CreateEscrowResult:
    deal_id: str
    escrow_pubkey: str
    tapscripts: list[str]
    address: str


@dataclass
class EscrowInfo:
    deal_id: str
    status: str
    amount: int
    address: str
    buyer_pubkey: str = ""
    seller_pubkey: str = ""
    escrow_pubkey: str = ""
    vtxo_txid: Optional[str] = None
    vtxo_vout: Optional[int] = None
    created_at: str = ""
    expires_at: str = ""


@dataclass
class SignedAttestation:
    """Oracle attestation for dispute resolution."""
    pubkey: str
    signature: str
    content: dict = field(default_factory=dict)


class ArkEscrowClient:
    """HTTP client for the Ark Escrow Agent service."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or ARK_ESCROW_URL).rstrip("/")

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.request(method, url, **kwargs)

                if resp.status_code == 404:
                    raise ArkEscrowNotFoundError(f"Not found: {path}")
                if resp.status_code == 409:
                    data = resp.json()
                    raise ArkEscrowStateError(data.get("error", "state conflict"))
                if resp.status_code >= 400:
                    text = resp.text
                    raise ArkEscrowError(f"HTTP {resp.status_code}: {text}")

                return resp.json()
        except httpx.RequestError as e:
            raise ArkEscrowError(f"Connection error: {e}") from e

    async def create_escrow(
        self,
        buyer_pubkey: str,
        seller_pubkey: str,
        amount: int,
        timeout_blocks: int = 144,
    ) -> CreateEscrowResult:
        """Create a new escrow deal in the Ark agent."""
        data = await self._request("POST", "/escrow/v1/deals", json={
            "buyer_pubkey": buyer_pubkey,
            "seller_pubkey": seller_pubkey,
            "amount": amount,
            "timeout_blocks": timeout_blocks,
        })
        return CreateEscrowResult(
            deal_id=data["deal_id"],
            escrow_pubkey=data["escrow_pubkey"],
            tapscripts=data["tapscripts"],
            address=data["address"],
        )

    async def get_escrow_info(self, deal_id: str) -> EscrowInfo:
        """Fetch escrow deal state from the Ark agent."""
        data = await self._request("GET", f"/escrow/v1/deals/{deal_id}")
        return EscrowInfo(
            deal_id=data["id"],
            status=data["status"],
            amount=data["amount"],
            address=data.get("address", ""),
            buyer_pubkey=data.get("buyer_pubkey", ""),
            seller_pubkey=data.get("seller_pubkey", ""),
            escrow_pubkey=data.get("escrow_pubkey", ""),
            vtxo_txid=data.get("vtxo_txid"),
            vtxo_vout=data.get("vtxo_vout"),
            created_at=data.get("created_at", ""),
            expires_at=data.get("expires_at", ""),
        )

    async def fund_escrow(self, deal_id: str, vtxo_txid: str, vtxo_vout: int) -> None:
        """Mark deal as funded with VTXO reference."""
        await self._request("POST", f"/escrow/v1/deals/{deal_id}/fund", json={
            "vtxo_txid": vtxo_txid,
            "vtxo_vout": vtxo_vout,
        })

    async def release_escrow(self, deal_id: str) -> dict:
        """Release escrow funds to seller (escrow agent signs Leaf 1)."""
        return await self._request("POST", f"/escrow/v1/deals/{deal_id}/release", json={})

    async def refund_escrow(self, deal_id: str) -> dict:
        """Refund escrow funds to buyer (escrow agent signs Leaf 2)."""
        return await self._request("POST", f"/escrow/v1/deals/{deal_id}/refund", json={})

    async def dispute_escrow(self, deal_id: str, disputed_by: str, reason: str = "") -> dict:
        """Mark deal as disputed."""
        return await self._request("POST", f"/escrow/v1/deals/{deal_id}/dispute", json={
            "disputed_by": disputed_by,
            "reason": reason,
        })

    async def resolve_escrow(
        self, deal_id: str, outcome: str, attestations: list[dict]
    ) -> dict:
        """Resolve disputed deal via oracle attestations."""
        return await self._request("POST", f"/escrow/v1/deals/{deal_id}/resolve", json={
            "outcome": outcome,
            "attestations": attestations,
        })
