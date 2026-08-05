"""
Wiom Payment Metrics Refresher
Runs every hour, queries Metabase, writes payment_metrics.json, commits & pushes to GitHub.
Called by the local Claude Code scheduled task.
"""

import requests
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

METABASE_URL = 'https://metabase.wiom.in'
# Reads from env var when running in GitHub Actions; falls back to hardcoded for local use
API_KEY = os.environ.get('METABASE_API_KEY', 'mb_Uo6NCJismo2/x7Aupcy8LC+eABj7/iF6+1dF+LamMKI=')
DB_ID = 113

SQL = """
WITH last_hour AS (
    SELECT
        DATEADD('hour', -1, DATE_TRUNC('hour', CONVERT_TIMEZONE('Asia/Kolkata', CURRENT_TIMESTAMP()))) AS hour_start,
        DATE_TRUNC('hour', CONVERT_TIMEZONE('Asia/Kolkata', CURRENT_TIMESTAMP())) AS hour_end
),
csp_account AS (
    SELECT csp_id FROM csp_gateway_service_csp_gateway_service.csp_account
    WHERE _fivetran_active AND csp_id NOT IN ('a0a6w1','a0a0b1') AND partner_id IS NOT NULL
),
led AS (
    SELECT w.reference_id AS withdrawal_id
    FROM csp_payment_settlement_service_csp_payment_settlement_service.wallet_ledger_entries w
    JOIN csp_account c ON c.csp_id = w.csp_id CROSS JOIN last_hour lh
    WHERE w._fivetran_active AND w.entry_type = 'WITHDRAWAL_DEBIT' AND w.reference_id IS NOT NULL
      AND CONVERT_TIMEZONE('Asia/Kolkata', w.created_at) >= lh.hour_start
      AND CONVERT_TIMEZONE('Asia/Kolkata', w.created_at) <  lh.hour_end
    GROUP BY w.reference_id
),
retry_counts AS (
    SELECT withdrawal_id, COUNT(*) AS retries, MAX(retry_status) AS final_status
    FROM csp_payment_settlement_service_csp_payment_settlement_service.payout_retry_log
    WHERE NOT _fivetran_deleted GROUP BY withdrawal_id
),
outcomes AS (
    SELECT CASE WHEN r.withdrawal_id IS NULL THEN 1 ELSE 0 END AS is_first_attempt
    FROM led l LEFT JOIN retry_counts r ON r.withdrawal_id = l.withdrawal_id
    WHERE r.withdrawal_id IS NULL OR r.final_status = 'processed'
),
summary AS (
    SELECT
        (SELECT hour_start FROM last_hour) AS hour_ist,
        COUNT(*) AS total_successful,
        SUM(is_first_attempt) AS first_attempt_count,
        ROUND(100.0 * SUM(is_first_attempt) / NULLIF(COUNT(*), 0), 2) AS first_attempt_pct
    FROM outcomes
)
SELECT hour_ist, total_successful, first_attempt_count, first_attempt_pct,
       CASE WHEN first_attempt_pct < 90 THEN 'ALERT' ELSE 'OK' END AS status
FROM summary
"""

IST = timezone(timedelta(hours=5, minutes=30))

def run():
    now_ist = datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')
    result = {
        'generated_at_ist': now_ist,
        'hour_ist': None,
        'total_successful': None,
        'first_attempt_count': None,
        'first_attempt_pct': None,
        'status': None,
        'error': None
    }

    try:
        resp = requests.post(
            f'{METABASE_URL}/api/dataset',
            headers={'x-api-key': API_KEY, 'Content-Type': 'application/json'},
            json={'database': DB_ID, 'type': 'native', 'native': {'query': SQL}},
            timeout=120
        )
        resp.raise_for_status()
        data = resp.json()

        cols = [c['name'] for c in data['data']['cols']]
        row  = data['data']['rows'][0]
        row_dict = dict(zip(cols, row))

        result['hour_ist']          = str(row_dict.get('HOUR_IST') or row_dict.get('hour_ist') or '')
        result['total_successful']  = int(row_dict.get('TOTAL_SUCCESSFUL') or row_dict.get('total_successful') or 0)
        result['first_attempt_count'] = int(row_dict.get('FIRST_ATTEMPT_COUNT') or row_dict.get('first_attempt_count') or 0)
        result['first_attempt_pct'] = float(row_dict.get('FIRST_ATTEMPT_PCT') or row_dict.get('first_attempt_pct') or 0)
        result['status']            = str(row_dict.get('STATUS') or row_dict.get('status') or 'OK')

    except Exception as e:
        result['error'] = str(e)
        result['status'] = 'ERROR'

    # Write JSON
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, 'payment_metrics.json')
    with open(out_path, 'w') as f:
        json.dump(result, f, indent=2)

    # Git commit & push
    try:
        subprocess.run(['git', 'config', 'user.email', 'product_analytics@wiom.in'], cwd=script_dir, check=True)
        subprocess.run(['git', 'config', 'user.name', 'Wiom Analytics'], cwd=script_dir, check=True)
        subprocess.run(['git', 'add', 'payment_metrics.json'], cwd=script_dir, check=True)
        subprocess.run(
            ['git', 'commit', '-m', f'chore: refresh metrics {now_ist}'],
            cwd=script_dir, check=True
        )
        subprocess.run(['git', 'push'], cwd=script_dir, check=True)
        print(f'[{now_ist}] Pushed: status={result["status"]}, pct={result["first_attempt_pct"]}')
    except subprocess.CalledProcessError as e:
        print(f'[{now_ist}] Git error: {e}', file=sys.stderr)

if __name__ == '__main__':
    run()
