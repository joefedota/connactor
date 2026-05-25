# Replacing today's daily puzzle

Use this runbook when you need to swap out the active daily puzzle mid-day — for example, if the chosen pair is too easy/hard, a path bug was found, or you want to test the replacement flow.

---

## What happens when you replace a puzzle

1. The old `puzzles` row is **unmarked** (`is_daily = FALSE, scheduled_date = NULL`) — it stays in the DB as a regular puzzle and is never deleted.
2. A new pair is picked and **upserted** as the daily for the target date.
3. Any user who had **already completed** the old daily retains their `game_completions` row, but it now points to a non-daily `puzzle_id`. `GET /daily` returns the new `puzzle_id`, so their completion is invisible to that check — they will see the new puzzle as unplayed and can play again.
4. Users with the old puzzle still open in their browser will seamlessly start the new puzzle on their next page load or refresh (the store rehydrates from `GET /daily`).

---

## Method 1 — gcloud CLI

```bash
gcloud run jobs execute connactor-daily-puzzle \
  --project connactor-497019 \
  --region us-central1 \
  --args="pipeline/generate_daily_puzzle.py,--date,YYYY-MM-DD,--force" \
  --wait
```

Replace `YYYY-MM-DD` with the target date (today's UTC date to replace the active puzzle).

> **Important:** `--args` overrides the job's default args completely, so you must always include `pipeline/generate_daily_puzzle.py` as the first comma-separated value. The values must be comma-separated with no spaces around commas.

Example — replace today's puzzle (2026-05-25):
```bash
gcloud run jobs execute connactor-daily-puzzle \
  --project connactor-497019 \
  --region us-central1 \
  --args="pipeline/generate_daily_puzzle.py,--date,2026-05-25,--force" \
  --wait
```

`--wait` blocks until the job finishes and exits non-zero on failure, so you'll know immediately if something went wrong.

---

## Method 2 — Cloud Console

1. Go to [Cloud Run → Jobs](https://console.cloud.google.com/run/jobs?project=connactor-497019)
2. Click **connactor-daily-puzzle**
3. Click **Execute** (top right)
4. Under **Container overrides → Arguments**, enter each argument on its own line:
   ```
   pipeline/generate_daily_puzzle.py
   --date
   2026-05-25
   --force
   ```
5. Click **Execute**
6. Watch the **Executions** tab — a green tick means success, red X means failure

---

## Expected log output

A successful run looks like this in Cloud Logging:

```
INFO Daily puzzle for 2026-05-25 already exists — forcing regeneration.
INFO Picking pair for 2026-05-25 (excluding N previously used pairs) ...
INFO Selected: source=<tmdb_id> target=<tmdb_id> hops=<N>
INFO Daily puzzle for 2026-05-25 saved.
Container called exit(0).
```

If it says `Daily puzzle for YYYY-MM-DD already exists — skipping.` and exits cleanly, you forgot `--force`.

To tail logs after the fact:
```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=connactor-daily-puzzle" \
  --project connactor-497019 \
  --limit 30 \
  --order desc \
  --format="value(timestamp, textPayload)"
```

---

## Verifying it worked

**1. Check the puzzles table directly via psql / Neon console:**
```sql
SELECT puzzle_id, source_id, target_id, optimal_hops, is_daily, scheduled_date
FROM puzzles
WHERE scheduled_date = '2026-05-25'
ORDER BY created_at DESC;
```
You should see exactly one row with `is_daily = TRUE`. Any previous row for the same date should have `is_daily = FALSE` and `scheduled_date = NULL`.

**2. Hit the API:**
```bash
curl -s https://connactor.com/daily | python3 -m json.tool
```
The `source` and `target` fields should show the new actor pair. `already_completed` should be `false` (unless you happened to have completed the new pair as a random game previously).

**3. Open the app in a fresh private/incognito window:**
Navigate to `connactor.com/daily` and confirm the actor pair shown matches the new puzzle.

---

## If the job fails

- **Exit code 2** — argument parsing error. Most likely the `--args` format was wrong (spaces instead of commas, or the script path was omitted). Re-check the exact format above.
- **Exit code 1** — the script ran but couldn't find a valid pair after 50 attempts. This is rare. Re-run — it picks randomly, so a second attempt usually succeeds.
- **Connection error** — Neo4j or Postgres unreachable. Check that the Neo4j VM is running and that the `DATABASE_URL` secret is correct.

View execution details:
```bash
gcloud run jobs executions list \
  --job connactor-daily-puzzle \
  --project connactor-497019 \
  --region us-central1 \
  --limit 5
```
