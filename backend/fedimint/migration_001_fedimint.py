"""
Migration 001: Add Fedimint escrow columns to the deals table.

Run once on any existing database before enabling USE_FEDIMINT=true.

Usage:
    python -m backend.fedimint.migration_001_fedimint

Or on production server:
    python -m backend.fedimint.migration_001_fedimint
"""
import logging
import sqlite3
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Match the DB path used by the app (env var or default)
_DEFAULT_DB_PATH = Path.home() / ".ln-escrow" / "escrow.db"
_DB_PATH = os.environ.get("DATABASE_URL", str(_DEFAULT_DB_PATH)).removeprefix("sqlite:///")

NEW_COLUMNS = [
    ("fedimint_escrow_id",       "TEXT"),
    ("fedimint_secret_code",     "TEXT"),
    ("fedimint_timeout_block",   "INTEGER"),
]


def run_migration(db_path: str = _DB_PATH) -> None:
    logger.info("Running migration_001_fedimint on %s", db_path)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(deals)")
        existing = {row[1] for row in cur.fetchall()}

        added = []
        for col_name, col_type in NEW_COLUMNS:
            if col_name not in existing:
                cur.execute(f"ALTER TABLE deals ADD COLUMN {col_name} {col_type}")
                added.append(col_name)
                logger.info("Added column: deals.%s %s", col_name, col_type)
            else:
                logger.info("Column already exists, skipping: deals.%s", col_name)

        conn.commit()
        if added:
            print(f"Migration complete. Added columns: {', '.join(added)}")
        else:
            print("Migration complete. No new columns needed (already applied).")
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
