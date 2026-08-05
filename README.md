# wiom-payment-metrics

Hourly payment 1st-attempt success rate metrics for Wiom.

## How it works

1. **`refresh.py`** runs every hour on a local machine via a Claude Code scheduled task
2. It queries Snowflake via the Metabase REST API and writes results to `payment_metrics.json`
3. It commits and pushes the JSON to this repo
4. The **cloud Claude routine** (`Payment 1st-Attempt Rate Hourly Alert`) reads `payment_metrics.json` from this repo, checks if `first_attempt_pct < 90`, and DMs the PM via Slack if breached

## `payment_metrics.json` shape

```json
{
  "generated_at_ist": "2026-08-05 18:00 IST",
  "hour_ist": "2026-08-05 17:00:00",
  "total_successful": 142,
  "first_attempt_count": 134,
  "first_attempt_pct": 94.37,
  "status": "OK",
  "error": null
}
```

`status` is `"OK"`, `"ALERT"` (< 90%), or `"ERROR"` (query failed).
