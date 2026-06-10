#!/usr/bin/env bash
# Backup the remote D1 database. The collected history (track_events, milestones,
# vehicle_arrivals, train_status) exists nowhere else publicly — treat it as irreplaceable.
# Run weekly, e.g. crontab:  0 7 * * 1  cd /home/rob/Code/lib/scratch/estimated-platform && ./scripts/backup-d1.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
out="backups/full-$(date +%Y%m%d).sql"
npx wrangler d1 export estimated-platform --remote --output "$out"
gzip -f "$out"
# keep the 6 most recent
ls -1t backups/full-*.sql.gz 2>/dev/null | tail -n +7 | xargs -r rm
echo "backup: ${out}.gz ($(du -h "${out}.gz" | cut -f1)), $(ls backups/*.sql.gz | wc -l) retained"
