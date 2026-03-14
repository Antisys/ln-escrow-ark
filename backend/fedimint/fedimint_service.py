"""
High-level Fedimint escrow service for deal integration.

Creates and manages Fedimint escrows corresponding to deals.
Uses EscrowClient (subprocess wrapper around fedimint-cli) and OracleListener.

Configuration (environment variables):
  ORACLE_PUBKEYS       Comma-separated hex pubkeys of the 3 registered oracle
                       arbitrators (compressed, 33 bytes = 66 hex chars).
  FEDIMINT_CLI_PATH    Path to fedimint-cli binary (default: fedimint-cli).
  FEDIMINT_DATA_DIR    Federation client data directory.
  FEDIMINT_PASSWORD    Federation client password.

Deal flow:
  1. LN payment arrives  → create_deal_escrow()  → stores escrow_id + secret_code
  2. Buyer releases      → release_deal_escrow()  → claim_escrow with secret_code
  3. Dispute opened      → dispute_deal_escrow()  → initiate_dispute
  4. Oracle resolves     → resolve_deal_escrow_via_oracle()
  5. Timeout expires     → refund_deal_escrow()   → claim_timeout
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from backend.fedimint.escrow_client import (
    EscrowClient,
    CreateEscrowResult,
    EscrowInfo,
    SignedAttestation,
)

logger = logging.getLogger(__name__)

# Bitcoin blocks per hour (average ~6)
_BLOCKS_PER_HOUR = 6
# Minimum timeout to put into the escrow (1 day = 144 blocks)
_MIN_TIMEOUT_BLOCKS = 144


def _get_oracle_pubkeys() -> list[str]:
    """Get the 3 configured oracle pubkeys from ORACLE_PUBKEYS env var."""
    env = os.environ.get("ORACLE_PUBKEYS", "")
    pubkeys = [k.strip() for k in env.split(",") if k.strip()]
    if len(pubkeys) != 3:
        raise ValueError(
            f"ORACLE_PUBKEYS must contain exactly 3 pubkeys (got {len(pubkeys)}). "
            "Set ORACLE_PUBKEYS=pk1,pk2,pk3 in environment."
        )
    return pubkeys


def _timeout_hours_to_block_offset(timeout_hours: int) -> int:
    """Convert timeout hours to a block count offset (min 1 day = 144 blocks)."""
    return max(timeout_hours * _BLOCKS_PER_HOUR, _MIN_TIMEOUT_BLOCKS)


class FedimintEscrowService:
    """
    Service layer bridging the deal management layer with the Fedimint escrow module.

    The service acts as an intermediary:
    - It is the "buyer" in the Fedimint escrow (holds/deposits the e-cash).
    - Cooperative release requires the buyer to submit secret_code from their browser.
    - The actual buyer/seller receive their funds via Lightning Network.

    The Fedimint module provides trustless oracle-mediated dispute resolution:
    even the service cannot resolve a dispute without valid 2-of-3 oracle signatures
    (enforced by the federation guardians).
    """

    # Module-level caches (shared across all instances)
    _cached_pubkey: Optional[str] = None
    _cached_block_height: Optional[int] = None
    _block_height_ts: float = 0.0
    _BLOCK_HEIGHT_TTL = 600  # 10 minutes

    def __init__(self, client=None):
        if client is not None:
            self._client = client
        elif os.environ.get("ESCROW_HTTPD_URL"):
            from backend.fedimint.escrow_http import EscrowHttpClient
            self._client = EscrowHttpClient()
            logger.info("Using escrow-httpd at %s", os.environ["ESCROW_HTTPD_URL"])
        else:
            self._client = EscrowClient()

    @property
    def client(self) -> EscrowClient:
        return self._client

    async def _get_service_pubkey_cached(self) -> str:
        """Get service pubkey, cached permanently (never changes)."""
        if FedimintEscrowService._cached_pubkey is None:
            FedimintEscrowService._cached_pubkey = await self._client.get_public_key()
            logger.info("Cached service pubkey: %s", FedimintEscrowService._cached_pubkey)
        return FedimintEscrowService._cached_pubkey

    async def _get_block_height_cached(self) -> int:
        """Get consensus block height, cached for 10 minutes."""
        now = time.monotonic()
        if (
            FedimintEscrowService._cached_block_height is None
            or now - FedimintEscrowService._block_height_ts > self._BLOCK_HEIGHT_TTL
        ):
            FedimintEscrowService._cached_block_height = await self._client.get_current_block_height()
            FedimintEscrowService._block_height_ts = now
            logger.info("Cached block height: %d", FedimintEscrowService._cached_block_height)
        return FedimintEscrowService._cached_block_height

    # ------------------------------------------------------------------
    # Deal escrow lifecycle
    # ------------------------------------------------------------------

    async def create_deal_escrow(
        self,
        seller_pubkey: str,
        amount_sats: int,
        secret_code_hash: str,
        timeout_hours: int,
        timeout_action: str = "refund",
        oracle_pubkeys: Optional[list[str]] = None,
    ) -> CreateEscrowResult:
        """
        Create a Fedimint escrow for a funded deal.

        Args:
            seller_pubkey:   The pubkey that can claim the escrow (service's own key).
            amount_sats:     Escrow amount in satoshis.
            secret_code_hash: SHA-256 hash of the buyer's secret (generated in browser).
                             The service never sees the plaintext — only this hash.
            timeout_hours:   Deal timeout duration (converted to Bitcoin blocks).
            timeout_action:  What happens on timeout: "refund" (back to buyer) or
                             "release" (to seller). Mirrors the deal's timeout_action.
            oracle_pubkeys:  3 oracle pubkeys. Falls back to ORACLE_PUBKEYS env var.

        Returns:
            CreateEscrowResult(escrow_id).
        """
        pubkeys = oracle_pubkeys or _get_oracle_pubkeys()
        # timeout_block must be an absolute Bitcoin block height, not a relative offset.
        # Query the federation's current consensus block height and add the offset.
        current_height = await self._get_block_height_cached()
        block_offset = _timeout_hours_to_block_offset(timeout_hours)
        timeout_block = current_height + block_offset
        logger.info(
            "Escrow timeout: current_height=%d + offset=%d = timeout_block=%d",
            current_height, block_offset, timeout_block,
        )

        result = await self._client.create_escrow(
            seller_pubkey=seller_pubkey,
            oracle_pubkeys=pubkeys,
            amount_sats=amount_sats,
            secret_code_hash=secret_code_hash,
            timeout_block=timeout_block,
            timeout_action=timeout_action.lower(),
        )
        logger.info(
            "Created Fedimint escrow %s for %d sats "
            "(timeout_block=%d, action=%s)",
            result.escrow_id, amount_sats, timeout_block, timeout_action,
        )
        return result

    async def release_deal_escrow(
        self, escrow_id: str, secret_code: str, bolt11: str
    ) -> dict:
        """
        Cooperative release — claim escrow + pay seller via LN in one call.

        The buyer submits their secret_code (held in browser localStorage).
        The federation verifies it, claims the escrow, and pays the bolt11 invoice.
        Service wallet never holds intermediate e-cash.

        Returns the raw claim-and-pay result dict.
        """
        result = await self._client.claim_and_pay(escrow_id, secret_code, bolt11)
        logger.info("Fedimint escrow %s claimed + LN paid (cooperative release)", escrow_id)
        return result

    async def refund_deal_escrow(self, escrow_id: str, bolt11: str) -> dict:
        """
        Timeout refund — claim escrow after timeout + pay buyer via LN in one call.

        The federation rejects this before the timeout_block height.
        On success, the federation pays the bolt11 invoice directly.
        Service wallet never holds intermediate e-cash.

        Returns the raw claim-timeout-and-pay result dict.
        """
        result = await self._client.claim_timeout_and_pay(escrow_id, bolt11)
        logger.info("Fedimint escrow %s claimed + LN paid (timeout/refund)", escrow_id)
        return result

    async def dispute_deal_escrow(self, escrow_id: str) -> None:
        """
        Initiate dispute on the Fedimint escrow.

        After this call the escrow is in DisputedByBuyer or DisputedBySeller state
        and can only be resolved via oracle attestations.
        """
        await self._client.initiate_dispute(escrow_id)
        logger.info("Dispute initiated for Fedimint escrow %s", escrow_id)

    async def resolve_deal_escrow_via_oracle(
        self, escrow_id: str, attestations: list[SignedAttestation]
    ) -> None:
        """
        Resolve a disputed escrow using 2-of-3 oracle attestations.

        Called by the OracleListener callback when threshold is reached.
        """
        await self._client.resolve_via_oracle(escrow_id, attestations)
        logger.info(
            "Resolved Fedimint escrow %s via oracle (%d attestations)",
            escrow_id, len(attestations),
        )

    async def resolve_and_pay_via_oracle(
        self,
        escrow_id: str,
        attestations: list[SignedAttestation],
        bolt11: str,
    ) -> dict:
        """
        Resolve a disputed escrow via oracle attestations, then pay the winner via LN.

        Single atomic call: resolve-oracle → pay via Lightning.
        No standalone ln_pay endpoint exists — funds can only leave via escrow operations.
        """
        result = await self._client.resolve_oracle_and_pay(escrow_id, attestations, bolt11)
        logger.info("Fedimint escrow %s oracle resolution + LN payment complete", escrow_id)
        return result

    async def get_escrow_info(self, escrow_id: str) -> EscrowInfo:
        """Fetch current escrow state from the federation."""
        return await self._client.get_escrow_info(escrow_id)

    async def get_service_pubkey(self) -> str:
        """Get the service's Fedimint public key."""
        return await self._client.get_public_key()

    async def get_wallet_balance_sats(self) -> int:
        """Get the service's e-cash wallet balance in sats."""
        info = await self._client.get_info()
        total_msat = info.get("total_amount_msat", 0)
        # Handle both plain int and {"msats": N} formats
        if isinstance(total_msat, dict):
            total_msat = total_msat.get("msats", 0)
        return int(total_msat) // 1000

    # ------------------------------------------------------------------
    # LN receive invoice (non-custodial funding path)
    # ------------------------------------------------------------------

    async def create_funding_invoice_with_escrow(
        self,
        amount_sats: int,
        secret_code_hash: str,
        timeout_hours: int,
        timeout_action: str,
        seller_pubkey: str,
        buyer_pubkey: str | None = None,
        description: str | None = None,
    ) -> dict:
        """
        Create a LN receive invoice that atomically creates a Fedimint escrow when paid.

        Eliminates Window ①: no separate create-escrow step needed.
        When the buyer pays the returned bolt11, `check_funding_invoice_paid()` will
        detect payment AND create the escrow atomically in one CLI call.

        Args:
            seller_pubkey: Seller's ephemeral pubkey (from LNURL-auth key derivation).
                           This is the seller's own key, NOT the service's key.

        Returns:
            dict with {bolt11, escrow_id, operation_id}.
            Store escrow_id and operation_id in the deal DB.
        """
        pubkeys = _get_oracle_pubkeys()
        current_height = await self._get_block_height_cached()
        timeout_block = current_height + _timeout_hours_to_block_offset(timeout_hours)

        result = await self._client.receive_into_escrow(
            seller_pubkey=seller_pubkey,
            oracle_pubkeys=pubkeys,
            amount_sats=amount_sats,
            secret_code_hash=secret_code_hash,
            timeout_block=timeout_block,
            timeout_action=timeout_action.lower(),
            gateway_id=os.environ.get("FEDIMINT_GATEWAY_ID"),
            buyer_pubkey=buyer_pubkey,
            description=description,
        )
        logger.info(
            "receive-into-escrow created for %d sats: escrow_id=%s op_id=%s...",
            amount_sats, result["escrow_id"], result["operation_id"][:16],
        )
        result["timeout_block"] = timeout_block
        return result

    async def check_funding_invoice_with_escrow(
        self,
        operation_id: str,
        escrow_id: str,
        amount_sats: int,
        secret_code_hash: str,
        timeout_block: int,
        timeout_action: str,
        seller_pubkey: str,
        poll_timeout_secs: int = 5,
        buyer_pubkey: str | None = None,
    ) -> dict:
        """
        Poll the LN receive operation. If paid, atomically creates the Fedimint escrow.

        Returns dict with {status: "awaiting"|"funded"|"failed", escrow_id, reason?}.
        Call repeatedly until status is "funded" or "failed".
        timeout_block is the exact block height stored at invoice creation — no drift.
        """
        pubkeys = _get_oracle_pubkeys()

        return await self._client.await_receive_into_escrow(
            operation_id=operation_id,
            escrow_id=escrow_id,
            seller_pubkey=seller_pubkey,
            oracle_pubkeys=pubkeys,
            amount_sats=amount_sats,
            secret_code_hash=secret_code_hash,
            timeout_block=timeout_block,
            timeout_action=timeout_action.lower(),
            poll_timeout_secs=poll_timeout_secs,
            buyer_pubkey=buyer_pubkey,
        )

    # ------------------------------------------------------------------
    # Delegated operations (non-custodial: user signs, service submits)
    # ------------------------------------------------------------------

    async def release_deal_delegated(
        self, escrow_id: str, secret_code: str, buyer_signature: str, bolt11: str
    ) -> dict:
        """
        Non-custodial release: buyer's external signature proves consent.

        The buyer signs SHA256(secret_code) with their ephemeral key.
        Service submits the delegated claim and pays seller via LN.
        """
        result = await self._client.claim_delegated_and_pay(
            escrow_id, secret_code, buyer_signature, bolt11,
        )
        logger.info("Fedimint escrow %s claimed + LN paid (delegated release)", escrow_id)
        return result

    async def refund_deal_delegated(
        self, escrow_id: str, timeout_signature: str, bolt11: str
    ) -> dict:
        """
        Non-custodial timeout refund: buyer's pre-signed timeout authorization.

        The buyer pre-signed SHA256("timeout") at funding time. Service uses this
        stored signature to claim after timeout and pay buyer via LN.
        """
        result = await self._client.claim_timeout_delegated_and_pay(
            escrow_id, timeout_signature, bolt11,
        )
        logger.info("Fedimint escrow %s claimed + LN paid (delegated timeout/refund)", escrow_id)
        return result

    async def dispute_deal_delegated(
        self, escrow_id: str, disputer_pubkey: str, dispute_signature: str
    ) -> None:
        """
        Non-custodial dispute: user's external signature proves identity.
        """
        await self._client.dispute_delegated(escrow_id, disputer_pubkey, dispute_signature)
        logger.info("Dispute initiated for Fedimint escrow %s (delegated)", escrow_id)

    async def check_funding_invoice_paid(self, operation_id: str) -> bool:
        """
        Non-blocking check: has the buyer's payment arrived as e-cash in the wallet?

        Uses fedimint-cli await-invoice with a short timeout.
        Returns True only when e-cash is confirmed in the wallet (safe to create escrow).
        """
        return await self._client.check_ln_invoice_paid(operation_id)
