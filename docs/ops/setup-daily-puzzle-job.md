# Daily Puzzle Cloud Run Job + Cloud Scheduler

`connactor-daily-puzzle` is a Cloud Run Job that runs `pipeline/generate_daily_puzzle.py` once per night to pre-generate tomorrow's daily puzzle. It shares the same Docker image as the API service — only the command/args differ.

The job picks two random actors with `fame_rank` between 50–200 (medium fame tier), verifies a path exists between them, and upserts the pair into the `puzzles` table with `is_daily=true` and `scheduled_date = tomorrow (UTC)`.

The job is idempotent — if tomorrow's daily puzzle already exists it skips silently.

## Prerequisites

- API image pushed to Artifact Registry (see [`setup-cloudrun.md`](./setup-cloudrun.md))
- VM Neo4j running (see [`setup-vm.md`](./setup-vm.md))
- `connactor-daily-puzzle` job created (see step 1 below)
- `DATABASE_URL`, `NEO4J_PASSWORD` in Secret Manager
- `connactor-api` service account has `secretmanager.secretAccessor` on both secrets
- `connactor-scheduler` service account exists (created for the pipeline job — no changes needed)

## 1. Create the job (one-time)

```bash
gcloud run jobs create connactor-daily-puzzle \
  --project connactor-497019 \
  --image us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest \
  --region us-central1 \
  --service-account connactor-api@connactor-497019.iam.gserviceaccount.com \
  --set-secrets "NEO4J_PASSWORD=NEO4J_PASSWORD:latest,DATABASE_URL=DATABASE_URL:latest" \
  --set-env-vars "NEO4J_URI=bolt://10.128.0.2:7687,NEO4J_USER=neo4j" \
  --network default \
  --subnet default \
  --vpc-egress private-ranges-only \
  --memory 512Mi \
  --cpu 1 \
  --task-timeout 300 \
  --max-retries 2 \
  --command python \
  --args pipeline/generate_daily_puzzle.py
```

> `--vpc-egress private-ranges-only` is required so the job can reach Neo4j at `10.128.0.2` while still routing public traffic (Neon Postgres) through Cloud Run's default internet egress. See [`setup-cron-job.md`](./setup-cron-job.md) for the detailed explanation.

## 2. Grant the scheduler permission to invoke it

The `connactor-scheduler` service account was already created for the pipeline job. Just grant it invoker rights on this new job:

```bash
gcloud run jobs add-iam-policy-binding connactor-daily-puzzle \
  --project connactor-497019 \
  --region us-central1 \
  --member "serviceAccount:connactor-scheduler@connactor-497019.iam.gserviceaccount.com" \
  --role roles/run.invoker
```

## 3. Schedule it nightly at 06:00 UTC

```bash
PROJECT_NUMBER=$(gcloud projects describe connactor-497019 --format='value(projectNumber)')

gcloud scheduler jobs create http connactor-daily-puzzle-schedule \
  --project connactor-497019 \
  --location us-central1 \
  --schedule "1 0 * * *" \
  --time-zone "UTC" \
  --http-method POST \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/connactor-daily-puzzle:run" \
  --oauth-service-account-email connactor-scheduler@connactor-497019.iam.gserviceaccount.com
```

The job runs at 00:01 UTC — one minute into the new day — and generates today's puzzle (default: `--date tomorrow` resolves to the current UTC date from the job's perspective). This ensures there is no window during the day when `/daily` returns 404. The pipeline job (`connactor-pipeline-full`) runs at 09:00 UTC and recomputes `fame_rank`; the puzzle generator runs before it and uses the previous day's ranks, which is fine since fame ranks change slowly.

## Manual operations

Generate tomorrow's puzzle now:
```bash
gcloud run jobs execute connactor-daily-puzzle \
  --project connactor-497019 --region us-central1 --async
```

Generate a specific date's puzzle (override args):
```bash
gcloud run jobs execute connactor-daily-puzzle \
  --project connactor-497019 --region us-central1 \
  --args "pipeline/generate_daily_puzzle.py,--date,2026-05-26" --async
```

Regenerate today's puzzle (replaces the existing one):
```bash
gcloud run jobs execute connactor-daily-puzzle \
  --project connactor-497019 --region us-central1 \
  --args "pipeline/generate_daily_puzzle.py,--date,2026-05-24,--force" --async
```

Or use the local wrapper script against prod Postgres + local Neo4j:
```bash
backend/bin/generate-daily-puzzle.sh prod --date 2026-05-26
```

Pause / resume the nightly schedule:
```bash
gcloud scheduler jobs pause  connactor-daily-puzzle-schedule --project connactor-497019 --location us-central1
gcloud scheduler jobs resume connactor-daily-puzzle-schedule --project connactor-497019 --location us-central1
```

## Reading logs

```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=connactor-daily-puzzle" \
  --project connactor-497019 --limit 50 --order desc --format='value(timestamp,textPayload)'
```
