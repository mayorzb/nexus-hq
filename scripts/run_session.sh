#!/usr/bin/env bash
# Runs N paper scans and saves after each.
# - D6: a failed scan or save fails the run (red X + Telegram alert) after every scan has had its chance.
# - Provenance: NEXUS_CODE_COMMIT = last commit that changed code (not data). A shallow checkout cannot tell,
#   so history is fetched first; if it still cannot be told, the field is left blank rather than wrong.
# - If code on main changes mid-session, the session stops so the next one tests the new code first.
# - v1.5.2 pacing: each scan starts NEXUS_INTERVAL_S (60 min) after the LAST RECORDED scan started, read from
#   data_v15/scans.csv. No drift (start-to-start, not end-to-start) and no back-to-back scans when one session
#   hands over to the next.
# - v1.5.2 reports: after each scan the daily review and result bounds are written to data_v15/reports/, and the
#   test log of this session (NEXUS_TESTS_LOG) is copied there, so reviewers can read them without running code.
# Test overrides: NEXUS_SCAN_CMD / NEXUS_SAVE_CMD / NEXUS_SYNC_CMD / NEXUS_SLEEP_CMD / NEXUS_REVIEW_CMD
set -u
n="${1:-1}"
scan_cmd="${NEXUS_SCAN_CMD:-python nexus_v15.py}"
save_cmd="${NEXUS_SAVE_CMD:-bash scripts/save_logs.sh}"
sync_cmd="${NEXUS_SYNC_CMD:-bash scripts/sync_data.sh}"
sleep_cmd="${NEXUS_SLEEP_CMD:-sleep}"
review_cmd="${NEXUS_REVIEW_CMD:-bash scripts/write_reports.sh}"
interval="${NEXUS_INTERVAL_S:-3600}"

code_commit() {
  if [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
    git fetch -q --unshallow 2>/dev/null || true
  fi
  [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = "true" ] && { echo ""; return; }
  git log -1 --format=%H -- . ':(exclude)data_v15' 2>/dev/null
}
seconds_to_wait() {   # interval minus seconds since the last recorded scan started; never negative
  python3 - "$interval" <<'PY'
import csv, sys
from datetime import datetime, timezone
interval = int(sys.argv[1])
try:
    rows = list(csv.DictReader(open("data_v15/scans.csv")))
    t = datetime.fromisoformat(rows[-1]["started_at"])
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    since = (datetime.now(timezone.utc) - t).total_seconds()
    print(max(0, min(interval, int(interval - since))))
except Exception:
    print(0)
PY
}

start_code="$(code_commit)"
failed=0
for i in $(seq 1 "$n"); do
  $sync_cmd || { echo "::error::sync failed before scan $i"; failed=$((failed+1)); }
  wait_s="$(seconds_to_wait)"
  if [ "${wait_s:-0}" -gt 0 ]; then
    echo "Last scan started $(( (interval - wait_s) / 60 )) min ago: waiting ${wait_s}s so scans stay ${interval}s apart."
    $sleep_cmd "$wait_s"
    $sync_cmd || { echo "::error::sync failed before scan $i"; failed=$((failed+1)); }
  fi
  now_code="$(code_commit)"
  if [ -n "$start_code" ] && [ -n "$now_code" ] && [ "$now_code" != "$start_code" ]; then
    echo "Code on main changed ($start_code -> $now_code): ending this session; the next one tests the new code first."
    break
  fi
  echo "=== scan $i of $n at $(date -u +%H:%M) UTC (code ${now_code:-unknown}) ==="
  export NEXUS_CODE_COMMIT="$now_code"
  $scan_cmd || { echo "::error::scan $i failed"; failed=$((failed+1)); }
  mkdir -p data_v15/reports
  if [ -n "${NEXUS_TESTS_LOG:-}" ] && [ -f "$NEXUS_TESTS_LOG" ]; then cp "$NEXUS_TESTS_LOG" data_v15/reports/tests_latest.txt; fi
  $review_cmd || echo "::warning::review reports could not be written after scan $i (scan data is unaffected)"
  $save_cmd "v1.5 paper scan $(date -u +'%Y-%m-%d %H:%M') UTC" data_v15 || { echo "::error::save after scan $i failed"; failed=$((failed+1)); }
done
if [ "$failed" -gt 0 ]; then echo "::error::$failed step(s) failed in this session"; exit 1; fi
echo "Session finished without failures."
