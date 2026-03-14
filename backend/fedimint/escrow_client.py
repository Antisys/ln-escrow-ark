"""
Fedimint Escrow Client Bridge
==============================
Wraps fedimint-cli module escrow <command> as async subprocess calls.

All public functions are async. Errors raise EscrowClientError.

Configuration (via environment variables):
  FEDIMINT_CLI_PATH   Path to the fedimint-cli binary (default: "fedimint-cli")
  FEDIMINT_DATA_DIR   Client data directory passed as --data-dir (default: ~/.config/fedimint-client)
  FEDIMINT_PASSWORD   Client password passed as --password (optional)

Typical usage:
    from backend.fedimint.escrow_client import EscrowClient

    client = EscrowClient()
    result = await client.create_escrow(
        seller_pubkey="02abcd...",
        oracle_pubkeys=["02aa...", "02bb...", "02cc..."],
        amount_sats=100_000,
        secret_code_hash="sha256hexhere...",
        timeout_block=900_000,
        timeout_action="refund",
    )
    print(result.escrow_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EscrowClientError(Exception):
    """Raised when a fedimint-cli call fails."""
    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


class EscrowNotFoundError(EscrowClientError):
    pass


class EscrowStateError(EscrowClientError):
    """Raised when the escrow is in the wrong state for the requested operation."""
    pass


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CreateEscrowResult:
    escrow_id: str


@dataclass
class EscrowInfo:
    escrow_id: str
    buyer_pubkey: str
    seller_pubkey: str
    oracle_pubkeys: list[str]
    amount: dict          # Fedimint Amount object {"msats": N}
    state: str
    timeout_block: int
    timeout_action: str


@dataclass
class SignedAttestation:
    """A single oracle attestation, matching the format of oracle_sign.py output."""
    pubkey: str
    signature: str
    content: dict         # {escrow_id, outcome, decided_at, reason?}


# ---------------------------------------------------------------------------
# Global serialization lock
# ---------------------------------------------------------------------------

# fedimint-cli uses a RocksDB client database that only allows one writer at a
# time. Concurrent invocations block on the DB lock and eventually time out.
# This asyncio lock ensures we never run more than one fedimint-cli subprocess
# against the same data-dir simultaneously, eliminating all DB lock contention.
_CLI_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# Shared subprocess helper
# ---------------------------------------------------------------------------

async def _run_cli_subprocess(
    cli_cmd: list[str],
    ssh_host: str | None,
    timeout_secs: int = 30,
    label: str = "cli",
) -> tuple[int, str, str]:
    """
    Run a CLI command locally or via SSH. Returns (returncode, stdout, stderr).
    Raises EscrowClientError on timeout.
    """
    if ssh_host:
        remote_cmd = " ".join(shlex.quote(arg) for arg in cli_cmd)
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            ssh_host,
            remote_cmd,
        ]
    else:
        cmd = cli_cmd

    logger.debug("%s: %s", label, " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_secs)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise EscrowClientError(f"{label} timed out after {timeout_secs}s")

    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


def _parse_cli_json(stdout_str: str, stderr_str: str, label: str) -> dict:
    """Parse JSON from CLI stdout, raising EscrowClientError on failure."""
    if not stdout_str:
        return {}
    try:
        return json.loads(stdout_str)
    except json.JSONDecodeError as e:
        raise EscrowClientError(
            f"{label} returned non-JSON output: {stdout_str!r}",
            stderr=stderr_str,
        ) from e


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class EscrowClient:
    """
    Async wrapper around `fedimint-cli module escrow`.

    All methods raise EscrowClientError on failure.
    """

    def __init__(
        self,
        cli_path: Optional[str] = None,
        data_dir: Optional[str] = None,
        password: Optional[str] = None,
        ssh_host: Optional[str] = None,
    ):
        self.cli_path = cli_path or os.environ.get("FEDIMINT_CLI_PATH", "fedimint-cli")
        self.data_dir = data_dir or os.environ.get("FEDIMINT_DATA_DIR")
        self.password = password or os.environ.get("FEDIMINT_PASSWORD")
        # If set, fedimint-cli is invoked via SSH on this host (e.g. "user@remote-host")
        # The cli_path and data_dir are paths on the remote host.
        self.ssh_host = ssh_host or os.environ.get("FEDIMINT_SSH_HOST")

    # ------------------------------------------------------------------
    # Low-level subprocess helper
    # ------------------------------------------------------------------

    def _build_base_cmd(self) -> list[str]:
        """Build the fedimint-cli command prefix with --data-dir and --password flags."""
        cmd = [self.cli_path]
        if self.data_dir:
            cmd += ["--data-dir", self.data_dir]
        if self.password:
            cmd += ["--password", self.password]
        return cmd

    async def _run(self, *args: str, timeout_secs: int = 30) -> dict:
        """
        Run: fedimint-cli [--data-dir ...] [--password ...] <args...>
        If FEDIMINT_SSH_HOST is set, runs via: ssh <host> <cli_path> ...
        Returns parsed JSON stdout on success.
        Raises EscrowClientError on non-zero exit or JSON parse failure.

        Serialized via _CLI_LOCK to prevent RocksDB lock contention when
        multiple concurrent requests try to access the same client data-dir.
        """
        cli_cmd = self._build_base_cmd() + list(args)

        async with _CLI_LOCK:
            returncode, stdout_str, stderr_str = await _run_cli_subprocess(
                cli_cmd, self.ssh_host, timeout_secs=timeout_secs, label="fedimint-cli",
            )

        if returncode != 0:
            logger.error("fedimint-cli failed (rc=%d): %s", returncode, stderr_str)
            if "EscrowNotFound" in stderr_str or "escrow not found" in stderr_str.lower():
                raise EscrowNotFoundError("Escrow not found", stderr=stderr_str)
            if "EscrowDisputed" in stderr_str:
                raise EscrowStateError("Escrow is disputed", stderr=stderr_str)
            if "InvalidStateFor" in stderr_str:
                raise EscrowStateError(f"Invalid escrow state: {stderr_str}", stderr=stderr_str)
            raise EscrowClientError(
                f"fedimint-cli {' '.join(args[:3])} failed (rc={returncode}): {stderr_str}",
                stderr=stderr_str,
            )

        return _parse_cli_json(stdout_str, stderr_str, "fedimint-cli")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_current_block_height(self) -> int:
        """Return the federation's consensus block height."""
        data = await self._run("module", "wallet", "get-consensus-block-count")
        # The command returns a bare integer (JSON-parsed to int)
        if isinstance(data, int):
            return data
        if isinstance(data, dict):
            return int(data.get("count", data.get("block_count", 0)))
        raise EscrowClientError(f"Unexpected block count response: {data!r}")

    async def create_escrow(
        self,
        seller_pubkey: str,
        oracle_pubkeys: list[str],
        amount_sats: int,
        secret_code_hash: str,
        timeout_block: int,
        timeout_action: str = "refund",
    ) -> CreateEscrowResult:
        """
        Lock funds in a new escrow.

        The secret_code_hash is generated by the buyer's browser (SHA-256 of a random
        secret). The service never sees the plaintext secret — only the hash is sent
        to the Fedimint federation.

        Args:
            seller_pubkey:    Seller's secp256k1 pubkey (hex, compressed)
            oracle_pubkeys:   Exactly 3 oracle pubkeys (hex, compressed)
            amount_sats:      Escrow amount in satoshis
            secret_code_hash: SHA-256 hash of buyer's secret (hex, 64 chars)
            timeout_block:    Bitcoin block height after which timeout escape is available
            timeout_action:   "refund" (buyer reclaims) or "release" (seller claims) on timeout

        Returns:
            CreateEscrowResult with escrow_id
        """
        if len(oracle_pubkeys) != 3:
            raise EscrowClientError("oracle_pubkeys must contain exactly 3 pubkeys")

        # Amount in msats (plain integer, no "msat" suffix)
        amount_str = str(amount_sats * 1000)

        data = await self._run(
            "module", "escrow", "create",
            seller_pubkey,
            oracle_pubkeys[0],
            oracle_pubkeys[1],
            oracle_pubkeys[2],
            amount_str,
            str(timeout_block),
            timeout_action,
            "--secret-code-hash", secret_code_hash,
        )

        if "escrow-id" not in data:
            raise EscrowClientError(
                f"fedimint-cli create response missing 'escrow-id'. Got: {list(data)}"
            )
        return CreateEscrowResult(escrow_id=data["escrow-id"])

    async def get_escrow_info(self, escrow_id: str) -> EscrowInfo:
        """
        Fetch current escrow state from the federation.

        Raises EscrowNotFoundError if the escrow_id is unknown.
        """
        data = await self._run("module", "escrow", "info", escrow_id)

        required = ("buyer_pubkey", "seller_pubkey", "amount", "state", "timeout_block", "timeout_action")
        missing = [k for k in required if k not in data]
        if missing:
            raise EscrowClientError(
                f"fedimint-cli info response missing fields: {missing}. Got: {list(data)}"
            )
        return EscrowInfo(
            escrow_id=escrow_id,
            buyer_pubkey=data["buyer_pubkey"],
            seller_pubkey=data["seller_pubkey"],
            oracle_pubkeys=data.get("oracle_pubkeys", []),
            amount=data["amount"],
            state=data["state"],
            timeout_block=data["timeout_block"],
            timeout_action=data["timeout_action"],
        )

    async def claim_escrow(self, escrow_id: str, secret_code: str) -> None:
        """
        Cooperative release: seller claims funds using the secret code.

        Only valid when escrow is in Open state.
        Raises EscrowStateError if disputed or already resolved.
        """
        await self._run("module", "escrow", "claim", escrow_id, secret_code)

    async def initiate_dispute(self, escrow_id: str) -> None:
        """
        Raise a dispute on an escrow (buyer or seller).

        Transitions escrow to DisputedByBuyer or DisputedBySeller.
        """
        await self._run("module", "escrow", "dispute", escrow_id)

    async def resolve_via_oracle(
        self,
        escrow_id: str,
        attestations: list[SignedAttestation],
    ) -> None:
        """
        Resolve a disputed escrow using 2-of-3 oracle attestations.

        Attestations should be collected from oracle_sign.py or the Nostr oracle listener.
        The federation verifies the threshold and pays the winner.

        Args:
            escrow_id:     The disputed escrow to resolve
            attestations:  At least 2 agreeing SignedAttestation objects
        """
        if len(attestations) < 2:
            raise EscrowClientError(
                f"Need at least 2 attestations, got {len(attestations)}"
            )

        # Serialise to the JSON format expected by the CLI resolve-oracle command
        attestations_json = json.dumps([
            {
                "pubkey": a.pubkey,
                "signature": a.signature,
                "content": a.content,
            }
            for a in attestations
        ])

        await self._run(
            "module", "escrow", "resolve-oracle",
            escrow_id,
            attestations_json,
        )

    async def claim_timeout(self, escrow_id: str) -> None:
        """
        Claim escrow funds after the timelock has expired.

        The caller's key must match the authorized party for the configured
        timeout_action (buyer for "refund", seller for "release").
        """
        await self._run("module", "escrow", "claim-timeout", escrow_id)

    async def claim_and_pay(
        self, escrow_id: str, secret_code: str, bolt11: str
    ) -> dict:
        """
        Cooperative claim + immediate LN pay in one CLI call.

        Eliminates Window ②: escrow e-cash never sits in the service wallet.
        The federation claims the escrow and pays the invoice atomically.

        Returns dict with {escrow_id, payment: {status, preimage, operation_id}}.
        Raises EscrowClientError if claim or payment fails.
        """
        data = await self._run(
            "module", "escrow", "claim-and-pay",
            escrow_id, secret_code, bolt11,
            timeout_secs=90,
        )
        if data.get("payment", {}).get("status") != "success":
            raise EscrowClientError(
                f"claim-and-pay payment did not succeed: {data}",
            )
        return data

    async def claim_timeout_and_pay(self, escrow_id: str, bolt11: str) -> dict:
        """
        Timeout claim + immediate LN pay in one CLI call.

        For refund path: e-cash never sits in the service wallet.
        The federation claims via timeout and pays the invoice atomically.

        Returns dict with {escrow_id, payment: {status, preimage, operation_id}}.
        Raises EscrowClientError if claim or payment fails.
        """
        data = await self._run(
            "module", "escrow", "claim-timeout-and-pay",
            escrow_id, bolt11,
            timeout_secs=90,
        )
        if data.get("payment", {}).get("status") != "success":
            raise EscrowClientError(
                f"claim-timeout-and-pay payment did not succeed: {data}",
            )
        return data

    async def receive_into_escrow(
        self,
        seller_pubkey: str,
        oracle_pubkeys: list[str],
        amount_sats: int,
        secret_code_hash: str,
        timeout_block: int,
        timeout_action: str = "refund",
        gateway_id: str | None = None,
        buyer_pubkey: str | None = None,
    ) -> dict:
        """
        Create a LN receive invoice that auto-creates a Fedimint escrow when paid.

        Eliminates Window ①: instead of two separate Python calls (create-invoice,
        then create-escrow), this single CLI call creates the invoice and, when the
        buyer pays it, `await_receive_into_escrow()` atomically creates the escrow.

        Args:
            seller_pubkey:    Seller's secp256k1 pubkey (hex, compressed) — in practice
                              the service's own pubkey so it can claim the escrow.
            oracle_pubkeys:   Exactly 3 oracle pubkeys (hex, compressed).
            amount_sats:      Escrow amount in satoshis.
            secret_code_hash: SHA-256 hash of buyer's secret (hex, 64 chars).
            timeout_block:    Bitcoin block height after which timeout escape is available.
            timeout_action:   "refund" (buyer reclaims) or "release" (seller claims) on timeout.
            gateway_id:       Optional gateway pubkey (hex) to use for invoice creation.
                              Skips auto-selection, much faster.

        Returns:
            dict with {bolt11, escrow_id, operation_id}.
            Store escrow_id and operation_id — pass them to await_receive_into_escrow().
        """
        if len(oracle_pubkeys) != 3:
            raise EscrowClientError("oracle_pubkeys must contain exactly 3 pubkeys")

        amount_str = str(amount_sats * 1000)  # CLI expects msats

        extra_args = []
        if gateway_id:
            extra_args += ["--gateway-id", gateway_id]
        if buyer_pubkey:
            extra_args += ["--buyer-pubkey", buyer_pubkey]

        data = await self._run(
            "module", "escrow", "receive-into-escrow",
            seller_pubkey,
            oracle_pubkeys[0],
            oracle_pubkeys[1],
            oracle_pubkeys[2],
            amount_str,
            str(timeout_block),
            timeout_action,
            "--secret-code-hash", secret_code_hash,
            *extra_args,
            timeout_secs=60,
        )

        required = ("bolt11", "escrow_id", "operation_id")
        missing = [k for k in required if not data.get(k)]
        if missing:
            raise EscrowClientError(
                f"receive-into-escrow response missing fields: {missing}. Got: {list(data)}"
            )
        return data

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
        buyer_pubkey: str | None = None,
    ) -> dict:
        """
        Poll the LN receive operation. If buyer paid, atomically create the Fedimint escrow.

        Idempotent: if the escrow already exists, returns {status: "funded"} immediately.
        Call this repeatedly until status is "funded" or "failed".

        Args:
            operation_id:       LN operation ID from receive_into_escrow().
            escrow_id:          Escrow ID from receive_into_escrow().
            seller_pubkey:      Same as passed to receive_into_escrow().
            oracle_pubkeys:     Same as passed to receive_into_escrow().
            amount_sats:        Same as passed to receive_into_escrow().
            secret_code_hash:   Same as passed to receive_into_escrow().
            timeout_block:      Same as passed to receive_into_escrow().
            timeout_action:     Same as passed to receive_into_escrow().
            poll_timeout_secs:  How long to wait per poll call (default 5s).

        Returns:
            dict with {status: "awaiting"|"funded"|"failed", escrow_id, reason?}.
        """
        if len(oracle_pubkeys) != 3:
            raise EscrowClientError("oracle_pubkeys must contain exactly 3 pubkeys")

        amount_str = str(amount_sats * 1000)

        extra_args = []
        if buyer_pubkey:
            extra_args += ["--buyer-pubkey", buyer_pubkey]

        data = await self._run(
            "module", "escrow", "await-receive-into-escrow",
            operation_id,
            escrow_id,
            seller_pubkey,
            oracle_pubkeys[0],
            oracle_pubkeys[1],
            oracle_pubkeys[2],
            amount_str,
            str(timeout_block),
            timeout_action,
            "--secret-code-hash", secret_code_hash,
            "--timeout", str(poll_timeout_secs),
            *extra_args,
            timeout_secs=poll_timeout_secs + 15,  # subprocess timeout > poll timeout
        )

        if "status" not in data:
            raise EscrowClientError(
                f"await-receive-into-escrow response missing 'status'. Got: {list(data)}"
            )
        return data

    # ------------------------------------------------------------------
    # Delegated operations (user signs externally, service submits)
    # ------------------------------------------------------------------

    async def claim_delegated_and_pay(
        self, escrow_id: str, secret_code: str, signature_hex: str, bolt11: str
    ) -> dict:
        """
        Delegated cooperative claim + LN pay in one CLI call.

        The buyer's external Schnorr signature (over SHA256(secret_code)) proves consent.
        Service submits the transaction and receives e-cash for immediate LN payout.
        """
        data = await self._run(
            "module", "escrow", "claim-delegated-and-pay",
            escrow_id, secret_code, signature_hex, bolt11,
            timeout_secs=90,
        )
        if data.get("payment", {}).get("status") != "success":
            raise EscrowClientError(
                f"claim-delegated-and-pay payment did not succeed: {data}",
            )
        return data

    async def claim_timeout_delegated_and_pay(
        self, escrow_id: str, signature_hex: str, bolt11: str
    ) -> dict:
        """
        Delegated timeout claim + LN pay in one CLI call.

        The authorized party's pre-signed Schnorr signature (over SHA256("timeout"))
        proves consent. Stored at funding time, used when timeout fires.
        """
        data = await self._run(
            "module", "escrow", "claim-timeout-delegated-and-pay",
            escrow_id, signature_hex, bolt11,
            timeout_secs=90,
        )
        if data.get("payment", {}).get("status") != "success":
            raise EscrowClientError(
                f"claim-timeout-delegated-and-pay payment did not succeed: {data}",
            )
        return data

    async def dispute_delegated(
        self, escrow_id: str, disputer_pubkey: str, signature_hex: str
    ) -> None:
        """
        Delegated dispute: user signed externally, service submits.

        The disputer's Schnorr signature (over SHA256("dispute")) proves identity.
        """
        await self._run(
            "module", "escrow", "dispute-delegated",
            escrow_id, disputer_pubkey, signature_hex,
        )

    async def resolve_oracle_and_pay(
        self,
        escrow_id: str,
        attestations: list[SignedAttestation],
        bolt11: str,
    ) -> dict:
        """
        Resolve a disputed escrow via oracle attestations, then pay via Lightning.

        Two-step CLI flow (no standalone ln-pay exposed):
          1. resolve-oracle → e-cash lands in service wallet
          2. ln pay → pays the winner's BOLT11 invoice
        """
        await self.resolve_via_oracle(escrow_id, attestations)
        data = await self._run(
            "module", "ln", "pay", bolt11,
            timeout_secs=90,
        )
        if isinstance(data, dict) and data.get("Failure"):
            raise EscrowClientError(
                f"LN payment failed: {data['Failure']}",
            )
        return data

    async def get_info(self) -> dict:
        """Get federation client info including wallet balance."""
        return await self._run("info")

    async def get_public_key(self) -> str:
        """Return the client's secp256k1 public key (hex)."""
        data = await self._run("module", "escrow", "public-key")
        if "public_key" not in data:
            raise EscrowClientError(
                f"fedimint-cli public-key response missing 'public_key' field. Got: {list(data)}"
            )
        return data["public_key"]

    async def check_ln_invoice_paid(self, operation_id: str, timeout_secs: int = 2) -> bool:
        """
        Non-blocking check: has the LN receive invoice been paid and e-cash credited?

        Runs `fedimint-cli await-invoice <operation_id>` with a short timeout.
        Returns True if paid (e-cash confirmed in wallet), False if not yet paid.

        Serialized via _CLI_LOCK to prevent RocksDB lock contention.
        """
        if not operation_id:
            return False

        cli_cmd = self._build_base_cmd() + ["await-invoice", operation_id]

        try:
            async with _CLI_LOCK:
                returncode, _, _ = await _run_cli_subprocess(
                    cli_cmd, self.ssh_host,
                    timeout_secs=timeout_secs,
                    label="await-invoice",
                )
        except EscrowClientError:
            # Timeout — not yet paid
            return False

        # exit code 0 = paid, non-zero = not yet paid or error
        return returncode == 0

