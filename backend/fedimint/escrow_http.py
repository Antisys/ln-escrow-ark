"""
Fedimint Escrow HTTP Client
============================
Wraps the escrow-httpd REST API as async calls.

This replaces CLI subprocess invocations with HTTP requests to a persistent
daemon, eliminating ~13s cold-start overhead per operation.

Configuration:
  ESCROW_HTTPD_URL   Base URL of the escrow-httpd service (default: http://127.0.0.1:5400)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

from backend.fedimint.escrow_client import (
    EscrowClientError,
    EscrowInfo,
    EscrowNotFoundError,
    EscrowStateError,
)

logger = logging.getLogger(__name__)

HTTPD_URL = os.environ.get("ESCROW_HTTPD_URL", "http://127.0.0.1:5400")

# Timeouts match CLI subprocess timeouts
_QUICK_TIMEOUT = 30.0
_LONG_TIMEOUT = 180.0
_FUNDING_TIMEOUT = 65.0


class EscrowHttpClient:
    """HTTP client for escrow-httpd, drop-in replacement for EscrowClient."""

    def __init__(self, base_url: str = None):
        self.base_url = (base_url or HTTPD_URL).rstrip("/")

    async def _request(self, method: str, path: str, timeout: float = _QUICK_TIMEOUT, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(method, url, **kwargs)
                if resp.status_code >= 400:
                    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    error_msg = body.get("error", resp.text)
                    if "not found" in error_msg.lower() or "EscrowNotFound" in error_msg:
                        raise EscrowNotFoundError(error_msg)
                    if "invalid state" in error_msg.lower():
                        raise EscrowStateError(error_msg)
                    raise EscrowClientError(error_msg)
                return resp.json()
        except httpx.TimeoutException:
            raise EscrowClientError(f"HTTP request timed out: {method} {path}")
        except httpx.ConnectError:
            raise EscrowClientError(f"Cannot connect to escrow-httpd at {self.base_url}")

    # ── Read-only queries ───────────────────────────────────────────

    async def get_info(self) -> dict:
        return await self._request("GET", "/info")

    async def get_public_key(self) -> str:
        result = await self._request("GET", "/escrow/public-key")
        return result.get("public_key", "")

    async def get_escrow_info(self, escrow_id: str) -> EscrowInfo:
        data = await self._request("GET", f"/escrow/{escrow_id}/info")
        return EscrowInfo(
            escrow_id=escrow_id,
            buyer_pubkey=data.get("buyer_pubkey", ""),
            seller_pubkey=data.get("seller_pubkey", ""),
            oracle_pubkeys=data.get("oracle_pubkeys", []),
            amount=data.get("amount", {}),
            state=data.get("state", ""),
            timeout_block=data.get("timeout_block", 0),
            timeout_action=data.get("timeout_action", ""),
        )

    async def get_current_block_height(self) -> int:
        result = await self._request("GET", "/block-height")
        if isinstance(result, int):
            return result
        return int(result)

    # ── Funding ─────────────────────────────────────────────────────

    async def receive_into_escrow(
        self,
        seller_pubkey: str,
        oracle_pubkeys: list[str],
        amount_sats: int,
        secret_code_hash: str,
        timeout_block: int,
        timeout_action: str = "refund",
        gateway_id: str = None,
        buyer_pubkey: str = None,
        description: str = None,
    ) -> dict:
        body = {
            "seller_pubkey": seller_pubkey,
            "oracle_pubkeys": oracle_pubkeys,
            "amount_msats": amount_sats * 1000,
            "timeout_block": timeout_block,
            "timeout_action": timeout_action,
            "secret_code_hash": secret_code_hash,
        }
        if gateway_id:
            body["gateway_id"] = gateway_id
        if buyer_pubkey:
            body["buyer_pubkey"] = buyer_pubkey
        if description:
            body["description"] = description
        return await self._request("POST", "/escrow/receive-into-escrow",
                                   json=body, timeout=_FUNDING_TIMEOUT)

    async def await_receive_into_escrow(
        self,
        operation_id: str,
        escrow_id: str,
        seller_pubkey: str,
        oracle_pubkeys: list[str],
        amount_sats: int,
        secret_code_hash: str,
        timeout_block: int,
        timeout_action: str = "refund",
        poll_timeout_secs: int = 5,
        buyer_pubkey: str = None,
    ) -> dict:
        body = {
            "operation_id": operation_id,
            "escrow_id": escrow_id,
            "seller_pubkey": seller_pubkey,
            "oracle_pubkeys": oracle_pubkeys,
            "amount_msats": amount_sats * 1000,
            "timeout_block": timeout_block,
            "timeout_action": timeout_action,
            "secret_code_hash": secret_code_hash,
            "timeout_secs": poll_timeout_secs,
        }
        if buyer_pubkey:
            body["buyer_pubkey"] = buyer_pubkey
        return await self._request("POST", "/escrow/await-receive",
                                   json=body, timeout=poll_timeout_secs + 15)

    async def check_ln_invoice_paid(self, operation_id: str, timeout_secs: int = 2) -> bool:
        result = await self._request("POST", "/escrow/await-invoice",
                                     json={"operation_id": operation_id, "timeout_secs": timeout_secs},
                                     timeout=timeout_secs + 5)
        return result.get("status") == "paid"

    # ── Non-custodial (delegated) operations ────────────────────────

    async def claim_delegated_and_pay(
        self,
        escrow_id: str,
        secret_code: str,
        signature_hex: str,
        bolt11: str,
    ) -> dict:
        return await self._request("POST", "/escrow/claim-delegated-and-pay",
                                   json={
                                       "escrow_id": escrow_id,
                                       "secret_code": secret_code,
                                       "signature": signature_hex,
                                       "bolt11": bolt11,
                                   }, timeout=_LONG_TIMEOUT)

    async def claim_timeout_delegated_and_pay(
        self,
        escrow_id: str,
        signature_hex: str,
        bolt11: str,
    ) -> dict:
        return await self._request("POST", "/escrow/claim-timeout-delegated-and-pay",
                                   json={
                                       "escrow_id": escrow_id,
                                       "signature": signature_hex,
                                       "bolt11": bolt11,
                                   }, timeout=_LONG_TIMEOUT)

    async def dispute_delegated(
        self,
        escrow_id: str,
        disputer_pubkey: str,
        signature_hex: str,
    ) -> dict:
        return await self._request("POST", "/escrow/dispute-delegated",
                                   json={
                                       "escrow_id": escrow_id,
                                       "disputer_pubkey": disputer_pubkey,
                                       "signature": signature_hex,
                                   }, timeout=_LONG_TIMEOUT)

    # ── Oracle resolution ───────────────────────────────────────────

    async def resolve_via_oracle(self, escrow_id: str, attestations: list[dict]) -> dict:
        return await self._request("POST", "/escrow/resolve-oracle",
                                   json={
                                       "escrow_id": escrow_id,
                                       "attestations": attestations,
                                   }, timeout=_LONG_TIMEOUT)

    async def resolve_oracle_and_pay(self, escrow_id: str, attestations: list[dict], bolt11: str) -> dict:
        return await self._request("POST", "/escrow/resolve-oracle-and-pay",
                                   json={
                                       "escrow_id": escrow_id,
                                       "attestations": attestations,
                                       "bolt11": bolt11,
                                   }, timeout=_LONG_TIMEOUT)

    # ── Legacy (custodial) operations ───────────────────────────────

    async def claim_and_pay(self, escrow_id: str, secret_code: str, bolt11: str) -> dict:
        return await self._request("POST", "/escrow/claim-and-pay",
                                   json={
                                       "escrow_id": escrow_id,
                                       "secret_code": secret_code,
                                       "bolt11": bolt11,
                                   }, timeout=_LONG_TIMEOUT)

    async def claim_timeout_and_pay(self, escrow_id: str, bolt11: str) -> dict:
        return await self._request("POST", "/escrow/claim-timeout-and-pay",
                                   json={
                                       "escrow_id": escrow_id,
                                       "bolt11": bolt11,
                                   }, timeout=_LONG_TIMEOUT)

