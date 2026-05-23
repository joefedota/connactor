# Pipeline Cloud Run Job + Cloud Scheduler

A single Cloud Run **Job** (`connactor-pipeline-full`) runs the data pipeline end-to-end every night. It shares the same Docker image as the Cloud Run service — only the `--command`/`--args` differ.

The job runs `python pipeline/bootstrap.py --mode prod`, which:
1. Downloads the latest TMDB movie ID export
2. Re-crawls credits for every movie (`force=True` — full refresh, not resume)
3. Re-crawls movie details (`vote_count`, `year`, etc.) for every movie
4. Enriches persons (checkpoint-resumable — only fetches new ones)
5. MERGEs everything into Neo4j and recomputes `fame_score` + `fame_rank` per actor

Total runtime: ~35 min. Everything is idempotent — re-running converges to the same graph state. Neo4j is never wiped or restarted; the pipeline is just a client writing fresh data via Bolt.

> **Why no delta job?** TMDB calls are cheap and the dataset is small enough that a full nightly re-crawl is simpler than maintaining a separate delta path. Vote counts (which feed `fame_rank`) drift slowly on TMDB and aren't covered by `/movie/changes`, so we'd need a full re-crawl periodically anyway.

## Prerequisites

- API image pushed to Artifact Registry (see [`setup-cloudrun.md`](./setup-cloudrun.md))
- VM Neo4j running (see [`setup-vm.md`](./setup-vm.md))
- `NEO4J_PASSWORD` and `TMDB_API_READ_TOKEN` in Secret Manager
- `connactor-api` service account has `secretmanager.secretAccessor` on both secrets
- `connactor-api` SA has `roles/storage.objectAdmin` on `gs://connactor-data`:
  ```bash
  gsutil iam ch \
    serviceAccount:connactor-api@connactor-497019.iam.gserviceaccount.com:objectAdmin \
    gs://connactor-data
  ```

## Network egress

`--vpc-egress private-ranges-only` is critical. With `all-traffic`, the container routes *everything* (including `storage.googleapis.com`, TMDB, Secret Manager API) through our VPC — which has no internet egress, so all public-API calls fail with `Errno 101 Network unreachable`. `private-ranges-only` sends just RFC1918 / private IP traffic (Neo4j at `10.128.0.2`) through the VPC; public traffic uses Cloud Run's default internet egress.

## 1. Create the pipeline job

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

## 2. Schedule it nightly

Cloud Scheduler needs its own service account to call the Cloud Run Jobs Admin API.

```bash
gcloud iam service-accounts create connactor-scheduler \
  --project connactor-497019 \
  --display-name "Cloud Scheduler → Cloud Run Jobs"

gcloud run jobs add-iam-policy-binding connactor-pipeline-full \
  --project connactor-497019 \
  --region us-central1 \
  --member "serviceAccount:connactor-scheduler@connactor-497019.iam.gserviceaccount.com" \
  --role roles/run.invoker

PROJECT_NUMBER=$(gcloud projects describe connactor-497019 --format='value(projectNumber)')

gcloud scheduler jobs create http connactor-pipeline-daily \
  --project connactor-497019 \
  --location us-central1 \
  --schedule "0 9 * * *" \
  --time-zone "UTC" \
  --http-method POST \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/connactor-pipeline-full:run" \
  --oauth-service-account-email connactor-scheduler@connactor-497019.iam.gserviceaccount.com
```

## Manual operations

Run the pipeline now:
```bash
gcloud run jobs execute connactor-pipeline-full \
  --project connactor-497019 --region us-central1 --async
```

Update the job to a new image (after a code push):
```bash
gcloud run jobs update connactor-pipeline-full \
  --image us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest \
  --project connactor-497019 --region us-central1
```

Pause / resume the nightly trigger:
```bash
gcloud scheduler jobs pause  connactor-pipeline-daily --project connactor-497019 --location us-central1
gcloud scheduler jobs resume connactor-pipeline-daily --project connactor-497019 --location us-central1
```

## Reading logs

```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=connactor-pipeline-full" \
  --project connactor-497019 --limit 50 --order desc --format='value(timestamp,textPayload)'
```

## Idempotency guarantees

- **GCS uploads are atomic.** A partial upload can't leave a corrupted JSONL.
- **Crawl steps `force=True`**: write to local tempfiles, only upload the final JSONL at the end. Crash mid-crawl → old GCS data untouched → next run starts clean.
- **`load_neo4j` MERGE**: re-running with the same input data converges to the same graph state. No duplicate nodes/edges.
- **`_compute_fame_rank` is deterministic**: pure `SET` assignments ordered by `(fame_score DESC, popularity DESC, person_id ASC)`. Same input → same ranks.

The only caveat is that the graph is **grow-only** — if a movie or person disappears from TMDB, the Neo4j node + edges stay. For our use case this is fine (TMDB rarely deletes content, and stale nodes are unreachable in shortestPath against current data). If we ever need cleanup, add a "prune nodes not in current crawl" step at the end of `load_neo4j`.
