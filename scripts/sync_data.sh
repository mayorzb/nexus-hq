#!/usr/bin/env bash
# Run BEFORE each scan: bring this runner's copy up to the latest saved commit on its branch.
set -u
branch="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"
if git fetch -q origin "$branch"; then
  git reset -q --hard "origin/$branch" && echo "Synced to latest $branch ($(git rev-parse --short HEAD))."
else
  echo "Could not fetch $branch; scanning on the current copy."
fi
