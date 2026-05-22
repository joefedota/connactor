# Pipeline Cloud Run Jobs + Cloud Scheduler

The data pipeline (`backend/pipeline/bootstrap.py`) runs as two Cloud Run **Jobs** — batch workloads that run to completion, share the same Docker image as the Cloud Run service, and reach the VM Neo4j over VPC Direct Egress.

| Job | Trigger | Timeout | What it does |
|---|---|---|---|
| `connactor-pipeline-full` | Manual | 6h | `bootstrap.py --mode prod` — download TMDB movie ID export, crawl every qualifying movie's credits, enrich all persons, load Neo4j from scratch. Run once at setup time and on demand. |
| `connactor-pipeline-delta` | Cloud Scheduler, 09:00 UTC daily | 1h | `bootstrap.py --mode prod --delta --skip-download` — re-crawl movies changed in TMDB in the last 24h via `/movie/changes`, append rows, MERGE into Neo4j. |

Both jobs use the same image as the Cloud Run service (`us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest`); only the `--command`/`--args` differ.

### Network egress

`--vpc-egress private-ranges-only` is critical. With `all-traffic`, the container routes *everything* (including `storage.googleapis.com`, TMDB, Secret Manager API) through our VPC — which has no internet egress, so all public-API calls fail with `Errno 101 Network unreachable`. `private-ranges-only` sends just RFC1918 / private IP traffic (the Neo4j VM at `10.128.0.2`) through the VPC; public traffic uses Cloud Run's default internet egress.

The same flag is applied to the Cloud Run service in [`setup-cloudrun.md`](./setup-cloudrun.md).

## Prerequisites

- API image pushed to Artifact Registry (see [`setup-cloudrun.md`](./setup-cloudrun.md))
- VM Neo4j running (see [`setup-vm.md`](./setup-vm.md))
- `NEO4J_PASSWORD` and `TMDB_API_READ_TOKEN` in Secret Manager (see [`setup-secrets.md`](./setup-secrets.md))
- `connactor-api` service account exists and has `secretmanager.secretAccessor` on both secrets
- GCS bucket `connactor-data` exists and `connactor-api` SA has `roles/storage.objectAdmin` on it

Grant the GCS role if you haven't yet:

```bash
gsutil iam ch \
  serviceAccount:connactor-api@connactor-497019.iam.gserviceaccount.com:objectAdmin \
  gs://connactor-data
```

## 1. Create the full-backfill job

```bash
gcloud run jobs create connactor-pipeline-full \
  --project connactor-497019 \
  --image us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest \
  --region us-central1 \
  --service-account connactor-api@connactor-497019.iam.gserviceaccount.com \
  --set-secrets "TMDB_API_READ_TOKEN=TMDB_API_READ_TOKEN:latest,NEO4J_PASSWORD=NEO4J_PASSWORD:latest" \
  --set-env-vars "NEO4J_URI=bolt://10.128.0.2:7687,NEO4J_USER=neo4j,GCS_BUCKET=connactor-data,GCP_PROJECT=connactor-497019" \
  --network default \
  --subnet default \
  --vpc-egress private-ranges-only \
  --memory 2Gi \
  --cpu 1 \
  --task-timeout 21600 \
  --max-retries 1 \
  --command python \
  --args pipeline/bootstrap.py,--mode,prod
```

Execute it once at setup time:

```bash
gcloud run jobs execute connactor-pipeline-full \
  --project connactor-497019 \
  --region us-central1 \
  --async
```

The `--async` flag returns immediately; the job runs ~4-6 hours. Watch logs:

```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=connactor-pipeline-full" \
  --project connactor-497019 --limit 50 --order desc --format='value(textPayload)'
```

## 2. Create the delta job

```bash
gcloud run jobs create connactor-pipeline-delta \
  --project connactor-497019 \
  --image us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest \
  --region us-central1 \
  --service-account connactor-api@connactor-497019.iam.gserviceaccount.com \
  --set-secrets "TMDB_API_READ_TOKEN=TMDB_API_READ_TOKEN:latest,NEO4J_PASSWORD=NEO4J_PASSWORD:latest" \
  --set-env-vars "NEO4J_URI=bolt://10.128.0.2:7687,NEO4J_USER=neo4j,GCS_BUCKET=connactor-data,GCP_PROJECT=connactor-497019" \
  --network default \
  --subnet default \
  --vpc-egress private-ranges-only \
  --memory 2Gi \
  --cpu 1 \
  --task-timeout 3600 \
  --max-retries 2 \
  --command python \
  --args pipeline/bootstrap.py,--mode,prod,--delta,--skip-download
```

## 3. Schedule the delta job

Cloud Scheduler needs its own service account to call the Cloud Run Jobs Admin API.

```bash
gcloud iam service-accounts create connactor-scheduler \
  --project connactor-497019 \
  --display-name "Cloud Scheduler → Cloud Run Jobs"

# Permission to invoke the specific delta job
gcloud run jobs add-iam-policy-binding connactor-pipeline-delta \
  --project connactor-497019 \
  --region us-central1 \
  --member "serviceAccount:connactor-scheduler@connactor-497019.iam.gserviceaccount.com" \
  --role roles/run.invoker
```

Create the scheduled trigger (09:00 UTC daily):

```bash
PROJECT_NUMBER=$(gcloud projects describe connactor-497019 --format='value(projectNumber)')

gcloud scheduler jobs create http connactor-delta-daily \
  --project connactor-497019 \
  --location us-central1 \
  --schedule "0 9 * * *" \
  --time-zone "UTC" \
  --http-method POST \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/connactor-pipeline-delta:run" \
  --oauth-service-account-email connactor-scheduler@connactor-497019.iam.gserviceaccount.com
```

Verify the cron job is registered:

```bash
gcloud scheduler jobs describe connactor-delta-daily \
  --project connactor-497019 --location us-central1
```

## Manual operations

Run the delta now (don't wait for 09:00 UTC):

```bash
gcloud run jobs execute connactor-pipeline-delta \
  --project connactor-497019 --region us-central1 --async
```

Re-run a full backfill (e.g. after major schema change):

```bash
gcloud run jobs execute connactor-pipeline-full \
  --project connactor-497019 --region us-central1 --async
```

Update either job to a new image (e.g. after a code change pushes a new `:latest`):

```bash
gcloud run jobs update connactor-pipeline-delta \
  --image us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest \
  --project connactor-497019 --region us-central1
```

Pause / resume the Cloud Scheduler trigger:

```bash
gcloud scheduler jobs pause  connactor-delta-daily --project connactor-497019 --location us-central1
gcloud scheduler jobs resume connactor-delta-daily --project connactor-497019 --location us-central1
```

## Reading logs

```bash
# Full backfill — last 50 lines
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=connactor-pipeline-full" \
  --project connactor-497019 --limit 50 --order desc --format='value(textPayload)'

# Delta — last 50 lines
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=connactor-pipeline-delta" \
  --project connactor-497019 --limit 50 --order desc --format='value(textPayload)'
```
