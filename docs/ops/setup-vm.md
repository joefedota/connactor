# Compute Engine VM Setup

Provisions the GCP VM that runs Neo4j for production. The VM hosts the database only — the API runs on Cloud Run and connects via VPC.

The VM provisions itself via [`scripts/vm-startup.sh`](../../scripts/vm-startup.sh), which mounts the data disk, installs Docker, fetches the Neo4j password from Secret Manager, and starts Neo4j. The runbook below creates the surrounding infrastructure (disk, IP, firewall, service account) and hands the startup script to the VM at create time.

## Why a separate persistent disk?

Neo4j writes its database files to `/data` inside the container. The container itself is ephemeral — delete it and everything in its writable layer is gone. To make the data durable, we layer storage like this:

```
20GB balanced persistent disk (separate GCP resource)
  └─ mounted at /data on the host (ext4)
        └─ docker-compose bind-mounts /data/neo4j/data → /data inside the Neo4j container
              └─ Neo4j writes here
```

The disk is a separate GCP resource from the VM, which buys us three things:

- **Survives VM deletion.** Delete and recreate the VM and the data is still there — you just reattach the disk.
- **Independent snapshots.** The daily 03:00 UTC snapshot schedule is attached to the data disk only. We back up what matters, not the OS.
- **Sized and tuned for Neo4j.** The 20GB balanced disk has ample headroom for
  the current sub-1GB data directory without paying for unused SSD capacity.
  Reassess capacity and I/O before the dataset approaches 70% utilization.

The `mkfs.ext4` in the startup script is gated by `blkid` — it only formats a blank disk. Once formatted (after first boot), every subsequent boot just mounts the existing filesystem, preserving all data.

## Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- Project set: `gcloud config set project connactor-497019`
- `NEO4J_PASSWORD` already in Secret Manager (see [`setup-secrets.md`](./setup-secrets.md))

---

## 1. Enable Compute Engine API

```bash
gcloud services enable compute.googleapis.com --project connactor-497019
```

## 2. Create the Data Disk

```bash
gcloud compute disks create connactor-db-data-balanced \
  --project connactor-497019 \
  --zone us-central1-a \
  --type pd-balanced \
  --size 20GB
```

## 3. Daily Snapshot Schedule

```bash
gcloud compute resource-policies create snapshot-schedule connactor-daily-backup \
  --project connactor-497019 \
  --region us-central1 \
  --max-retention-days 7 \
  --start-time 03:00 \
  --daily-schedule

gcloud compute disks add-resource-policies connactor-db-data-balanced \
  --project connactor-497019 \
  --zone us-central1-a \
  --resource-policies connactor-daily-backup
```

## 4. Reserve a Static Internal IP

```bash
gcloud compute addresses create connactor-db-internal \
  --project connactor-497019 \
  --region us-central1 \
  --subnet default \
  --purpose GCE_ENDPOINT
```

Capture the assigned IP for use in step 6:

```bash
gcloud compute addresses describe connactor-db-internal \
  --region us-central1 --project connactor-497019 \
  --format 'value(address)'
```

## 5. VM Service Account + Firewall

```bash
# Dedicated SA so the VM can read NEO4J_PASSWORD from Secret Manager — nothing else.
gcloud iam service-accounts create connactor-db-vm \
  --project connactor-497019 \
  --display-name "Connactor DB VM"

gcloud secrets add-iam-policy-binding NEO4J_PASSWORD \
  --project connactor-497019 \
  --member "serviceAccount:connactor-db-vm@connactor-497019.iam.gserviceaccount.com" \
  --role "roles/secretmanager.secretAccessor"

# Neo4j Bolt is reachable only from inside the VPC (Cloud Run, Cloud Run Jobs).
gcloud compute firewall-rules create allow-neo4j-from-cloudrun \
  --project connactor-497019 \
  --allow tcp:7687 \
  --target-tags connactor-db \
  --source-ranges 10.0.0.0/8 \
  --description "Allow Neo4j Bolt from Cloud Run VPC"
```

## 6. Create the VM

The startup script runs on first boot (and again on every restart — it's idempotent). Replace `<internal-ip>` with the address from step 4.

```bash
gcloud compute instances create connactor-db \
  --project connactor-497019 \
  --zone us-central1-a \
  --machine-type e2-medium \
  --image-family debian-12 \
  --image-project debian-cloud \
  --boot-disk-size 20GB \
  --tags connactor-db \
  --disk name=connactor-db-data-balanced,device-name=data,mode=rw,boot=no \
  --private-network-ip <internal-ip> \
  --service-account connactor-db-vm@connactor-497019.iam.gserviceaccount.com \
  --scopes cloud-platform \
  --metadata-from-file startup-script=scripts/vm-startup.sh
```

Run this from the repo root so the relative path to `scripts/vm-startup.sh` resolves.

The previous `connactor-db-data` 100GB SSD is intentionally detached and kept
for short-term rollback after the 2026-08-23 rightsizing. Once the new disk has
completed several healthy snapshot cycles, delete the old disk to stop its
remaining storage charges:

```bash
gcloud compute disks delete connactor-db-data \
  --project connactor-497019 --zone us-central1-a
```

## 7. Verify

Startup typically finishes in 2–3 minutes (apt update, Docker install, Neo4j pull, boot). Watch for the Neo4j container:

```bash
gcloud compute ssh connactor-db --zone us-central1-a --project connactor-497019 \
  --command "docker ps"
```

Then ping cypher-shell:

```bash
gcloud compute ssh connactor-db --zone us-central1-a --project connactor-497019 --command '
  PW=$(gcloud secrets versions access latest --secret NEO4J_PASSWORD --project connactor-497019);
  docker exec $(docker ps -q --filter ancestor=neo4j:5-community) cypher-shell -u neo4j -p "$PW" "RETURN 1 AS ok"
'
```

Expected output:
```
ok
1
```

## Replicating the VM

To recreate the VM from scratch (e.g. after deletion), re-run steps 1–6. Disk and snapshots survive VM deletion.

To re-run the startup script on an existing VM (e.g. after editing it):

```bash
gcloud compute instances add-metadata connactor-db --zone us-central1-a --project connactor-497019 \
  --metadata-from-file startup-script=scripts/vm-startup.sh
gcloud compute instances reset connactor-db --zone us-central1-a --project connactor-497019
```

## Inspecting startup-script output

If something goes wrong during boot:

```bash
gcloud compute ssh connactor-db --zone us-central1-a --project connactor-497019 \
  --command "sudo journalctl -u google-startup-scripts.service --no-pager"
```
