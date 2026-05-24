#!/usr/bin/env python3
"""
Weekly cost + usage report (Issue #47).

Pulls GCP spend (BigQuery billing export), Cloudflare subscription cost
(REST), and Cloudflare Web Analytics visitor counts (GraphQL). Renders a
single HTML email, POSTs it to Resend.

Designed to run weekly as `connactor-cost-report` Cloud Run Job. See
docs/ops/setup-cost-report.md.

Local dry-run (prints HTML, skips email):
    cd backend && uv run python scripts/cost_report.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from google.cloud import bigquery

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from settings import settings  # noqa: E402

logger = logging.getLogger(__name__)

# Date connactor.com first served traffic via Cloudflare. Used as the
# "cumulative since launch" anchor for usage analytics.
LAUNCH_DATE = date(2026, 5, 23)

# Threshold for flagging a week-over-week change as notable (cost ↑ or usage ↓).
WOW_FLAG_THRESHOLD = 0.25

CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
RESEND_API = "https://api.resend.com/emails"


# ---------- data classes ----------

@dataclass
class CostRow:
    service: str
    this_week: float
    prior_week: float

    @property
    def delta_pct(self) -> float | None:
        if self.prior_week <= 0.01:
            return None  # avoid divide-by-zero / explosive deltas on tiny baselines
        return (self.this_week - self.prior_week) / self.prior_week

    @property
    def flagged(self) -> bool:
        d = self.delta_pct
        return d is not None and d > WOW_FLAG_THRESHOLD


@dataclass
class DailyUsage:
    day: date
    visitors: int
    pageviews: int


# ---------- GCP cost (BigQuery) ----------

def fetch_gcp_costs(client: bigquery.Client, start: date, prior_start: date, end: date) -> list[CostRow]:
    """
    Return a list of CostRow per GCP service, summing weekly spend net of credits.
    """
    table_id = f"{settings.gcp_project}.{settings.billing_dataset}.{settings.billing_table}"
    query = f"""
        SELECT
          service.description AS service,
          SUM(IF(usage_start_time >= @start AND usage_start_time < @end,
                 cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0),
                 0)) AS usd_this_week,
          SUM(IF(usage_start_time >= @prior_start AND usage_start_time < @start,
                 cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0),
                 0)) AS usd_prior_week
        FROM `{table_id}`
        WHERE usage_start_time >= @prior_start AND usage_start_time < @end
        GROUP BY service
        HAVING usd_this_week > 0 OR usd_prior_week > 0
        ORDER BY usd_this_week DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "TIMESTAMP", datetime.combine(start, datetime.min.time(), timezone.utc)),
            bigquery.ScalarQueryParameter("prior_start", "TIMESTAMP", datetime.combine(prior_start, datetime.min.time(), timezone.utc)),
            bigquery.ScalarQueryParameter("end", "TIMESTAMP", datetime.combine(end, datetime.min.time(), timezone.utc)),
        ]
    )
    rows = client.query(query, job_config=job_config).result()
    return [
        CostRow(service=r["service"], this_week=float(r["usd_this_week"]), prior_week=float(r["usd_prior_week"]))
        for r in rows
    ]


# ---------- Cloudflare cost (subscriptions) ----------

def fetch_cloudflare_cost(account_id: str, token: str) -> CostRow | None:
    """
    Sum active Cloudflare subscriptions, expressed as a weekly equivalent.
    Returns None on API failure (so the report still ships).
    """
    if not (account_id and token):
        logger.warning("Cloudflare credentials missing; skipping CF cost row")
        return None
    try:
        r = httpx.get(
            f"{CLOUDFLARE_API}/accounts/{account_id}/subscriptions",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        r.raise_for_status()
        subs = r.json().get("result", []) or []
    except Exception as e:
        logger.exception("Cloudflare subscriptions API failed: %s", e)
        return CostRow(service="Cloudflare (data unavailable)", this_week=0.0, prior_week=0.0)

    weekly = 0.0
    for sub in subs:
        price = float(sub.get("rated_price", {}).get("value") or sub.get("price") or 0.0)
        freq = (sub.get("frequency") or "monthly").lower()
        if freq == "monthly":
            weekly += price * 7 / 30
        elif freq == "yearly":
            weekly += price / 52
        elif freq == "quarterly":
            weekly += price / 13
        elif freq == "weekly":
            weekly += price
    return CostRow(service="Cloudflare", this_week=weekly, prior_week=weekly)


# ---------- Cloudflare usage (GraphQL Analytics) ----------

_GRAPHQL = """
query ($zone: String!, $start: Date!, $end: Date!) {
  viewer {
    zones(filter: {zoneTag: $zone}) {
      httpRequests1dGroups(
        limit: 1000
        filter: {date_geq: $start, date_lt: $end}
        orderBy: [date_ASC]
      ) {
        dimensions { date }
        uniq { uniques }
        sum { pageViews }
      }
    }
  }
}
"""


def _cloudflare_graphql(zone_tag: str, token: str, start: date, end: date) -> list[DailyUsage]:
    """Returns one DailyUsage per day in [start, end)."""
    if not (zone_tag and token):
        return []
    try:
        r = httpx.post(
            f"{CLOUDFLARE_API}/graphql",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "query": _GRAPHQL,
                "variables": {"zone": zone_tag, "start": start.isoformat(), "end": end.isoformat()},
            },
            timeout=20.0,
        )
        r.raise_for_status()
        zones = r.json().get("data", {}).get("viewer", {}).get("zones", [])
        if not zones:
            return []
        groups = zones[0].get("httpRequests1dGroups", []) or []
    except Exception as e:
        logger.exception("Cloudflare analytics API failed: %s", e)
        return []

    return [
        DailyUsage(
            day=date.fromisoformat(g["dimensions"]["date"]),
            visitors=int(g["uniq"]["uniques"] or 0),
            pageviews=int(g["sum"]["pageViews"] or 0),
        )
        for g in groups
    ]


def fetch_usage(zone_tag: str, token: str, start: date, prior_start: date, end: date) -> tuple[list[DailyUsage], int, int]:
    """
    Returns (last-7-days daily breakdown, prior_week_visitors, cumulative_visits_since_launch).
    """
    daily = _cloudflare_graphql(zone_tag, token, start, end)
    prior = _cloudflare_graphql(zone_tag, token, prior_start, start)
    cumulative = _cloudflare_graphql(zone_tag, token, LAUNCH_DATE, end)

    prior_visitors = sum(d.visitors for d in prior)
    cumulative_visits = sum(d.visitors for d in cumulative)
    return daily, prior_visitors, cumulative_visits


# ---------- HTML render ----------

def _fmt_pct(p: float | None) -> str:
    if p is None:
        return "—"
    sign = "+" if p >= 0 else ""
    return f"{sign}{p*100:.0f}%"


def render_html(
    cost_rows: list[CostRow],
    daily: list[DailyUsage],
    this_visitors: int,
    prior_visitors: int,
    cumulative: int,
    start: date,
    end: date,
) -> str:
    visitors_delta = None
    if prior_visitors > 0:
        visitors_delta = (this_visitors - prior_visitors) / prior_visitors
    visitors_drop_flagged = visitors_delta is not None and visitors_delta < -WOW_FLAG_THRESHOLD

    total_this = sum(r.this_week for r in cost_rows)
    total_prior = sum(r.prior_week for r in cost_rows)
    total_delta = ((total_this - total_prior) / total_prior) if total_prior > 0.01 else None

    pageviews_total = sum(d.pageviews for d in daily)

    flag_style = "background:#fff8d6;"

    cost_html = "".join(
        f"<tr style='{flag_style if r.flagged else ''}'>"
        f"<td>{'⚠ ' if r.flagged else ''}{r.service}</td>"
        f"<td style='text-align:right'>${r.this_week:,.2f}</td>"
        f"<td style='text-align:right'>${r.prior_week:,.2f}</td>"
        f"<td style='text-align:right'>{_fmt_pct(r.delta_pct)}</td>"
        f"</tr>"
        for r in cost_rows
    )

    daily_html = "".join(
        f"<tr><td>{d.day.isoformat()}</td>"
        f"<td style='text-align:right'>{d.visitors:,}</td>"
        f"<td style='text-align:right'>{d.pageviews:,}</td></tr>"
        for d in daily
    )

    return f"""<!doctype html>
<html><body style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#222;max-width:640px;margin:0 auto;padding:24px;">
  <h2 style="margin:0 0 4px;">Connactor weekly report</h2>
  <div style="color:#888;margin-bottom:24px;">Week of {start.isoformat()} – {(end - timedelta(days=1)).isoformat()} (UTC)</div>

  <h3 style="margin-top:24px;">Usage</h3>
  <p style="margin:4px 0;">
    <strong>Last 7 days:</strong> {this_visitors:,} visitors · {pageviews_total:,} pageviews
    <span style="color:{'#cc0000' if visitors_drop_flagged else '#888'};">
      ({'⚠ ' if visitors_drop_flagged else ''}{_fmt_pct(visitors_delta)} WoW)
    </span>
  </p>
  <p style="margin:4px 0;">
    <strong>Cumulative since launch ({LAUNCH_DATE.isoformat()}):</strong> {cumulative:,} visits
  </p>
  <table cellspacing="0" cellpadding="6" style="border-collapse:collapse;width:100%;margin-top:12px;font-size:14px;">
    <thead><tr style="background:#f5f5f5;text-align:left;">
      <th>Date</th><th style="text-align:right">Visitors</th><th style="text-align:right">Pageviews</th>
    </tr></thead>
    <tbody>{daily_html or '<tr><td colspan="3" style="color:#888;font-style:italic;">No data — is Cloudflare Web Analytics enabled?</td></tr>'}</tbody>
  </table>

  <h3 style="margin-top:32px;">Cost</h3>
  <table cellspacing="0" cellpadding="6" style="border-collapse:collapse;width:100%;font-size:14px;">
    <thead><tr style="background:#f5f5f5;text-align:left;">
      <th>Service</th><th style="text-align:right">This week</th><th style="text-align:right">Prior week</th><th style="text-align:right">Δ</th>
    </tr></thead>
    <tbody>
      {cost_html or '<tr><td colspan="4" style="color:#888;font-style:italic;">No cost rows — is the BigQuery billing export populated?</td></tr>'}
      <tr style="border-top:2px solid #888;font-weight:bold;">
        <td>TOTAL</td>
        <td style="text-align:right">${total_this:,.2f}</td>
        <td style="text-align:right">${total_prior:,.2f}</td>
        <td style="text-align:right">{_fmt_pct(total_delta)}</td>
      </tr>
    </tbody>
  </table>

  <p style="color:#888;font-size:12px;margin-top:32px;">
    Generated by <code>connactor-cost-report</code>. <code>⚠</code> = WoW change exceeds ±25%.
  </p>
</body></html>"""


# ---------- email ----------

def send_email(html: str, subject: str) -> None:
    r = httpx.post(
        RESEND_API,
        headers={"Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json"},
        json={
            "from": settings.report_sender,
            "to": [settings.report_recipient],
            "subject": subject,
            "html": html,
        },
        timeout=15.0,
    )
    if r.status_code >= 400:
        logger.error("Resend rejected the email: %d %s", r.status_code, r.text)
        r.raise_for_status()
    logger.info("Sent email id=%s", r.json().get("id"))


# ---------- main ----------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Connactor weekly cost + usage report.")
    parser.add_argument("--dry-run", action="store_true", help="Print HTML to stdout, do not send email.")
    args = parser.parse_args()

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=7)
    prior_start = end - timedelta(days=14)

    logger.info("Reporting period: %s to %s (prior week from %s)", start, end, prior_start)

    bq = bigquery.Client(project=settings.gcp_project)
    cost_rows = fetch_gcp_costs(bq, start=start, prior_start=prior_start, end=end)
    cf_cost = fetch_cloudflare_cost(settings.cloudflare_account_id, settings.cloudflare_api_token)
    if cf_cost:
        cost_rows.append(cf_cost)

    daily, prior_visitors, cumulative = fetch_usage(
        settings.cloudflare_zone_tag, settings.cloudflare_api_token,
        start=start, prior_start=prior_start, end=end,
    )
    this_visitors = sum(d.visitors for d in daily)

    html = render_html(cost_rows, daily, this_visitors, prior_visitors, cumulative, start, end)
    subject = f"Connactor weekly report — {start.isoformat()}"

    if args.dry_run:
        print(html)
        return

    send_email(html, subject)


if __name__ == "__main__":
    main()
