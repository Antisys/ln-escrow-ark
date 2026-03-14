"""
LND REST API Client

Supports:
- Regular invoices (create, check status)
- Invoice payments with preimage retrieval
- Route queries
- Invoice decoding

Uses REST API to avoid gRPC/protobuf compilation complexity.
"""

import asyncio
import base64
import json
import logging
import os
import ssl
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from urllib.parse import urlparse
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


@dataclass
class InvoiceStatus:
    state: str  # OPEN, SETTLED, CANCELED, ACCEPTED
    settled: bool
    preimage: Optional[str] = None
    amt_paid_sat: int = 0


@dataclass
class PaymentResult:
    success: bool
    payment_preimage: Optional[str] = None
    failure_reason: Optional[str] = None
    fee_sat: int = 0


@dataclass
class DecodedInvoice:
    payment_hash: str
    num_satoshis: int
    destination: str
    expiry: int
    description: str


def decode_invoice_local(payment_request: str) -> DecodedInvoice:
    """
    Decode a BOLT11 invoice locally using pyln-proto, without an LND roundtrip.

    Returns the same DecodedInvoice dataclass as LndRestClient.decode_invoice().
    """
    from pyln.proto import Invoice

    inv = Invoice.decode(payment_request)

    amount_sats = int(inv.amount * 10**8) if inv.amount else 0
    pubkey_hex = inv.pubkey.format().hex() if inv.pubkey else ""

    description = ""
    expiry = 3600
    for tag, value in inv.tags:
        if tag == 'd':
            description = value
        elif tag == 'x':
            expiry = value

    return DecodedInvoice(
        payment_hash=inv.paymenthash.hex(),
        num_satoshis=amount_sats,
        destination=pubkey_hex,
        expiry=expiry,
        description=description,
    )


class LndRestClient:
    """
    LND REST API client.

    Connects to LND via REST API (port 8080 by default).
    """

    def __init__(
        self,
        host: str,
        port: int = 8080,
        macaroon_hex: Optional[str] = None,
        macaroon_path: Optional[str] = None,
        tls_cert_path: Optional[str] = None,
        network: str = "mainnet"
    ):
        self.host = host
        self.port = port
        self.base_url = f"https://{host}:{port}"
        self._use_https = True  # May be overridden by from_url()
        self.network = network

        # Load macaroon (hex format required by LND REST API)
        if macaroon_hex:
            self.macaroon = macaroon_hex
        elif macaroon_path:
            with open(macaroon_path, 'r') as f:
                self.macaroon = f.read().strip()
        else:
            raise ValueError("Must provide macaroon_path or macaroon_hex")

        # Setup SSL context
        self.ssl_context = ssl.create_default_context()
        if tls_cert_path:
            self.ssl_context.load_verify_locations(tls_cert_path)
            # Disable hostname check when using SSH tunnel (cert issued for internal hostname)
            self.ssl_context.check_hostname = False
        else:
            # Disable verification if no cert provided (not recommended for production)
            logger.warning("LND TLS verification DISABLED — no tls_cert_path provided. Set LND_TLS_CERT_PATH for production security.")
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        timeout: int = 30
    ) -> dict:
        """Make authenticated request to LND REST API."""
        url = f"{self.base_url}{endpoint}"

        headers = {
            "Grpc-Metadata-macaroon": self.macaroon,
            "Content-Type": "application/json"
        }

        body = json.dumps(data).encode() if data else None

        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method
        )

        try:
            ctx = self.ssl_context if self._use_https else None
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else str(e)
            logger.error("LND API error: %s - %s", e.code, error_body)
            raise Exception(f"LND API error: {e.code} - {error_body}")
        except Exception as e:
            logger.error("LND request failed (%s %s): %s", method, endpoint, e)
            raise

    # ==================== Info ====================

    def get_info(self) -> dict:
        """Get node info."""
        return self._request("GET", "/v1/getinfo")

    # ==================== Regular Invoices ====================

    def add_invoice(self, value: int, memo: str = "", expiry: int = 3600) -> tuple[str, bytes]:
        """
        Create a regular invoice (auto-settles on payment).

        Args:
            value: Amount in satoshis
            memo: Invoice description
            expiry: Expiry time in seconds

        Returns:
            Tuple of (payment_request, payment_hash)
        """
        data = {
            "value": str(value),
            "memo": memo,
            "expiry": str(expiry),
            "private": True,  # Include route hints — required for Tor-only/private nodes
        }

        result = self._request("POST", "/v1/invoices", data)

        payment_hash = base64.b64decode(result["r_hash"])
        return result["payment_request"], payment_hash

    def create_invoice(
        self,
        amount_sats: int,
        description: str = "",
        expiry_seconds: int = 3600
    ) -> dict:
        """
        Create a regular invoice with dict return format.

        Args:
            amount_sats: Amount in satoshis
            description: Invoice description
            expiry_seconds: Expiry time in seconds

        Returns:
            Dict with payment_request and payment_hash_hex
        """
        payment_request, payment_hash = self.add_invoice(
            value=amount_sats,
            memo=description,
            expiry=expiry_seconds
        )
        return {
            "payment_request": payment_request,
            "payment_hash_hex": payment_hash.hex()
        }

    def get_invoice_status(self, payment_hash_hex: str) -> dict:
        """
        Check if an invoice has been paid.

        Args:
            payment_hash_hex: Payment hash as hex string

        Returns:
            Dict with 'paid' boolean and invoice details
        """
        # Use v1 API which accepts hex hash directly
        result = self._request("GET", f"/v1/invoice/{payment_hash_hex}")

        state = result.get("state", "OPEN")
        settled = result.get("settled", False)

        return {
            "paid": settled or state == "SETTLED",
            "state": state,
            "amount_paid_sats": int(result.get("amt_paid_sat", 0)),
            "memo": result.get("memo", "")
        }

    # ==================== Routing ====================

    def query_routes(self, pub_key: str, amt_sat: int) -> bool:
        """
        Check if LND can find a route to the given destination.

        Returns True if at least one route exists, False otherwise.
        Used as a pre-check before attempting payments to avoid wasting
        federation LN contract fees on unrouteable destinations.
        """
        try:
            result = self._request("GET", f"/v1/graph/routes/{pub_key}/{amt_sat}", timeout=10)
            routes = result.get("routes", [])
            return len(routes) > 0
        except Exception as e:
            # If route query fails (e.g. node not in graph), treat as no route
            logger.debug("query_routes failed for %s: %s", pub_key[:16], e)
            return False

    # ==================== Payments ====================

    def decode_invoice(self, payment_request: str) -> DecodedInvoice:
        """
        Decode a BOLT11 payment request.

        Args:
            payment_request: BOLT11 invoice string

        Returns:
            DecodedInvoice with payment details
        """
        result = self._request("GET", f"/v1/payreq/{payment_request}")

        return DecodedInvoice(
            payment_hash=result["payment_hash"],
            num_satoshis=int(result.get("num_satoshis", 0)),
            destination=result["destination"],
            expiry=int(result.get("expiry", 3600)),
            description=result.get("description", "")
        )

    def pay_invoice(
        self,
        payment_request: str,
        timeout_seconds: int = 60,
        fee_limit_sat: int = 1000
    ) -> PaymentResult:
        """
        Pay a BOLT11 invoice and return the preimage.

        Args:
            payment_request: BOLT11 invoice string
            timeout_seconds: Payment timeout
            fee_limit_sat: Maximum fee to pay

        Returns:
            PaymentResult with success status and preimage
        """
        try:
            # Use synchronous payment endpoint (blocks until payment resolves)
            # Note: /v1/channels/transactions does NOT accept timeout_seconds
            # HTTP timeout must be >= payment timeout to avoid orphaned payments
            result = self._request("POST", "/v1/channels/transactions", {
                "payment_request": payment_request,
                "fee_limit": {"fixed": str(fee_limit_sat)}
            }, timeout=max(timeout_seconds + 10, 30))

            if result.get("payment_error"):
                return PaymentResult(
                    success=False,
                    failure_reason=result["payment_error"]
                )

            raw_preimage = result.get("payment_preimage", "")
            if not raw_preimage:
                return PaymentResult(
                    success=False,
                    failure_reason="Empty payment_preimage in response"
                )

            preimage = base64.b64decode(raw_preimage).hex()
            # All-zero preimage means LND returned default/placeholder — not a real payment
            if not preimage or preimage == "0" * 64:
                return PaymentResult(
                    success=False,
                    failure_reason="Zero/invalid preimage — payment did not succeed"
                )

            return PaymentResult(
                success=True,
                payment_preimage=preimage,
                fee_sat=int(result.get("payment_route", {}).get("total_fees", 0))
            )

        except Exception as e:
            return PaymentResult(
                success=False,
                failure_reason=str(e)
            )


# ==================== Factory ====================

def create_lnd_client_from_config(config_path: str = None) -> LndRestClient:
    """
    Create LND client from config file or environment.

    Looks for credentials in:
    1. config_path if provided
    2. data/lnd/ directory
    3. Environment variables

    Note: LND must be reachable at LND_HOST:LND_PORT (default 127.0.0.1:8080).
        Set LND_HOST/LND_PORT env vars or LND_URL if LND is on a remote host.
    """
    base_dir = Path(__file__).parent.parent.parent / "data" / "lnd"

    # Try to load macaroon (hex format)
    macaroon_path = base_dir / "admin.macaroon.hex"
    tls_cert_path = base_dir / "tls.cert"

    macaroon_hex = None
    if macaroon_path.exists():
        with open(macaroon_path, 'r') as f:
            macaroon_hex = f.read().strip()
    elif os.getenv("LND_MACAROON_HEX"):
        macaroon_hex = os.getenv("LND_MACAROON_HEX")

    env_tls_cert = os.getenv("LND_TLS_CERT_PATH")
    if env_tls_cert and Path(env_tls_cert).exists() and Path(env_tls_cert).stat().st_size > 0:
        tls_cert = env_tls_cert
    elif tls_cert_path.exists() and tls_cert_path.stat().st_size > 0:
        tls_cert = str(tls_cert_path)
    else:
        tls_cert = None

    # Parse LND_REST_URL or fall back to LND_HOST/LND_PORT
    rest_url = os.getenv("LND_REST_URL")
    if rest_url:
        # Parse URL like https://127.0.0.1:8080 or http://127.0.0.1:8089
        parsed = urlparse(rest_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8080
        scheme = parsed.scheme or "https"
    else:
        host = os.getenv("LND_HOST", "127.0.0.1")
        port = int(os.getenv("LND_PORT", "8080"))
        scheme = "https"

    client = LndRestClient(
        host=host,
        port=port,
        macaroon_hex=macaroon_hex,
        tls_cert_path=tls_cert
    )
    # Respect the scheme from LND_REST_URL (http vs https)
    client.base_url = f"{scheme}://{host}:{port}"
    client._use_https = (scheme == "https")
    return client


# ==================== Async Wrapper ====================

# Alias for backward compatibility
def get_lnd_client() -> LndRestClient:
    """Get LND client (alias for create_lnd_client_from_config)."""
    return create_lnd_client_from_config()


class AsyncLndClient:
    """
    Async wrapper around LndRestClient for use with asyncio.

    Runs blocking operations in thread pool.
    """

    def __init__(self, sync_client: LndRestClient):
        self.sync = sync_client

    async def get_info(self) -> dict:
        return await asyncio.to_thread(self.sync.get_info)

    async def decode_invoice(self, payment_request: str) -> DecodedInvoice:
        return await asyncio.to_thread(self.sync.decode_invoice, payment_request)

    async def query_routes(self, pub_key: str, amt_sat: int) -> bool:
        return await asyncio.to_thread(self.sync.query_routes, pub_key, amt_sat)

    async def pay_invoice(self, payment_request: str, timeout_seconds: int = 60, fee_limit_sat: int = 1000) -> PaymentResult:
        return await asyncio.to_thread(self.sync.pay_invoice, payment_request, timeout_seconds, fee_limit_sat)
