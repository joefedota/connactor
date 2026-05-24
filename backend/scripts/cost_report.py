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
from google.api_core.exceptions import GoogleAPIError, NotFound
from google.cloud import bigquery

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from settings import settings  # noqa: E402

logger = logging.getLogger(__name__)

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

def fetch_gcp_totals(client: bigquery.Client, end: date) -> tuple[float, float]:
    """
    Returns (month_to_date_usd, year_to_date_usd) for all GCP services combined,
    net of credits. Bounded by `end` (exclusive) so the function is deterministic
    for a given run.
    """
    table_id = f"{settings.gcp_project}.{settings.billing_dataset}.{settings.billing_table}"
    mtd_start = end.replace(day=1)
    ytd_start = end.replace(month=1, day=1)
    query = f"""
        SELECT
          SUM(IF(usage_start_time >= @mtd_start,
                 cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0),
                 0)) AS mtd,
          SUM(IF(usage_start_time >= @ytd_start,
                 cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0),
                 0)) AS ytd
        FROM `{table_id}`
        WHERE usage_start_time >= @ytd_start AND usage_start_time < @end
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("mtd_start", "TIMESTAMP", datetime.combine(mtd_start, datetime.min.time(), timezone.utc)),
            bigquery.ScalarQueryParameter("ytd_start", "TIMESTAMP", datetime.combine(ytd_start, datetime.min.time(), timezone.utc)),
            bigquery.ScalarQueryParameter("end", "TIMESTAMP", datetime.combine(end, datetime.min.time(), timezone.utc)),
        ]
    )
    try:
        row = next(iter(client.query(query, job_config=job_config).result()))
    except (NotFound, GoogleAPIError) as e:
        logger.warning("BigQuery totals query failed (likely billing export not yet populated): %s", e)
        return 0.0, 0.0
    return float(row["mtd"] or 0.0), float(row["ytd"] or 0.0)


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
    try:
        rows = client.query(query, job_config=job_config).result()
        return [
            CostRow(service=r["service"], this_week=float(r["usd_this_week"]), prior_week=float(r["usd_prior_week"]))
            for r in rows
        ]
    except (NotFound, GoogleAPIError) as e:
        logger.warning("BigQuery cost query failed (likely billing export not yet populated): %s", e)
        return []


# ---------- Cloudflare cost (subscriptions) ----------

def fetch_cloudflare_cost(account_id: str, token: str) -> tuple[CostRow | None, float]:
    """
    Sum active Cloudflare subscriptions.

    Returns (weekly_row, monthly_total_usd):
    - weekly_row is what goes in the per-service table
    - monthly_total_usd is used to prorate MTD/YTD across services

    Returns (None, 0.0) when credentials are missing; returns a 'data unavailable'
    row with monthly=0 on API failure (so the report still ships).
    """
    if not (account_id and token):
        logger.warning("Cloudflare credentials missing; skipping CF cost row")
        return None, 0.0
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
        return CostRow(service="Cloudflare (data unavailable)", this_week=0.0, prior_week=0.0), 0.0

    monthly = 0.0
    for sub in subs:
        price = float(sub.get("rated_price", {}).get("value") or sub.get("price") or 0.0)
        freq = (sub.get("frequency") or "monthly").lower()
        if freq == "monthly":
            monthly += price
        elif freq == "yearly":
            monthly += price / 12
        elif freq == "quarterly":
            monthly += price / 3
        elif freq == "weekly":
            monthly += price * 30 / 7
    weekly = monthly * 7 / 30
    return CostRow(service="Cloudflare", this_week=weekly, prior_week=weekly), monthly


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


# ---------- HTML render ----------

def _fmt_pct(p: float | None) -> str:
    if p is None:
        return "—"
    sign = "+" if p >= 0 else ""
    return f"{sign}{p*100:.0f}%"


def render_chart(daily: list[DailyUsage]) -> str:
    """
    Bar chart of daily visitors. Renders as a single-row HTML table — every
    email client honors this without inline CSS quirks. Each cell holds:
    count label (top), bar (background-colored div with pixel height), day-of-week (bottom).
    """
    if not daily:
        return ""
    max_val = max(d.visitors for d in daily) or 1
    bars = []
    for d in daily:
        h = max(2, int(d.visitors / max_val * 100))  # min 2px so empty days are visible
        bars.append(
            f'<td valign="bottom" style="padding:0 4px;text-align:center;min-width:40px;">'
            f'<div style="font-size:11px;color:#444;font-weight:600;margin-bottom:4px;">{d.visitors}</div>'
            f'<div style="background:#C68DFE;width:26px;height:{h}px;margin:0 auto;border-radius:3px 3px 0 0;"></div>'
            f'<div style="font-size:10px;color:#888;margin-top:6px;">{d.day.strftime("%a")}</div>'
            f'<div style="font-size:9px;color:#bbb;">{d.day.strftime("%m/%d")}</div>'
            f'</td>'
        )
    return (
        '<table cellspacing="0" cellpadding="0" align="center" '
        'style="border-collapse:collapse;margin:16px auto;">'
        f'<tr style="vertical-align:bottom;">{"".join(bars)}</tr>'
        '</table>'
    )


def render_html(
    cost_rows: list[CostRow],
    daily: list[DailyUsage],
    avg_dau_visitors: float,
    avg_dau_pageviews: float,
    avg_dau_prior_visitors: float,
    mtd_total: float,
    ytd_total: float,
    start: date,
    end: date,
) -> str:
    dau_delta = None
    if avg_dau_prior_visitors > 0:
        dau_delta = (avg_dau_visitors - avg_dau_prior_visitors) / avg_dau_prior_visitors
    dau_drop_flagged = dau_delta is not None and dau_delta < -WOW_FLAG_THRESHOLD

    total_this = sum(r.this_week for r in cost_rows)
    total_prior = sum(r.prior_week for r in cost_rows)
    total_delta = ((total_this - total_prior) / total_prior) if total_prior > 0.01 else None

    chart_html = render_chart(daily)

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
<html><head><meta charset="utf-8"></head>
<body style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#222;max-width:640px;margin:0 auto;padding:24px;">
  <h2 style="margin:0 0 4px;">Connactor weekly report</h2>
  <div style="color:#888;margin-bottom:24px;">Week of {start.isoformat()} – {(end - timedelta(days=1)).isoformat()} (UTC)</div>

  <h3 style="margin-top:24px;">Usage</h3>
  <p style="margin:4px 0;">
    <strong>DAU (avg, last 7d):</strong> {avg_dau_visitors:,.1f} visitors/day · {avg_dau_pageviews:,.1f} pageviews/day
    <span style="color:{'#cc0000' if dau_drop_flagged else '#888'};">
      ({'⚠ ' if dau_drop_flagged else ''}{_fmt_pct(dau_delta)} WoW)
    </span>
  </p>

  {chart_html}

  <table cellspacing="0" cellpadding="6" style="border-collapse:collapse;width:100%;margin-top:12px;font-size:14px;">
    <thead><tr style="background:#f5f5f5;text-align:left;">
      <th>Date</th><th style="text-align:right">Visitors</th><th style="text-align:right">Pageviews</th>
    </tr></thead>
    <tbody>{daily_html or '<tr><td colspan="3" style="color:#888;font-style:italic;">No data — is Cloudflare Web Analytics enabled?</td></tr>'}</tbody>
  </table>

  <h3 style="margin-top:32px;">Cost</h3>
  <p style="margin:4px 0;">
    <strong>Last 7 days:</strong> ${total_this:,.2f}
    <span style="color:#888;">({_fmt_pct(total_delta)} WoW)</span>
  </p>
  <p style="margin:4px 0;"><strong>Month-to-date:</strong> ${mtd_total:,.2f}</p>
  <p style="margin:4px 0;"><strong>Year-to-date:</strong> ${ytd_total:,.2f}</p>

  <h4 style="margin-top:20px;margin-bottom:8px;color:#555;font-weight:600;">Service breakdown (last 7 days)</h4>
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

  <p style="color:#888;font-size:12px;margin-top:32px;line-height:1.5;">
    Generated by <code>connactor-cost-report</code>. <code>⚠</code> = WoW change exceeds ±25%.<br>
    Usage data via Cloudflare Web Analytics. WAU / YTD / retention metrics intentionally omitted — Cloudflare's free tier doesn't expose cross-day deduplication. See issue for proper analytics infra.
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
    gcp_mtd, gcp_ytd = fetch_gcp_totals(bq, end=end)

    cf_row, cf_monthly = fetch_cloudflare_cost(settings.cloudflare_account_id, settings.cloudflare_api_token)
    if cf_row:
        cost_rows.append(cf_row)

    # Prorate the current Cloudflare monthly subscription onto MTD/YTD windows.
    # Cloudflare's API doesn't expose historical invoices; this is an approximation
    # that's accurate as long as the subscription set hasn't changed mid-period.
    day_of_month = end.day - 1  # `end` is exclusive (today UTC 00:00)
    day_of_year = (end - end.replace(month=1, day=1)).days
    cf_mtd = cf_monthly * day_of_month / 30
    cf_ytd = cf_monthly * day_of_year / 30

    mtd_total = gcp_mtd + cf_mtd
    ytd_total = gcp_ytd + cf_ytd

    zone = settings.cloudflare_zone_tag
    token = settings.cloudflare_api_token

    # Daily breakdown — drives the chart + per-day table.
    daily = _cloudflare_graphql(zone, token, start, end)
    daily_prior = _cloudflare_graphql(zone, token, prior_start, start)

    # DAU = mean of daily uniques across the last 7 days. Same for pageviews.
    # Prior-week DAU is the same calc shifted back a week, for WoW comparison.
    avg_dau_visitors = (sum(d.visitors for d in daily) / len(daily)) if daily else 0.0
    avg_dau_pageviews = (sum(d.pageviews for d in daily) / len(daily)) if daily else 0.0
    avg_dau_prior_visitors = (sum(d.visitors for d in daily_prior) / len(daily_prior)) if daily_prior else 0.0

    html = render_html(
        cost_rows, daily,
        avg_dau_visitors=avg_dau_visitors,
        avg_dau_pageviews=avg_dau_pageviews,
        avg_dau_prior_visitors=avg_dau_prior_visitors,
        mtd_total=mtd_total, ytd_total=ytd_total,
        start=start, end=end,
    )
    subject = f"Connactor weekly report — {start.isoformat()}"

    if args.dry_run:
        print(html)
        return

    send_email(html, subject)


if __name__ == "__main__":
    main()
