#!/usr/bin/env bash
# Writes the fixed review outputs next to the data, so reviewers read files instead of running code.
set -u
mkdir -p data_v15/reports
python nexus_review.py --daily --data data_v15 > data_v15/reports/daily_latest.md.tmp && \
  mv data_v15/reports/daily_latest.md.tmp data_v15/reports/daily_latest.md
python nexus_review.py --bounds --data data_v15 > data_v15/reports/bounds_latest.md.tmp && \
  mv data_v15/reports/bounds_latest.md.tmp data_v15/reports/bounds_latest.md
python nexus_eval.py --data data_v15 > data_v15/reports/eval2_latest.md.tmp && \
  mv data_v15/reports/eval2_latest.md.tmp data_v15/reports/eval2_latest.md
