# Workload Identity Federation for GitHub Actions

One-time setup so the `.github/workflows/deploy.yml` workflow can deploy to GCP without storing a long-lived service-account JSON key in GitHub secrets.

GitHub Actions presents an OIDC token to GCP; the Workload Identity Pool verifies it came from this specific repo and lets the workflow impersonate the existing `connactor-api` service account.

## Prerequisites

- `gcloud` CLI authenticated (`gcloud auth login`) with project owner / IAM admin
- `gh` CLI authenticated (`gh auth login`)
- `connactor-api` service account already exists — see [`setup-secrets.md`](./setup-secrets.md)

---

## 1. Enable the IAM Credentials API

Required for SA impersonation via WIF.

```bash
gcloud services enable iamcredentials.googleapis.com --project connactor-497019
```

---

## 2. Create the Workload Identity Pool

```bash
gcloud iam workload-identity-pools create github \
  --project connactor-497019 \
  --location global \
  --display-name "GitHub Actions"
```

---

## 3. Create the OIDC provider

Scoped to `joefedota/connactor` only — tokens from any other GitHub repo are rejected.

```bash
gcloud iam workload-identity-pools providers create-oidc github \
  --project connactor-497019 \
  --location global \
  --workload-identity-pool github \
  --display-name "GitHub" \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition "assertion.repository == 'joefedota/connactor'"
```

---

## 4. Let the GitHub identity impersonate `connactor-api`

```bash
PROJECT_NUMBER=$(gcloud projects describe connactor-497019 --format='value(projectNumber)')

gcloud iam service-accounts add-iam-policy-binding \
  connactor-api@connactor-497019.iam.gserviceaccount.com \
  --project connactor-497019 \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/joefedota/connactor"
```

---

## 5. Grant deploy-side roles to the service account

The `connactor-api` SA already has runtime roles (`secretmanager.secretAccessor` on the two secrets, `storage.objectAdmin` on the GCS bucket). It now also needs roles to build images and update Cloud Run.

```bash
for role in \
  roles/run.developer \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/storage.objectViewer \
  roles/logging.logWriter \
  roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding connactor-497019 \
    --member "serviceAccount:connactor-api@connactor-497019.iam.gserviceaccount.com" \
    --role "$role"
done
```

Why `iam.serviceAccountUser` on itself: `gcloud builds submit` runs Cloud Build as a service account and the deploying identity needs `actAs` permission on that SA. Granting `serviceAccountUser` lets the SA act on itself, which is the simplest path.

---

## 6. Tell GitHub the project number

The deploy workflow references `${{ vars.GCP_PROJECT_NUMBER }}` in its WIF audience URL. Set it as a repo-level variable:

```bash
PROJECT_NUMBER=$(gcloud projects describe connactor-497019 --format='value(projectNumber)')
gh variable set GCP_PROJECT_NUMBER --body "$PROJECT_NUMBER" --repo joefedota/connactor
```

Verify:

```bash
gh variable list --repo joefedota/connactor
```

---

## Verification

After merging the workflow files to `main`:

1. The `Deploy` workflow run should reach the `auth` step and succeed (the action prints `Successfully authenticated as connactor-api@...`).
2. `gcloud builds submit` produces a digest tagged `:<sha>` and `:latest`:
   ```bash
   gcloud artifacts docker images list \
     us-central1-docker.pkg.dev/connactor-497019/connactor/api --include-tags
   ```
3. The Cloud Run service points at the new SHA:
   ```bash
   gcloud run services describe connactor-api \
     --project connactor-497019 --region us-central1 \
     --format='value(spec.template.spec.containers[0].image)'
   ```
4. Same for the pipeline job:
   ```bash
   gcloud run jobs describe connactor-pipeline-full \
     --project connactor-497019 --region us-central1 \
     --format='value(template.template.containers[0].image)'
   ```

---

## Rollback

Every deploy tags the image with the commit SHA, so you can pin to any prior revision:

```bash
OLD_SHA=<commit-sha-to-roll-back-to>
gcloud run services update connactor-api \
  --project connactor-497019 --region us-central1 \
  --image "us-central1-docker.pkg.dev/connactor-497019/connactor/api:${OLD_SHA}"

gcloud run jobs update connactor-pipeline-full \
  --project connactor-497019 --region us-central1 \
  --image "us-central1-docker.pkg.dev/connactor-497019/connactor/api:${OLD_SHA}"
```
