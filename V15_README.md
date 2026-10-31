# Nexus v1.5.0 (paper test, branch v15-dev)

- `nexus_v15.py`: risk-first scanner, fixed measurement, 5/15/30/60/240-min paper labels, Telegram.
- `test_nexus_v15.py`: 25 offline tests (one per confirmed defect F01-F07, N1-N3, plus launch checks).
- `scripts/save_logs.sh`: safe log saving (fix for N1), used by both workflows.
- `.github/workflows/nexus-v15-paper.yml`: runs on pushes to `v15-dev` only: tests, Telegram test, 6 hourly scans.
- `.github/workflows/nexus-scan.yml`: v1.4.2 hourly workflow, save step fixed (N1). Takes effect only if merged to main.
- `concept_scorer_v1_4.py` is unchanged: it is the frozen baseline.
- Output: `data_v15/` (scans, sightings, labels). Old v1.4 files are never touched.
- PAPER ONLY. No wallet, keys or trading code. Probabilities are not shown until validated.
