#!/usr/bin/env python3
"""
Migrate existing JSON escrow data to SQLite database
"""
import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.database.connection import ensure_tables, get_db_session
from backend.database.models import EscrowModel

JSON_STORAGE_FILE = Path.home() / '.ln-escrow' / 'escrows.json'


def load_json_escrows() -> dict:
    """Load escrows from JSON file"""
    if not JSON_STORAGE_FILE.exists():
        print(f"No JSON file found at {JSON_STORAGE_FILE}")
        return {}

    with open(JSON_STORAGE_FILE, 'r') as f:
        return json.load(f)


def migrate():
    """Migrate JSON data to database"""
    print("=" * 60)
    print("JSON to SQLite Migration")
    print("=" * 60)

    # Ensure database tables exist
    print("\n1. Creating database tables...")
    ensure_tables()
    print("   Done.")

    # Load JSON data
    print("\n2. Loading JSON data...")
    json_escrows = load_json_escrows()
    print(f"   Found {len(json_escrows)} escrows in JSON file.")

    if not json_escrows:
        print("\n   No escrows to migrate.")
        return

    # Migrate each escrow
    print("\n3. Migrating escrows...")
    migrated = 0
    skipped = 0
    errors = []

    with get_db_session() as db:
        for escrow_id, data in json_escrows.items():
            try:
                # Check if already exists
                existing = db.query(EscrowModel).filter(
                    EscrowModel.escrow_id == escrow_id
                ).first()

                if existing:
                    print(f"   SKIP: {escrow_id[:12]}... (already exists)")
                    skipped += 1
                    continue

                # Create model from dict
                escrow = EscrowModel.from_dict(data)
                db.add(escrow)
                migrated += 1

                print(f"   OK: {escrow_id[:12]}... | {data.get('state', 'unknown')} | {data.get('amount_msat', 0) // 1000:,} sats")

            except Exception as e:
                errors.append(f"{escrow_id[:12]}: {e}")
                print(f"   ERROR: {escrow_id[:12]}... - {e}")

    # Summary
    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"Migrated: {migrated}")
    print(f"Skipped:  {skipped}")
    print(f"Errors:   {len(errors)}")

    if errors:
        print("\nErrors:")
        for err in errors[:10]:
            print(f"  - {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")

    # Verify
    print("\n4. Verifying migration...")
    with get_db_session() as db:
        count = db.query(EscrowModel).count()
        print(f"   Total escrows in database: {count}")

    # Backup suggestion
    if migrated > 0:
        backup_path = JSON_STORAGE_FILE.with_suffix('.json.bak')
        print(f"\n5. Consider backing up JSON file:")
        print(f"   mv {JSON_STORAGE_FILE} {backup_path}")


if __name__ == '__main__':
    migrate()
