# GCP Secret Manager Setup

Run these commands once. Values are stored in Secret Manager only — never in `.env` files, GitHub secrets, or source code.

## Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- Project set: `gcloud config set project connactor-497019`

---

## 1. Enable Secret Manager API

```bash
gcloud services enable secretmanager.googleapis.com --project connactor-497019
```

---

## 2. Create the Cloud Run Service Account

```bash
gcloud iam service-accounts create connactor-api \
  --project connactor-497019 \
  --display-name "Connactor API (Cloud Run)"
```

---

## 3. Create Secrets

```bash
echo -n "YOUR_TMDB_TOKEN" | gcloud secrets create TMDB_API_READ_TOKEN \
  --project connactor-497019 --data-file=-

echo -n "YOUR_NEO4J_PASSWORD" | gcloud secrets create NEO4J_PASSWORD \
  --project connactor-497019 --data-file=-
```

Replace `YOUR_TMDB_TOKEN` with your TMDB API Read Access Token (themoviedb.org → Settings → API) and `YOUR_NEO4J_PASSWORD` with a strong password you'll use for the production Neo4j instance.

---

## 4. Grant the Service Account Access

```bash
for SECRET in TMDB_API_READ_TOKEN NEO4J_PASSWORD; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --project connactor-497019 \
    --member "serviceAccount:connactor-api@connactor-497019.iam.gserviceaccount.com" \
    --role "roles/secretmanager.secretAccessor"
done
```

---

## 5. Verify

```bash
gcloud secrets versions access latest \
  --secret TMDB_API_READ_TOKEN \
  --project connactor-497019
```

Should print the token value.

---

## Rotating a Secret

```bash
echo -n "NEW_VALUE" | gcloud secrets versions add SECRET_NAME \
  --project connactor-497019 --data-file=-
```

Cloud Run automatically picks up the new version on the next request (secrets are resolved at request time, not at deploy time).
