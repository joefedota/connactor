# Cloud Run Service Setup

Deploys the FastAPI backend (`backend/`) to Cloud Run. The service is stateless; it connects to the Neo4j VM (`10.128.0.2:7687`) via VPC Direct Egress and reads secrets from Secret Manager at request time.

## Prerequisites

- `gcloud` CLI installed and authenticated
- Project set: `gcloud config set project connactor-497019`
- Secrets exist (see [`setup-secrets.md`](./setup-secrets.md))
- VM is up and Neo4j is reachable on `10.128.0.2:7687` (see [`setup-vm.md`](./setup-vm.md))

## Image strategy

One image — `backend/Dockerfile` — is used by:
- the Cloud Run **service** (this runbook): runs `uvicorn app.main:app` on port 8080
- the Cloud Run **jobs** (see [`setup-cron-job.md`](./setup-cron-job.md)): run `pipeline/bootstrap.py` with command override

A `.dockerignore` excludes test/dev files from the image. A `.gcloudignore` excludes the same plus the local `.venv` and `data/raw/`, `data/processed/` from the Cloud Build tarball (without it the upload is 1.4 GiB; with it, 149 KiB).

## 1. Enable APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project connactor-497019
```

## 2. Grant Cloud Build's worker SA the roles it needs

Cloud Build runs as the default Compute Engine SA. It needs to read the staging bucket, push to Artifact Registry, and write logs.

```bash
PROJECT_NUMBER=$(gcloud projects describe connactor-497019 --format='value(projectNumber)')
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for ROLE in \
  roles/cloudbuild.builds.builder \
  roles/storage.objectViewer \
  roles/artifactregistry.writer \
  roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding connactor-497019 \
    --member "serviceAccount:${COMPUTE_SA}" \
    --role "${ROLE}" \
    --condition=None
done
```

## 3. Create the Artifact Registry repo

```bash
gcloud artifacts repositories create connactor \
  --project connactor-497019 \
  --repository-format docker \
  --location us-central1 \
  --description "Connactor backend container images"
```

## 4. Build and push the image

Run from the repo root (or anywhere — we pass an absolute path):

```bash
gcloud builds submit \
  --project connactor-497019 \
  --tag us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest \
  --quiet \
  backend/
```

Typical build: ~45 seconds. The output ends with `STATUS: SUCCESS` and the image digest.

## 5. Deploy the Cloud Run service

```bash
gcloud run deploy connactor-api \
  --project connactor-497019 \
  --image us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest \
  --region us-central1 \
  --service-account connactor-api@connactor-497019.iam.gserviceaccount.com \
  --set-secrets "TMDB_API_READ_TOKEN=TMDB_API_READ_TOKEN:latest,NEO4J_PASSWORD=NEO4J_PASSWORD:latest" \
  --set-env-vars "NEO4J_URI=bolt://10.128.0.2:7687,NEO4J_USER=neo4j,GCS_BUCKET=connactor-data,GCP_PROJECT=connactor-497019" \
  --network default \
  --subnet default \
  --vpc-egress private-ranges-only \
  --min-instances 0 \
  --max-instances 10 \
  --allow-unauthenticated \
  --port 8080 \
  --quiet
```

Key flags:
- `--network default --subnet default --vpc-egress private-ranges-only` — Direct VPC Egress for private IPs (Neo4j VM at `10.128.0.2`); public traffic uses Cloud Run's default internet egress. **Don't use `all-traffic` unless you've set up Cloud NAT** — our VPC has no internet route, so `all-traffic` would break any call to Google APIs or TMDB.
- `--set-secrets` — Secret Manager values injected as env vars at request time. Rotating a secret in Secret Manager takes effect on the next request without redeploying.
- `--min-instances 0` — scale to zero when idle. Cold start is ~2s including Neo4j connection check.
- `--allow-unauthenticated` — the frontend (Cloudflare Pages) calls this directly. Restrict later if we add auth.

## 6. Verify

```bash
curl https://<service-url>/health
```

Expected (with empty DB):
```json
{"status":"ok","actors":0,"movies":0,"edges":0}
```

With a populated DB (after backfill), the counts will be non-zero.

## Updating the service later

Subsequent code changes are deployed via GitHub Actions (#12). To redeploy manually with the latest image:

```bash
gcloud run services update connactor-api \
  --project connactor-497019 \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest
```

## Reading logs

```bash
gcloud run services logs read connactor-api \
  --project connactor-497019 \
  --region us-central1 \
  --limit 50
```

Or tail live:

```bash
gcloud run services logs tail connactor-api \
  --project connactor-497019 \
  --region us-central1
```
