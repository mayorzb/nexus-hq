#!/usr/bin/env bash
# Saves log files back to the repo. Fix for defect N1: each path is added on its own, so one
# missing file can no longer stop the others being saved (the old one-line `git add a b c || true` did).
# Usage: scripts/save_logs.sh "commit message" path1 [path2 ...]
set -u
msg="$1"; shift
git config user.name  "nexus-bot"
git config user.email "nexus-bot@users.noreply.github.com"
for f in "$@"; do
  if [ -e "$f" ]; then git add -f -- "$f" || echo "could not stage $f"; else echo "skip (not created yet): $f"; fi
done
if git diff --cached --quiet; then echo "Nothing new to save."; exit 0; fi
git commit -q -m "$msg"
[ "${NEXUS_NO_PUSH:-0}" = "1" ] && { echo "Committed (push skipped)."; exit 0; }
branch="$(git rev-parse --abbrev-ref HEAD)"
for i in 1 2 3; do git pull --rebase --quiet origin "$branch" && git push --quiet origin "HEAD:$branch" && { echo "Saved."; exit 0; }; sleep 5; done
echo "Could not push the logs after 3 tries."; exit 1
