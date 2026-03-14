#!/usr/bin/env python3
"""
Escrow Recovery Tool — recover funds without the service.

Usage:
    # Using individual flags:
    python3 escrow-recovery.py \\
        --federation-invite "fed11..." \\
        --escrow-id "abc123" \\
        --private-key "deadbeef..." \\
        --bolt11 "lnbc..."

    # Using a recovery kit (exported from the deal details page):
    python3 escrow-recovery.py --recovery-kit recovery-kit-abc12345.json

    # Just check escrow state without claiming:
    python3 escrow-recovery.py --recovery-kit recovery-kit-abc12345.json --action info

Options:
    --federation-invite   Federation invite code (fed11...)
    --escrow-id           Ark escrow ID
    --private-key         Your ephemeral private key (hex)
    --bolt11              BOLT11 invoice to pay recovered funds to
    --recovery-kit        Path to recovery kit JSON (alternative to individual flags)
    --ark-escrow-agent        Path to ark-escrow-agent binary (default: ark-escrow-agent)
    --data-dir            Client data directory (default: ~/.escrow-recovery/)
    --action              claim-timeout (default) or info

What this does:
    1. Joins the Ark federation using the invite code
    2. Signs SHA256("timeout") with your ephemeral private key
    3. Calls claim-timeout-delegated to claim the escrow
    4. Pays the BOLT11 invoice from the recovered e-cash

Requirements:
    - ark-escrow-agent binary (with the escrow module compiled in)
    - secp256k1 Python library: pip install secp256k1
    - The escrow must have passed its timeout block height
    - Your private key must match buyer_pubkey or seller_pubkey in the escrow

Your private key can be found in your browser's localStorage:
    1. Open DevTools (F12) -> Application -> Local Storage
    2. Find 'vault_deal_keys' -> your deal ID -> your role -> privateKey
    3. Or use the "Export Recovery Kit" button in the deal details page
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

try:
    import secp256k1
except ImportError:
    secp256k1 = None


def _require_secp256k1():
    """Ensure secp256k1 is available, exit with helpful message if not."""
    if secp256k1 is None:
        print("ERROR: secp256k1 library not installed.")
        print("Install it with: pip install secp256k1")
        sys.exit(1)


def sign_timeout(private_key_hex: str) -> str:
    """Sign SHA256("timeout") with BIP-340 Schnorr signature."""
    _require_secp256k1()
    privkey_bytes = bytes.fromhex(private_key_hex)
    pk = secp256k1.PrivateKey(privkey_bytes)
    msg = hashlib.sha256(b"timeout").digest()
    sig = pk.schnorr_sign(msg, b"", raw=True)
    return sig.hex()


def get_pubkey(private_key_hex: str) -> str:
    """Derive compressed public key from private key."""
    _require_secp256k1()
    privkey_bytes = bytes.fromhex(private_key_hex)
    pk = secp256k1.PrivateKey(privkey_bytes)
    return pk.pubkey.serialize(compressed=True).hex()


def run_cli(cli_path: str, data_dir: str, *args) -> str:
    """Run ark-escrow-agent command and return stdout."""
    cmd = [cli_path, "--data-dir", data_dir] + list(args)
    print(f"  > {' '.join(cmd[:6])}...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
        raise RuntimeError(f"ark-escrow-agent failed: {result.stderr.strip()}")
    return result.stdout.strip()


def load_recovery_kit(path: str) -> dict:
    """Load and validate a recovery kit JSON file."""
    if not os.path.isfile(path):
        print(f"ERROR: Recovery kit file not found: {path}")
        sys.exit(1)
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Recovery kit is not valid JSON: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Recover escrow funds without the service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--federation-invite", help="Federation invite code (fed11...)")
    parser.add_argument("--escrow-id", help="Ark escrow ID")
    parser.add_argument("--private-key", help="Your ephemeral private key (hex)")
    parser.add_argument("--bolt11", help="BOLT11 invoice to pay recovered funds to")
    parser.add_argument("--ark-escrow-agent", default="ark-escrow-agent",
                        help="Path to ark-escrow-agent binary (default: ark-escrow-agent)")
    parser.add_argument("--data-dir",
                        help="Client data directory (default: ~/.escrow-recovery/)")
    parser.add_argument("--action", choices=["claim-timeout", "info"],
                        default="claim-timeout",
                        help="Action to perform (default: claim-timeout)")
    parser.add_argument("--recovery-kit",
                        help="Path to recovery kit JSON file (alternative to individual flags)")
    args = parser.parse_args()

    # Load recovery kit if provided — fills in any missing flags
    if args.recovery_kit:
        kit = load_recovery_kit(args.recovery_kit)
        if not args.federation_invite:
            args.federation_invite = kit.get("federation_invite_code")
        if not args.escrow_id:
            args.escrow_id = kit.get("escrow_id")
        if not args.private_key:
            args.private_key = kit.get("your_private_key")

    # Validate required fields
    missing = []
    if not args.federation_invite:
        missing.append("--federation-invite")
    if not args.escrow_id:
        missing.append("--escrow-id")
    if not args.private_key:
        missing.append("--private-key")
    if missing:
        parser.error(
            f"Missing required arguments: {', '.join(missing)}. "
            "Provide them directly or via --recovery-kit."
        )

    # Default data dir to a stable location (not a random tempdir)
    default_data_dir = os.path.join(os.path.expanduser("~"), ".escrow-recovery")
    data_dir = args.data_dir or default_data_dir
    os.makedirs(data_dir, exist_ok=True)
    cli = args.ark_cli

    pubkey = get_pubkey(args.private_key)
    print(f"\n{'=' * 60}")
    print("  ESCROW RECOVERY TOOL")
    print(f"  Escrow ID:   {args.escrow_id}")
    print(f"  Your pubkey: {pubkey}")
    print(f"  Data dir:    {data_dir}")
    print(f"{'=' * 60}\n")

    # Step 1: Join federation
    print("[1/4] Joining federation...")
    if os.path.isdir(os.path.join(data_dir, "client.db")):
        print("  Already joined (client.db exists)")
    else:
        try:
            run_cli(cli, data_dir, "join-federation", args.federation_invite)
            print("  Joined successfully")
        except RuntimeError as e:
            if "already" in str(e).lower():
                print("  Already joined")
            else:
                raise

    # Step 2: Check escrow info
    print("\n[2/4] Checking escrow state...")
    info_json = run_cli(cli, data_dir, "module", "escrow", "info", args.escrow_id)
    info = json.loads(info_json)
    print(f"  State:  {info.get('state', 'unknown')}")
    print(f"  Amount: {info.get('amount', 'unknown')} msat")
    if info.get("buyer_pubkey"):
        print(f"  Buyer:  {info['buyer_pubkey']}")
    if info.get("seller_pubkey"):
        print(f"  Seller: {info['seller_pubkey']}")

    if args.action == "info":
        print("\nDone (info only).")
        return

    state = info.get("state", "")
    if state not in ("Open", "DisputedByBuyer", "DisputedBySeller"):
        print(f"\n  WARNING: Escrow state is '{state}' — may already be claimed.")
        response = input("  Continue anyway? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            return

    # Step 3: Sign timeout
    print("\n[3/4] Signing timeout authorization...")
    sig_hex = sign_timeout(args.private_key)
    print(f"  Signature: {sig_hex[:32]}...")

    # Step 4: Claim
    if args.bolt11:
        print("\n[4/4] Claiming escrow + paying invoice...")
        result_json = run_cli(
            cli, data_dir, "module", "escrow",
            "claim-timeout-delegated-and-pay",
            args.escrow_id, sig_hex, args.bolt11,
        )
        result = json.loads(result_json)
        print(f"  Result: {json.dumps(result, indent=2)}")
    else:
        print("\n[4/4] Claiming escrow (no invoice — e-cash stays in wallet)...")
        run_cli(
            cli, data_dir, "module", "escrow",
            "claim-timeout-delegated",
            args.escrow_id, sig_hex,
        )
        print("  Escrow claimed! E-cash is in your local wallet.")
        print(f"  Use '{cli} --data-dir {data_dir} info' to check balance.")
        print(f"  Use '{cli} --data-dir {data_dir} module ln pay <bolt11>' to pay out.")

    print(f"\n{'=' * 60}")
    print("  RECOVERY COMPLETE")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
