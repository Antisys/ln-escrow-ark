#!/bin/bash
# DB backup script for ln-escrow
# Recommended cron: 0 */2 * * * /home/pi/ln-escrow/deploy/backup-db.sh
#
# Keeps last 30 backups (2.5 days at 2-hour intervals)

set -euo pipefail

DB_PATH="${HOME}/.ln-escrow/escrow.db"
BACKUP_DIR="${HOME}/.ln-escrow/backups"
MAX_BACKUPS=30

if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: Database not found at $DB_PATH"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/escrow_${TIMESTAMP}.db"

# Use sqlite3 .backup for consistent copy (safe even while DB is in use)
sqlite3 "$DB_PATH" ".backup '${BACKUP_FILE}'"

# Compress
gzip "$BACKUP_FILE"

echo "Backup created: ${BACKUP_FILE}.gz ($(du -h "${BACKUP_FILE}.gz" | cut -f1))"

# Prune old backups (keep last N)
cd "$BACKUP_DIR"
ls -t escrow_*.db.gz 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | xargs -r rm --
echo "Backups in ${BACKUP_DIR}: $(ls escrow_*.db.gz 2>/dev/null | wc -l)"
