#!/usr/bin/env bash
# Deploy the latest prebuilt images and reclaim disk space.
#
# Pulls the newest API + web images from GHCR, restarts the stack, then prunes
# old images so the disk doesn't fill up. Each build is ~1 GB and every pull
# leaves the previous one behind; once the 40 GB disk fills, Postgres can no
# longer write and crash-loops ("No space left on device"), so the prune is not
# optional — it is part of a safe deploy.
#
# Run on the VM from this directory (needs Docker access, hence sudo):
#   sudo ./deploy.sh
#
# Volumes (the database) are never touched — only unused images and build cache.
set -euo pipefail

cd "$(dirname "$0")"

compose() { docker compose -f docker-compose.prod.images.yml --env-file .env "$@"; }

echo "==> Pulling latest images"
compose pull

echo "==> Restarting stack"
compose up -d

echo "==> Reclaiming disk (unused images + build cache; volumes untouched)"
docker image prune -af
docker builder prune -af

echo "==> Disk usage"
df -h /
