# Daily cost + usage report

A Cloud Run Job (`connactor-cost-report`) builds a rolling-7-day per-service spend breakdown, adds Cloudflare Web Analytics visitor counts, and emails the result via Resend. Cloud Scheduler triggers it daily. Same image as the API/pipeline — only the entrypoint differs. (Resend free tier covers 100 sends/day, daily reports use ~1.)

Sources:
- **GCP cost** — BigQuery billing export (`gcp_billing_export_resource_v1_*` table)
- **Cloudflare cost** — `/accounts/{id}/subscriptions` REST API
- **Usage** — Cloudflare GraphQL Analytics API (`httpRequests1dGroups`)
- **Delivery** — Resend HTTP API → joefedota@gmail.com

## One-time setup

### 1. Enable BigQuery billing export

GCP Console → **Billing → joefedota-account (017EE0-4F04E9-9FCF85) → Billing export**.

Enable **Detailed usage cost** export to a new BigQuery dataset:
- Project: `connactor-497019`
- Dataset: `billing_export`
- Location: `US`

First data lands ~24h after enabling; backfill ~6 months by default. Table will be named like `gcp_billing_export_resource_v1_017EE0_4F04E9_9FCF85`.

### 2. Enable Cloudflare Web Analytics

Cloudflare dashboard → **Analytics & Logs → Web Analytics**. For each connactor.com zone, click "Enable Web Analytics." Sites under Cloudflare proxy collect at the edge — no JS snippet required. Metrics start populating within an hour.

### 3. Cloudflare API token

Cloudflare dashboard → **My Profile → API Tokens → Create Token → Create Custom Token**:

| Permission | Resource | Access |
|---|---|---|
| Account → Billing | This account | Read |
| Account → Account Settings | This account | Read |
| Account → Account Analytics | This account | Read |
| Zone → Analytics | All zones | Read |

Store in Secret Manager:
```bash
gcloud secrets create cloudflare-api-token \
  --project connactor-497019 \
  --replication-policy automatic \
  --data-file - <<< "<paste-token-here>"
```

Note the **Account ID** (Cloudflare → right sidebar of any zone) and **Zone tag** for connactor.com — needed as env vars.

### 4. Resend account

1. Sign up at https://resend.com (free tier 100 emails/day).
2. (Recommended) Verify the `connactor.com` sender domain — adds SPF/DKIM records to Cloudflare DNS for deliverability.
3. **API Keys → Create API Key** (read-only "send" scope is fine).
4. Store in Secret Manager:
   ```bash
   gcloud secrets create resend-api-key \
     --project connactor-497019 \
     --replication-policy automatic \
     --data-file - <<< "<paste-key-here>"
   ```

### 5. Service account permissions

The existing `connactor-api@connactor-497019.iam.gserviceaccount.com` SA needs:

```bash
SA=connactor-api@connactor-497019.iam.gserviceaccount.com

# Query the billing export
gcloud projects add-iam-policy-binding connactor-497019 \
  --member "serviceAccount:$SA" --role roles/bigquery.jobUser
gcloud projects add-iam-policy-binding connactor-497019 \
  --member "serviceAccount:$SA" --role roles/bigquery.dataViewer

# Read the new secrets
for secret in cloudflare-api-token resend-api-key; do
  gcloud secrets add-iam-policy-binding $secret \
    --project connactor-497019 \
    --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor
done
```

## Create the job

```bash
gcloud run jobs create connactor-cost-report \
  --project connactor-497019 \
  --image us-central1-docker.pkg.dev/connactor-497019/connactor/api:latest \
  --region us-central1 \
  --service-account connactor-api@connactor-497019.iam.gserviceaccount.com \
  --set-secrets "CLOUDFLARE_API_TOKEN=cloudflare-api-token:latest,RESEND_API_KEY=resend-api-key:latest" \
  --set-env-vars "GCP_PROJECT=connactor-497019,BILLING_DATASET=billing_export,BILLING_TABLE=gcp_billing_export_resource_v1_017EE0_4F04E9_9FCF85,CLOUDFLARE_ACCOUNT_ID=<account-id>,CLOUDFLARE_ZONE_TAG=<zone-tag>,REPORT_RECIPIENT=joefedota@gmail.com,REPORT_SENDER=reports@connactor.com" \
  --memory 512Mi \
  --cpu 1 \
  --task-timeout 600 \
  --max-retries 1 \
  --command python \
  --args scripts/cost_report.py
```

No VPC egress flags needed — this job hits public APIs only (BigQuery, Cloudflare, Resend).

## Schedule daily (14:00 UTC = 10am Eastern / 7am Pacific during DST; 9am ET / 6am PT in winter)

```bash
gcloud run jobs add-iam-policy-binding connactor-cost-report \
  --project connactor-497019 --region us-central1 \
  --member "serviceAccount:connactor-scheduler@connactor-497019.iam.gserviceaccount.com" \
  --role roles/run.invoker

PROJECT_NUMBER=$(gcloud projects describe connactor-497019 --format='value(projectNumber)')

gcloud scheduler jobs create http connactor-cost-report-daily \
  --project connactor-497019 \
  --location us-central1 \
  --schedule "0 14 * * *" \
  --time-zone "UTC" \
  --http-method POST \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/connactor-cost-report:run" \
  --oauth-service-account-email connactor-scheduler@connactor-497019.iam.gserviceaccount.com
```

(Reuses the existing `connactor-scheduler` SA from the pipeline cron.)

## Manual operations

Run now:
```bash
gcloud run jobs execute connactor-cost-report \
  --project connactor-497019 --region us-central1
```

Dry-run locally (renders HTML to stdout, doesn't send):
```bash
cd backend && uv run python scripts/cost_report.py --dry-run
```

Pause / resume:
```bash
gcloud scheduler jobs pause connactor-cost-report-daily --project connactor-497019 --location us-central1
gcloud scheduler jobs resume connactor-cost-report-daily --project connactor-497019 --location us-central1
```

Reading logs:
```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=connactor-cost-report" \
  --project connactor-497019 --limit 50 --order desc --format='value(timestamp,textPayload)'
```
