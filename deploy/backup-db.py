#!/usr/bin/env python3
"""Crash-safe SQLite backup. Keeps last 48 copies (4 days at 2h intervals)."""
import sqlite3
import os
import glob
from datetime import datetime

BACKUP_DIR = os.environ.get("BACKUP_DIR", "/var/backups/escrow")
DB_PATH = os.environ.get("DB_PATH", os.path.expanduser("~/.ln-escrow/escrow.db"))
MAX_BACKUPS = 48

os.makedirs(BACKUP_DIR, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_file = os.path.join(BACKUP_DIR, f"escrow_{timestamp}.db")

try:
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(backup_file)
    src.backup(dst)
    dst.close()
    src.close()
    size = os.path.getsize(backup_file)
    print(f"Backup OK: {backup_file} ({size // 1024} KB)")
except Exception as e:
    print(f"BACKUP FAILED: {e}")
    if os.path.exists(backup_file):
        os.remove(backup_file)
    raise SystemExit(1)

# Prune old backups
backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "escrow_*.db")), reverse=True)
for old in backups[MAX_BACKUPS:]:
    os.remove(old)
    print(f"Pruned: {old}")
