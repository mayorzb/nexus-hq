"""
Nexus review: the FIXED scorecard used for every monitoring review. Read-only: it never changes data or rules.

  python nexus_review.py --daily  [--data DIR ...] [--now ISO]
  python nexus_review.py --weekly [--data DIR ...] [--now ISO]

Same script + same data = same numbers. If a metric definition ever changes, REVIEW_VERSION changes and the
monitoring log notes it. Several --data folders (e.g. main and V15-dev) are merged; duplicates are dropped.
"""
import csv
import math
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

REVIEW_VERSION = "review-1.0"
HORIZONS = [5, 15, 30, 60, 240]
MIN_N = 30                      # below this a group/horizon is "insufficient", no verdict
BOOT = 2000
SEED = 15                       # fixed seed: the same data always gives the same intervals

# health thresholds (daily)
COVERAGE_OK, COVERAGE_WARN = 0.95, 0.80      # share of the last 24 hours with at least one scan
GAP_ALERT_MIN = 90
UNVERIFIED_ALERT = 0.30                      # share of deep-checked coins that ended UNVERIFIED
NOT_CHECKED_ALERT = 0.20                     # share of gate-passers the deep-check budget skipped
UNKNOWN_ALERT = 0.10                         # share of finished labels that are UNKNOWN
OVERDUE_H = 6                                # a label still pending this long after it was due


def parse(s):
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def read(dirs, name, key):
    seen, out = set(), []
    for d in dirs:
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        with open(p, newline="") as fh:
            for r in csv.DictReader(fh):
                k = tuple(r.get(x, "") for x in key)
                if k not in seen:
                    seen.add(k)
                    out.append(r)
    return out


def load(dirs):
    scans = read(dirs, "scans.csv", ["scan_id"])
    sights = read(dirs, "sightings.csv", ["sighting_id"])
    labels = read(dirs, "labels.csv", ["sighting_id", "horizon_min"])
    # a label can exist on two branches with different progress: keep the most finished copy
    best = {}
    rank = {"labelled": 2, "unknown": 1, "pending": 0}
    for d in dirs:
        p = os.path.join(d, "labels.csv")
        if os.path.exists(p):
            with open(p, newline="") as fh:
                for r in csv.DictReader(fh):
                    k = (r["sighting_id"], r["horizon_min"])
                    if k not in best or rank.get(r["status"], 0) > rank.get(best[k]["status"], 0):
                        best[k] = r
    return scans, sights, list(best.values()) or labels


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - m), min(1, c + m)


def day_block_ci(rows, level=0.90):
    """Mean net return with a bootstrap that resamples whole days (coins on one day are not independent)."""
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["t0"][:10]].append(f(r["net_pct"]))
    days = list(by_day.values())
    if len(days) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(SEED)
    means = []
    for _ in range(BOOT):
        pick = [x for _ in days for x in rng.choice(days)]
        means.append(sum(pick) / len(pick))
    means.sort()
    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    return means[int(lo * BOOT)], means[int(hi * BOOT) - 1]


GROUPS = {
    "B0 liquid baseline": lambda r: r["b0_liquid"] == "1",
    "Legacy v1.4.2 gate": lambda r: r["legacy_gate"] == "1",
    "H1 mature (>=3h) liquid": lambda r: r["b0_liquid"] == "1" and r["h1_mature"] == "1",
    "v1.5 candidates": lambda r: r["decision"] == "CANDIDATE",
}


def group_stats(rows):
    lab = [r for r in rows if r["status"] == "labelled"]
    unk = sum(1 for r in rows if r["status"] == "unknown")
    pend = sum(1 for r in rows if r["status"] == "pending")
    nets = [f(r["net_pct"]) for r in lab]
    n = len(nets)
    out = {"n": n, "unknown": unk, "pending": pend}
    if n:
        wins = sum(1 for x in nets if x > 0)
        out.update(wins=wins, win_ci=wilson(wins, n), mean=sum(nets) / n,
                   median=sorted(nets)[n // 2], rug=sum(1 for x in nets if x <= -90) / n,
                   mean_ci=day_block_ci(lab))
    return out


def pct(x):
    return "n/a" if x is None or x != x else f"{100 * x:.0f}%"


def num(x):
    return "n/a" if x is None or x != x else f"{x:+.1f}%"


def status(ok, warn=None):
    return "OK" if ok else ("WARN" if warn else "ALERT")


def daily(dirs, now):
    scans, sights, labels = load(dirs)
    since = now - timedelta(hours=24)
    sc = sorted((s for s in scans if parse(s["started_at"]) >= since), key=lambda s: s["started_at"])
    hours = {parse(s["started_at"]).strftime("%Y%m%d%H") for s in sc}
    coverage = len(hours) / 24
    times = [parse(s["started_at"]) for s in sorted(scans, key=lambda s: s["started_at"])]
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:]) if b >= since]
    if times:
        gaps.append((now - times[-1]).total_seconds() / 60)
    max_gap = max(gaps) if gaps else float("inf")
    errs = [s for s in sc if s["errors"]]
    ids = {s["scan_id"] for s in sc}
    sg = [s for s in sights if s["scan_id"] in ids]
    deep = [s for s in sg if s["deep_checked"] == "1"]
    unv = sum(1 for s in deep if s["decision"] == "UNVERIFIED")
    passers = [s for s in sg if s["decision"] in ("CANDIDATE", "UNVERIFIED", "NOT_CHECKED") or s["deep_checked"] == "1"]
    notc = sum(1 for s in sg if s["decision"] == "NOT_CHECKED")
    cands = [s for s in sg if s["decision"] == "CANDIDATE"]
    fin = [r for r in labels if r["status"] in ("labelled", "unknown") and r["labelled_at"] and parse(r["labelled_at"]) >= since]
    unk = sum(1 for r in fin if r["status"] == "unknown")
    overdue = sum(1 for r in labels if r["status"] == "pending"
                  and parse(r["t0"]) + timedelta(minutes=247 + 60 * OVERDUE_H) < now)
    rules = Counter(s["rules"] for s in sc)
    rows = [
        ("Scan coverage (hours with a scan, last 24h)", f"{len(hours)}/24 ({pct(coverage)})",
         "OK" if coverage >= COVERAGE_OK else ("WARN" if coverage >= COVERAGE_WARN else "ALERT")),
        ("Longest gap between scans", "none" if max_gap == float("inf") else f"{max_gap:.0f} min",
         status(max_gap <= GAP_ALERT_MIN)),
        ("Scans with errors", f"{len(errs)} of {len(sc)}", status(not errs, warn=len(errs) <= 2)),
        ("Tokens seen / liquid (median per scan)",
         f"{med([f(s['n_tokens']) for s in sc])} / {med([f(s['n_liquid']) for s in sc])}", status(bool(sc))),
        ("Deep-checked coins left UNVERIFIED", f"{unv} of {len(deep)} ({pct(unv / len(deep) if deep else None)})",
         status(not deep or unv / len(deep) <= UNVERIFIED_ALERT)),
        ("Gate-passers skipped by check budget", f"{notc} of {len(passers)}",
         status(not passers or notc / len(passers) <= NOT_CHECKED_ALERT, warn=True)),
        ("Paper candidates (last 24h)", str(len(cands)), "INFO"),
        ("Labels finished / unknown (last 24h)", f"{len(fin)} / {unk}",
         status(not fin or unk / len(fin) <= UNKNOWN_ALERT)),
        ("Labels overdue (> 6h past due)", str(overdue), status(overdue == 0, warn=overdue < 20)),
        ("Rules versions in use", ", ".join(f"{k} ({v})" for k, v in rules.items()) or "none", status(len(rules) <= 1)),
    ]
    worst = "ALERT" if any(r[2] == "ALERT" for r in rows) else ("WARN" if any(r[2] == "WARN" for r in rows) else "OK")
    out = [f"DAILY HEALTH {now:%Y-%m-%d %H:%M} UTC ({REVIEW_VERSION}) - overall: {worst}", "",
           "| Check | Value | Status |", "| --- | --- | --- |"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    if errs:
        out += ["", "Errors seen: " + "; ".join(Counter(e["errors"][:80] for e in errs).keys())]
    if cands:
        out += ["", "Candidates: " + ", ".join(f"{c['symbol']} ({c['seen_at'][11:16]})" for c in cands)]
    return "\n".join(out), worst


def med(xs):
    xs = sorted(x for x in xs if x is not None)
    return "n/a" if not xs else f"{xs[len(xs) // 2]:.0f}"


def weekly(dirs, now):
    scans, sights, labels = load(dirs)
    rules = Counter(r["rules"] for r in labels)
    current = rules.most_common(1)[0][0] if rules else "none"
    lab = [r for r in labels if r["rules"] == current]
    first = min((parse(s["started_at"]) for s in scans), default=None)
    weeks = (now - first).days / 7 if first else 0
    out = [f"WEEKLY SCORECARD {now:%Y-%m-%d} ({REVIEW_VERSION}); rules {current}; "
           f"{weeks:.1f} weeks of data; {len(scans)} scans. PAPER ONLY, NOT VALIDATED.", ""]
    findings = []
    for h in HORIZONS:
        out += [f"### {h} minutes", "",
                "| Group | Labelled | Unknown | Pending | Win rate (95% range) | Mean net (90% day-block range) | Median | Rug rate | Mean vs B0 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        base = None
        for name, keep in GROUPS.items():
            g = group_stats([r for r in lab if r["horizon_min"] == str(h) and keep(r)])
            if name.startswith("B0"):
                base = g
            if not g["n"]:
                out.append(f"| {name} | 0 | {g['unknown']} | {g['pending']} | - | - | - | - | - |")
                continue
            diff = g["mean"] - base["mean"] if base and base.get("n") else float("nan")
            flag = "" if g["n"] >= MIN_N else " (insufficient)"
            out.append(f"| {name}{flag} | {g['n']} | {g['unknown']} | {g['pending']} | "
                       f"{pct(g['wins'] / g['n'])} ({pct(g['win_ci'][0])}-{pct(g['win_ci'][1])}) | "
                       f"{num(g['mean'])} ({num(g['mean_ci'][0])} to {num(g['mean_ci'][1])}) | {num(g['median'])} | "
                       f"{pct(g['rug'])} | {num(diff)} |")
            if g["n"] >= MIN_N and not name.startswith("B0") and g["mean_ci"][0] > 0 and diff > 0:
                findings.append(f"{name} at {h} min: 90% range of mean net is above zero and above baseline "
                                f"(n={g['n']}). Candidate for a pre-registered confirmation test, NOT a validated edge.")
        out.append("")
    # what blocks liquid coins
    liquid = [s for s in sights if s["b0_liquid"] == "1" and s["rules"] == current]
    reasons = Counter(s["reasons"].split(";")[0].split(" $")[0].split(" (")[0][:50] for s in liquid
                      if s["decision"] != "CANDIDATE")
    out += ["### What stopped liquid coins becoming candidates", "", "| Reason | Coins | Share |", "| --- | --- | --- |"]
    out += [f"| {k} | {v} | {pct(v / len(liquid))} |" for k, v in reasons.most_common(6)]
    # fixed improvement triggers
    d, _ = daily(dirs, now)
    if "ALERT" in d:
        findings.append("Pipeline health has ALERTs in the last 24h: fix data quality before reading results.")
    deep = [s for s in sights if s["deep_checked"] == "1" and s["rules"] == current]
    if deep and sum(s["decision"] == "UNVERIFIED" for s in deep) / len(deep) > UNVERIFIED_ALERT:
        findings.append("More than 30% of deep-checked coins end UNVERIFIED: improve data sources (RPC key, holder read).")
    cand7 = [s for s in sights if s["decision"] == "CANDIDATE" and parse(s["seen_at"]) >= now - timedelta(days=7)]
    if not cand7 and reasons:
        top = reasons.most_common(1)[0][0]
        findings.append(f"No candidates in 7 days. Most common blocker: '{top}'. Review whether that gate is "
                        f"evidence-based before any change (any change = new rules version).")
    fin = [r for r in lab if r["status"] in ("labelled", "unknown")]
    if fin and sum(r["status"] == "unknown" for r in fin) / len(fin) > UNKNOWN_ALERT:
        findings.append("More than 10% of finished labels are UNKNOWN: check candle coverage for these pools.")
    gate = ("CONTINUE" if any("Candidate for a pre-registered" in x for x in findings)
            else ("STOP RULE DUE: 8 weeks without a group beating baseline" if weeks >= 8 else
                  f"COLLECTING: week {weeks:.1f} of 8; no group has passed yet"))
    out += ["", f"Section 6 gate status: {gate}", "", "Proposed improvements (for approval, nothing auto-applied):"]
    out += [f"- {x}" for x in findings] or ["- none this week"]
    return "\n".join(out)


def main():
    args = sys.argv[1:]
    dirs = [args[i + 1] for i, a in enumerate(args) if a == "--data"] or ["data_v15"]
    now = next((parse(args[i + 1]) for i, a in enumerate(args) if a == "--now"), datetime.now(timezone.utc))
    if "--weekly" in args:
        print(weekly(dirs, now))
    else:
        print(daily(dirs, now)[0])


if __name__ == "__main__":
    main()
