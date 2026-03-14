#!/usr/bin/env python3
"""
Oracle attestation publisher — signs and publishes to Nostr relays.

Signs an oracle attestation using oracle_sign.py's sign_attestation()
and publishes the resulting Nostr event to one or more relays via WebSocket.

Usage:
    python tools/oracle_publish.py \
        --privkey <hex> \
        --escrow-id <str> \
        --outcome buyer|seller \
        [--reason "..."] \
        [--relays wss://relay.damus.io,wss://nos.lol,wss://relay.nostr.band]

Dependencies: secp256k1, websockets (both already in requirements.txt)
"""

import argparse
import asyncio
import json
import sys

from websockets.asyncio.client import connect as ws_connect

# Import signing logic — no duplication
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from tools.oracle_sign import sign_attestation

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
]

RELAY_TIMEOUT = 10  # seconds to wait for OK response


async def publish_to_relay(relay_url: str, event: dict) -> tuple[str, bool, str]:
    """
    Publish a Nostr event to a single relay.

    Returns (relay_url, success, message).
    """
    try:
        async with ws_connect(relay_url, open_timeout=RELAY_TIMEOUT) as ws:
            await ws.send(json.dumps(["EVENT", event]))

            # Wait for OK response
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=RELAY_TIMEOUT)
                msg = json.loads(raw)
                if not isinstance(msg, list) or len(msg) < 2:
                    continue

                if msg[0] == "OK" and len(msg) >= 3:
                    # ["OK", event_id, true/false, message]
                    accepted = msg[2]
                    reason = msg[3] if len(msg) > 3 else ""
                    return relay_url, bool(accepted), reason

                if msg[0] == "NOTICE":
                    return relay_url, False, f"NOTICE: {msg[1] if len(msg) > 1 else '?'}"

    except (asyncio.TimeoutError, OSError, Exception) as exc:
        return relay_url, False, str(exc)


async def publish_event(event: dict, relays: list[str]) -> list[tuple[str, bool, str]]:
    """Publish event to all relays concurrently."""
    tasks = [publish_to_relay(url, event) for url in relays]
    return await asyncio.gather(*tasks)


def main():
    parser = argparse.ArgumentParser(
        description="Sign an oracle attestation and publish it to Nostr relays"
    )
    parser.add_argument("--privkey", required=True, help="Oracle private key (32-byte hex)")
    parser.add_argument("--escrow-id", required=True, help="Escrow ID to attest")
    parser.add_argument("--outcome", required=True, choices=["buyer", "seller"], help="Dispute outcome")
    parser.add_argument("--reason", default=None, help="Human-readable reason")
    parser.add_argument(
        "--relays",
        default=None,
        help=f"Comma-separated relay URLs (default: {','.join(DEFAULT_RELAYS)})",
    )
    args = parser.parse_args()

    relays = [r.strip() for r in args.relays.split(",")] if args.relays else DEFAULT_RELAYS

    # 1. Sign the attestation
    event = sign_attestation(args.privkey, args.escrow_id, args.outcome, args.reason)
    print(f"Signed event {event['id'][:16]}... by {event['pubkey'][:16]}...")
    print(f"  outcome: {args.outcome}")
    print(f"  escrow:  {args.escrow_id}")
    print()

    # 2. Publish to relays
    print(f"Publishing to {len(relays)} relay(s)...")
    results = asyncio.run(publish_event(event, relays))

    # 3. Report results
    ok_count = 0
    for relay_url, accepted, message in results:
        status = "OK" if accepted else "FAIL"
        suffix = f" ({message})" if message else ""
        print(f"  [{status}] {relay_url}{suffix}")
        if accepted:
            ok_count += 1

    print()
    if ok_count > 0:
        print(f"Published to {ok_count}/{len(relays)} relay(s)")
        return 0
    else:
        print("Failed to publish to any relay")
        return 1


if __name__ == "__main__":
    sys.exit(main())
