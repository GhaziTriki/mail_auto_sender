#!/usr/bin/env sh
set -eu
[ $# -eq 1 ] || { echo "usage: restore.sh <backup-dir>"; exit 1; }
DIR="$1"
docker compose stop api worker
docker compose exec -T mongo mongorestore --archive --gzip --drop < "$DIR/mongo.archive.gz"
docker compose run --rm -T --no-deps api sh -c "rm -rf /data/* && tar -C /data -xzf -" < "$DIR/data.tar.gz"
docker compose start api worker
echo "Restored from $DIR"
