#!/usr/bin/env bash
# D6 + D11: runs N scans, saving after each. A failed scan or save no longer leaves the run green: every scan
# still gets its chance, then the run fails if anything failed (red X in Actions + Telegram alert step).
# Provenance: before each scan, NEXUS_CODE_COMMIT = the last commit that changed code (not data), so every scan
# row names the exact code that produced it. If the code changes on main during a session, the session stops
# cleanly so the next session runs the tests on the new code before scanning with it.
# Usage: scripts/run_session.sh N   (env NEXUS_SCAN_CMD / NEXUS_SAVE_CMD / NEXUS_SYNC_CMD / NEXUS_SLEEP_S, for tests)
set -u
n="${1:-1}"
scan_cmd="${NEXUS_SCAN_CMD:-python nexus_v15.py}"
save_cmd="${NEXUS_SAVE_CMD:-bash scripts/save_logs.sh}"
sync_cmd="${NEXUS_SYNC_CMD:-bash scripts/sync_data.sh}"
sleep_s="${NEXUS_SLEEP_S:-3600}"
code_commit() { git log -1 --format=%H -- . ':(exclude)data_v15' 2>/dev/null; }
start_code="$(code_commit)"
failed=0
for i in $(seq 1 "$n"); do
  echo "=== scan $i of $n at $(date -u +%H:%M) UTC ==="
  $sync_cmd || { echo "::error::sync failed before scan $i"; failed=$((failed+1)); }
  now_code="$(code_commit)"
  if [ -n "$start_code" ] && [ -n "$now_code" ] && [ "$now_code" != "$start_code" ]; then
    echo "Code on main changed ($start_code -> $now_code): ending this session; the next one tests the new code first."
    break
  fi
  export NEXUS_CODE_COMMIT="${now_code:-${NEXUS_CODE_COMMIT:-}}"
  $scan_cmd || { echo "::error::scan $i failed"; failed=$((failed+1)); }
  $save_cmd "v1.5 paper scan $(date -u +'%Y-%m-%d %H:%M') UTC" data_v15 || { echo "::error::save after scan $i failed"; failed=$((failed+1)); }
  if [ "$i" -lt "$n" ]; then sleep "$sleep_s"; fi
done
if [ "$failed" -gt 0 ]; then echo "::error::$failed step(s) failed in this session"; exit 1; fi
echo "Session finished without failures."
