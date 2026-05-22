#!/usr/bin/env bash
# VM startup script for connactor-db.
# Idempotent — safe to re-run by rebooting the VM or via:
#   gcloud compute instances add-metadata connactor-db --metadata-from-file startup-script=scripts/vm-startup.sh
#   gcloud compute instances reset connactor-db
#
# Fetches NEO4J_PASSWORD from Secret Manager using the VM's service account,
# so no secrets ever land on disk or in metadata.

set -euxo pipefail

PROJECT=connactor-497019
DATA_DEVICE=/dev/disk/by-id/google-data
DATA_MOUNT=/data

# 1. Mount the data disk (format only if blank — preserves data across VM recreation).
if ! blkid "$DATA_DEVICE" >/dev/null 2>&1; then
  mkfs.ext4 -F "$DATA_DEVICE"
fi
mkdir -p "$DATA_MOUNT"
grep -q "$DATA_DEVICE" /etc/fstab || \
  echo "$DATA_DEVICE $DATA_MOUNT ext4 defaults,nofail 0 2" >> /etc/fstab
mountpoint -q "$DATA_MOUNT" || mount "$DATA_MOUNT"
mkdir -p "$DATA_MOUNT/neo4j/data" "$DATA_MOUNT/neo4j/logs" "$DATA_MOUNT/dumps"

# 2. Install Docker if missing.
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# 3. Fetch Neo4j password via the VM's service account (must have secretmanager.secretAccessor).
NEO4J_PASSWORD=$(gcloud secrets versions access latest --secret NEO4J_PASSWORD --project "$PROJECT")

# 4. Write docker-compose file.
mkdir -p /opt/connactor
cat > /opt/connactor/docker-compose.db.yml <<'YAML'
services:
  neo4j:
    image: neo4j:5-community
    restart: always
    ports: []
    expose: ["7474", "7687"]
    volumes:
      - /data/neo4j/data:/data
      - /data/neo4j/logs:/logs
      - /data/dumps:/dumps
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
      - NEO4J_dbms_memory_heap_initial__size=4g
      - NEO4J_dbms_memory_heap_max__size=4g
      - NEO4J_dbms_memory_pagecache_size=6g
YAML

# 5. Start Neo4j.
cd /opt/connactor
NEO4J_PASSWORD="$NEO4J_PASSWORD" docker compose -f docker-compose.db.yml up -d
