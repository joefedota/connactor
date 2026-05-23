# Cloudflare Pages + Custom Domain Setup

One-time setup to put the frontend on `https://connactor.com` and the API on `https://api.connactor.com`. Cloudflare Pages handles the frontend auto-deploy from `main`; Cloud Run's custom domain mapping handles the API.

## Architecture

```
User
 │
 ├─► https://connactor.com           ──► Cloudflare Pages (auto-deploy from main)
 │                                          └─► static React bundle
 │
 └─► https://api.connactor.com       ──► Cloud Run custom domain mapping
                                            └─► connactor-api service
                                                  └─► VM Neo4j over VPC
```

The frontend bakes `VITE_API_URL=https://api.connactor.com` into the bundle at build time, so the SPA talks directly to the API host.

## Prerequisites

- `gcloud` CLI authenticated as a project owner
- Cloudflare account at `dash.cloudflare.com`
- Backend already on Cloud Run via [`setup-cloudrun.md`](./setup-cloudrun.md)

---

## 1. Register `connactor.com` (~5 min)

Cloudflare dash → **Domain Registration** → **Register Domain** → search `connactor.com` → complete checkout. DNS is auto-managed in the same Cloudflare account.

---

## 2. Verify domain ownership in Google Search Console (~3 min)

Cloud Run won't map a subdomain to a domain it doesn't think you own.

1. Go to https://search.google.com/search-console
2. **Add Property** → **Domain** → enter `connactor.com`
3. Google gives a TXT record value like `google-site-verification=abc123...`
4. In Cloudflare DNS (`connactor.com` → DNS → Add record):
   - Type: `TXT`
   - Name: `@`
   - Content: paste the full `google-site-verification=...` value
5. Wait ~30 sec, return to Search Console, click **Verify**

---

## 3. Create the Cloud Run domain mapping

```bash
gcloud beta run domain-mappings create \
  --service=connactor-api \
  --domain=api.connactor.com \
  --region=us-central1 \
  --project=connactor-497019
```

Output includes the DNS record to add. For `api.connactor.com` mapping to a Cloud Run service, the output is consistently:

```
NAME  RECORD TYPE  CONTENTS
api   CNAME        ghs.googlehosted.com.
```

If `gcloud beta` isn't installed:

```bash
gcloud components install beta --quiet
```

---

## 4. Add the API CNAME in Cloudflare DNS

Cloudflare dash → connactor.com → DNS → Records → Add record:

| Type | Name | Target | Proxy status | TTL |
|---|---|---|---|---|
| CNAME | `api` | `ghs.googlehosted.com` | **DNS only** (gray cloud) | Auto |

**Critical:** proxy status must be **DNS only** for the API. If proxied (orange cloud), Cloudflare terminates SSL with its cert and Cloud Run never sees the request, so Google's managed cert never provisions and CORS/headers from Cloud Run get rewritten.

---

## 5. Set up Cloudflare Pages (~5 min)

Cloudflare dash → **Workers & Pages** → **Create application** → **Pages** tab → **Connect to Git**:

- Select `joefedota/connactor` (authorize the Cloudflare GitHub app on first use)
- Production branch: `main`

Build configuration:
- **Framework preset**: None
- **Root directory** (sometimes labeled "Path"): `frontend`
- **Build command**: `npm run build`
- **Build output directory**: `dist`
- **Environment variables** (Production):
  - `VITE_API_URL` = `https://api.connactor.com`

Save and Deploy. First build takes ~1 min and produces a `connactor-XXXX.pages.dev` URL.

If the dashboard pushes you to the Workers Builds flow instead of Pages (newer UI), the equivalent setup requires a `wrangler.toml` in `frontend/` with `[assets] directory = "./dist"`. The Pages tab is the simpler path.

---

## 6. Attach `connactor.com` to the Pages project (~2 min)

In the Pages project → **Custom domains** → **Set up a custom domain** → enter `connactor.com`. Cloudflare auto-creates the apex CNAME (using CNAME flattening) and provisions Universal SSL.

Optional: add `www.connactor.com` as a second custom domain.

DNS record auto-created by Cloudflare for the apex:

| Type | Name | Target | Proxy status |
|---|---|---|---|
| CNAME | `@` | `connactor.pages.dev` | **Proxied** (orange cloud) |

(For Pages, proxied is correct — Cloudflare's CDN serves the static bundle.)

---

## 7. Verify

```bash
# Cloud Run cert may take 5-15 min after step 4
curl -sI https://api.connactor.com/health
curl -s  https://api.connactor.com/health    # expects {"status":"ok","actors":...}
curl -sI https://connactor.com               # expects 200, served by Cloudflare
```

Open `https://connactor.com` in a browser — game loads, autocomplete works, play-through completes.

---

## Updating the Pages project

Pushes to `main` auto-trigger a Pages build (~1 min). Watch builds at:

```
dash.cloudflare.com → Workers & Pages → connactor → Deployments
```

To change `VITE_API_URL` (e.g., point to a staging API):

- Pages project → Settings → Environment variables → edit → trigger a redeploy

---

## Troubleshooting

**`api.connactor.com` returns NXDOMAIN** → the api CNAME from step 4 isn't in Cloudflare DNS yet. Add it.

**`api.connactor.com` returns 5xx after the CNAME is live** → cert hasn't provisioned. Check:
```bash
gcloud beta run domain-mappings describe \
  --domain=api.connactor.com --region=us-central1 --project=connactor-497019 \
  --format='value(status.conditions)'
```
Wait until `CertificateProvisioned: True`. If stuck >30 min, double-check the CNAME is **DNS only** (not proxied).

**Frontend loads but API calls fail with CORS error** → CORS in `backend/app/main.py` is `allow_origins=["*"]`, which works without modification. If you later restrict it, add `https://connactor.com` to the allow list.

**Old Pages deployment cached** → Cloudflare's CDN caches aggressively. Force-refresh in browser (Cmd-Shift-R) or purge cache in the Cloudflare zone settings.
