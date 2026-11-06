#!/usr/bin/env bash
# Session chaining for "Nexus v1.5 paper test" (D11). PAPER ONLY.
#   chain.sh guard  -> exit 0 = go ahead; exit 3 = another session is already running (skip this one)
#   chain.sh next   -> start the next session, unless a safety limit says no
# Safety limits (frozen):
#   - never on a private repo (Actions minutes would cost money; public repos are free)
#   - never if another session is queued or running (no duplicates, no repeated dispatches)
#   - at most MAX_SESSIONS_PER_DAY sessions started per UTC day (runaway cap; 6 x 5 scans covers 24h+)
# Needs: gh CLI, GH_TOKEN with actions:write, GITHUB_REPOSITORY, GITHUB_RUN_ID, REPO_PRIVATE ("true"/"false").
set -u
cmd="${1:-}"
wf="nexus-v15-paper.yml"
max_day="${MAX_SESSIONS_PER_DAY:-6}"
today="$(date -u +%Y-%m-%d)"
self="${GITHUB_RUN_ID:-0}"

others_active() {   # queued or running runs of this workflow other than this one
  gh run list --workflow "$wf" --limit 50 --json databaseId,status \
    --jq "[.[] | select(.databaseId != $self and (.status == \"queued\" or .status == \"in_progress\" or .status == \"waiting\" or .status == \"pending\"))] | length"
}
started_today() {
  gh run list --workflow "$wf" --limit 100 --json createdAt \
    --jq "[.[] | select(.createdAt | startswith(\"$today\"))] | length"
}

case "$cmd" in
  guard)
    # Fail OPEN: the server-side concurrency group already stops two sessions overlapping, so this guard may
    # only ever skip a session when it can positively see a DIFFERENT run still in progress. It never counts
    # its own run (databaseId == GITHUB_RUN_ID), and it re-checks before skipping because the runs list can
    # briefly show a just-finished run as in progress.
    case "$self" in ''|0|*[!0-9]*) echo "::warning::GITHUB_RUN_ID missing: guard skipped (fail open)"; exit 0 ;; esac
    tries="${GUARD_RECHECKS:-6}"; wait_s="${GUARD_WAIT_S:-30}"
    for t in $(seq 1 "$tries"); do
      running="$(gh run list --workflow "$wf" --limit 50 --json databaseId,status \
        --jq "[.[] | select(.databaseId != $self and .status == \"in_progress\")] | length")" \
        || { echo "::warning::could not list runs: going ahead (fail open)"; exit 0; }
      [ "${running:-0}" -eq 0 ] && { echo "No other running session: go."; exit 0; }
      echo "Another run shows as in progress (check $t of $tries)"; [ "$t" -lt "$tries" ] && sleep "$wait_s"
    done
    echo "Another session is still running after $tries checks: skipping this one (that session chains)."; exit 3 ;;
  next)
    if [ "${REPO_PRIVATE:-true}" != "false" ]; then
      echo "::error::repo is private (or unknown): chaining refused to avoid paid Actions minutes"; exit 4; fi
    n="$(others_active)" || { echo "::error::could not list runs: chain not started"; exit 1; }
    if [ "$n" -gt 0 ]; then echo "A session is already queued or running: not dispatching another."; exit 0; fi
    d="$(started_today)" || { echo "::error::could not count today's sessions: chain not started"; exit 1; }
    if [ "$d" -ge "$max_day" ]; then
      echo "::error::daily cap reached ($d of $max_day sessions on $today): chain stopped; the hourly schedule resumes tomorrow"; exit 5; fi
    gh workflow run "$wf" --ref main -f mode=scan -f chain=true || { echo "::error::dispatch failed"; exit 1; }
    echo "Next session requested ($((d + 1)) of $max_day today)."; exit 0 ;;
  *) echo "usage: chain.sh guard|next"; exit 2 ;;
esac
