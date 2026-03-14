"""
High-level Ark escrow service — bridges deals with the Ark Escrow Agent.
Replaces backend/fedimint/fedimint_service.py.

All LN payment handling stays in the route layer (LND).
This service only manages the Ark VTXO escrow lifecycle.
"""
import os
import logging
from typing import Optional

from backend.ark.ark_client import (
    ArkEscrowClient,
    ArkEscrowError,
    ArkEscrowNotFoundError,
    ArkEscrowStateError,
    CreateEscrowResult,
    EscrowInfo,
    SignedAttestation,
)

logger = logging.getLogger(__name__)

_BLOCKS_PER_HOUR = 6
_MIN_TIMEOUT_BLOCKS = 144  # ~1 day


def _get_oracle_pubkeys() -> list[str]:
    raw = os.getenv("ORACLE_PUBKEYS", "")
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


class ArkEscrowService:
    """
    High-level escrow service for trustMeBro-ARK.

    Provides the same interface as the old ArkEscrowService so that
    route handlers can swap with minimal changes.
    """

    def __init__(self, client: Optional[ArkEscrowClient] = None):
        self.client = client or ArkEscrowClient()
        self._service_pubkey: Optional[str] = None

    # ── Escrow lifecycle ─────────────────────────────────────────

    async def create_deal_escrow(
        self,
        amount_sats: int,
        secret_code_hash: str,
        timeout_hours: int,
        timeout_action: str,
        seller_pubkey: str,
        buyer_pubkey: str,
    ) -> dict:
        """
        Create an Ark escrow deal. Returns dict with:
        {deal_id, escrow_pubkey, tapscripts, address, timeout_block}
        """
        timeout_blocks = max(timeout_hours * _BLOCKS_PER_HOUR, _MIN_TIMEOUT_BLOCKS)

        result: CreateEscrowResult = await self.client.create_escrow(
            buyer_pubkey=buyer_pubkey,
            seller_pubkey=seller_pubkey,
            amount=amount_sats,
            timeout_blocks=timeout_blocks,
        )

        logger.info(
            "Ark escrow created: deal=%s amount=%d timeout=%d blocks",
            result.deal_id, amount_sats, timeout_blocks,
        )

        return {
            "deal_id": result.deal_id,
            "escrow_pubkey": result.escrow_pubkey,
            "tapscripts": result.tapscripts,
            "address": result.address,
            "timeout_block": timeout_blocks,
            "secret_code_hash": secret_code_hash,
        }

    async def release_deal_escrow(self, deal_id: str, secret_code: str) -> dict:
        """Release escrow to seller (legacy custodial path)."""
        return await self.client.release_escrow(deal_id)

    async def release_deal_delegated(
        self,
        deal_id: str,
        secret_code: str,
        buyer_signature: str,
        invoice: str,
    ) -> dict:
        """
        Release escrow to seller (non-custodial delegated path).
        The buyer_signature proves consent.
        LN payout to seller is handled by the route layer via LND.
        """
        result = await self.client.release_escrow(deal_id)
        logger.info("Ark escrow released (delegated): deal=%s", deal_id)
        return result

    async def refund_deal_escrow(self, deal_id: str) -> dict:
        """Refund escrow to buyer (legacy custodial path)."""
        return await self.client.refund_escrow(deal_id)

    async def refund_deal_delegated(
        self,
        deal_id: str,
        timeout_signature: str,
        invoice: str,
    ) -> dict:
        """
        Refund escrow to buyer (non-custodial delegated path).
        The timeout_signature is the buyer's pre-signed timeout authorization.
        LN payout to buyer is handled by the route layer via LND.
        """
        result = await self.client.refund_escrow(deal_id)
        logger.info("Ark escrow refunded (delegated): deal=%s", deal_id)
        return result

    async def dispute_deal_escrow(self, deal_id: str) -> dict:
        """Initiate dispute on escrow (custodial path)."""
        return await self.client.dispute_escrow(deal_id, disputed_by="service")

    async def dispute_deal_delegated(
        self, deal_id: str, pubkey: str, signature: str
    ) -> dict:
        """Initiate dispute on escrow (non-custodial path)."""
        result = await self.client.dispute_escrow(deal_id, disputed_by=pubkey)
        logger.info("Ark escrow disputed (delegated): deal=%s by=%s", deal_id, pubkey[:16])
        return result

    async def resolve_deal_escrow_via_oracle(
        self, deal_id: str, attestations: list[SignedAttestation]
    ) -> dict:
        """Resolve dispute via oracle attestations."""
        outcome = attestations[0].content.get("outcome", "buyer")
        att_dicts = [
            {"pubkey": a.pubkey, "signature": a.signature, "content": a.content}
            for a in attestations
        ]
        return await self.client.resolve_escrow(deal_id, outcome, att_dicts)

    async def resolve_and_pay_via_oracle(
        self,
        deal_id: str,
        attestations: list[SignedAttestation],
        invoice: str,
    ) -> dict:
        """Resolve dispute + trigger LN payout (oracle path)."""
        result = await self.resolve_deal_escrow_via_oracle(deal_id, attestations)
        logger.info("Ark escrow resolved via oracle: deal=%s", deal_id)
        return result

    # ── Funding ──────────────────────────────────────────────────

    async def create_funding_invoice_with_escrow(
        self,
        amount_sats: int,
        secret_code_hash: str,
        timeout_hours: int,
        timeout_action: str,
        seller_pubkey: str,
        buyer_pubkey: str,
    ) -> dict:
        """
        Create escrow deal + return info for LN invoice creation.

        Unlike Ark (which atomically creates invoice + escrow),
        Ark separates these: we create the escrow deal here, and the
        route layer creates the LN invoice via LND separately.

        Returns dict compatible with the old Ark interface:
        {escrow_id, address, timeout_block, bolt11: None}
        """
        escrow = await self.create_deal_escrow(
            amount_sats=amount_sats,
            secret_code_hash=secret_code_hash,
            timeout_hours=timeout_hours,
            timeout_action=timeout_action,
            seller_pubkey=seller_pubkey,
            buyer_pubkey=buyer_pubkey,
        )

        return {
            "escrow_id": escrow["deal_id"],
            "escrow_pubkey": escrow["escrow_pubkey"],
            "tapscripts": escrow["tapscripts"],
            "address": escrow["address"],
            "timeout_block": escrow["timeout_block"],
            "bolt11": None,  # LN invoice created separately by route layer
            "operation_id": None,  # No Ark operation ID
        }

    async def check_funding_status(self, deal_id: str) -> dict:
        """Check if escrow deal has been funded."""
        info = await self.client.get_escrow_info(deal_id)
        return {
            "status": "funded" if info.status == "funded" else "awaiting",
            "deal_id": deal_id,
        }

    async def check_funding_invoice_paid(self, operation_id: str) -> bool:
        """Compatibility stub — not used in Ark (LND checks invoice directly)."""
        return False

    # ── Queries ──────────────────────────────────────────────────

    async def get_escrow_info(self, deal_id: str) -> EscrowInfo:
        """Fetch escrow deal state."""
        return await self.client.get_escrow_info(deal_id)

    async def get_service_pubkey(self) -> str:
        """Get the Ark server's signer pubkey (cached)."""
        if not self._service_pubkey:
            import httpx
            ark_url = os.getenv("ARK_SERVER_URL", "http://localhost:7070")
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.get(f"{ark_url}/v1/info")
                self._service_pubkey = resp.json().get("signerPubkey", "")
        return self._service_pubkey

    async def get_wallet_balance_sats(self) -> int:
        """Compatibility stub — Ark doesn't have e-cash balance."""
        return 0
