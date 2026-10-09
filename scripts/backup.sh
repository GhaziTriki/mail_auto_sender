#!/usr/bin/env sh
set -eu
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="./backups/$TS"
mkdir -p "$OUT"
docker compose exec -T mongo mongodump --archive --gzip --db applymail > "$OUT/mongo.archive.gz"
docker compose exec -T api tar -C /data -czf - . > "$OUT/data.tar.gz"
echo "Backup written to $OUT"
