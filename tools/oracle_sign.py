#!/usr/bin/env python3
"""
Oracle attestation signing for Ark escrow disputes.

Signs a BIP-340 Schnorr attestation in the exact format expected by
the Nostr oracle listener (kind 30001 events).

Usage:
    python tools/oracle_sign.py \
        --privkey <hex> \
        --escrow-id <str> \
        --outcome buyer|seller \
        [--reason "..."]

Can also be imported:
    from tools.oracle_sign import sign_attestation, attestation_signing_bytes
"""

import argparse
import hashlib
import json
import sys
import time

import secp256k1


def attestation_signing_bytes(
    xonly_pubkey_hex: str,
    created_at: int,
    escrow_id: str,
    outcome: str,
) -> bytes:
    """
    Compute the Nostr event ID bytes (pre-image) for an oracle attestation.

    Returns the SHA256 digest of:
        [0, "<xonly_pubkey>", <created_at>, 30001, [["d","<escrow_id>"]], "<outcome>"]

    This is the canonical Nostr event serialization (NIP-01).
    """
    serialized = json.dumps(
        [0, xonly_pubkey_hex, created_at, 30001, [["d", escrow_id]], outcome],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).digest()


def sign_attestation(
    privkey_hex: str,
    escrow_id: str,
    outcome: str,
    reason: str | None = None,
    created_at: int | None = None,
) -> dict:
    """
    Sign an oracle attestation and return the full Nostr event dict.

    Args:
        privkey_hex: 32-byte private key as hex string
        escrow_id:   The escrow being resolved
        outcome:     "buyer" or "seller"
        reason:      Optional human-readable reason
        created_at:  Unix timestamp (defaults to now)

    Returns:
        Dict with keys: id, pubkey, created_at, kind, tags, content, sig
    """
    if outcome not in ("buyer", "seller"):
        raise ValueError(f"outcome must be 'buyer' or 'seller', got {outcome!r}")

    pk = secp256k1.PrivateKey(bytes.fromhex(privkey_hex))
    xonly = pk.pubkey.serialize(compressed=True)[1:].hex()

    if created_at is None:
        created_at = int(time.time())

    # Content: plain outcome string, or JSON with reason if provided
    if reason:
        content = json.dumps({"outcome": outcome, "reason": reason})
    else:
        content = outcome

    # Compute event ID (NIP-01 canonical serialization)
    event_id_bytes = attestation_signing_bytes(xonly, created_at, escrow_id, content)
    event_id = event_id_bytes.hex()

    # BIP-340 Schnorr signature over the raw 32-byte event ID.
    # raw=True bypasses tagged hashing — the event ID is already SHA256.
    sig = pk.schnorr_sign(event_id_bytes, bip340tag="", raw=True)

    return {
        "id": event_id,
        "pubkey": xonly,
        "created_at": created_at,
        "kind": 30001,
        "tags": [["d", escrow_id]],
        "content": content,
        "sig": sig.hex(),
    }


def main():
    parser = argparse.ArgumentParser(description="Sign an oracle attestation for escrow dispute resolution")
    parser.add_argument("--privkey", required=True, help="Oracle private key (32-byte hex)")
    parser.add_argument("--escrow-id", required=True, help="Escrow ID to attest")
    parser.add_argument("--outcome", required=True, choices=["buyer", "seller"], help="Dispute outcome")
    parser.add_argument("--reason", default=None, help="Human-readable reason")
    args = parser.parse_args()

    event = sign_attestation(args.privkey, args.escrow_id, args.outcome, args.reason)
    print(json.dumps(event, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
