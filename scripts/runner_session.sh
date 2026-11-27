#!/usr/bin/env bash
# Runner Track session: N scans, one every RUNNER_INTERVAL_S seconds (start to start), saving after each.
# Data lives in ./data_runner, a checkout of the separate "runner-data" branch, so main is never written to
# (a data commit on main would end the v1.5 scanner's sessions early). PAPER ONLY.
# Test overrides: RUNNER_SCAN_CMD / RUNNER_SAVE_CMD / RUNNER_SLEEP_CMD
set -u
n="${1:-34}"
interval="${RUNNER_INTERVAL_S:-600}"
scan_cmd="${RUNNER_SCAN_CMD:-python nexus_runner.py}"
save_cmd="${RUNNER_SAVE_CMD:-bash ../scripts/save_logs.sh}"
sleep_cmd="${RUNNER_SLEEP_CMD:-sleep}"
failed=0
for i in $(seq 1 "$n"); do
  started="$(date +%s)"
  git -C data_runner pull -q --rebase origin runner-data 2>/dev/null || echo "::warning::could not refresh runner-data before scan $i"
  echo "=== runner scan $i of $n at $(date -u +%H:%M) UTC ==="
  NEXUS_RUNNER_DATA=data_runner $scan_cmd || { echo "::error::runner scan $i failed"; failed=$((failed+1)); }
  ( cd data_runner && $save_cmd "runner scan $(date -u +'%Y-%m-%d %H:%M') UTC" . ) \
    || { echo "::error::save after runner scan $i failed"; failed=$((failed+1)); }
  if [ "$failed" -ge 3 ]; then echo "::error::3 failures in this session: stopping early"; break; fi
  if [ "$i" -lt "$n" ]; then
    wait_s=$(( interval - ($(date +%s) - started) ))
    [ "$wait_s" -gt 0 ] && $sleep_cmd "$wait_s"
  fi
done
if [ "$failed" -gt 0 ]; then echo "::error::$failed step(s) failed in this session"; exit 1; fi
echo "Runner session finished without failures."
