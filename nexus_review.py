"""
Nexus review: the FIXED scorecard used for every monitoring review. Read-only: it never changes data or rules.

  python nexus_review.py --daily  [--data DIR ...] [--now ISO]
  python nexus_review.py --weekly [--data DIR ...] [--now ISO]
  python nexus_review.py --sensitivity [--data DIR ...]   (price-validity thresholds, from archived candles)
  python nexus_review.py --sample-size [--data DIR ...]   (Round 3 sample sizes, every input computed from data)
  python nexus_review.py --bounds [--data DIR ...]        (each group's mean with exclusions left out / counted as -100)

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

REVIEW_VERSION = "review-1.4"
HORIZONS = [5, 15, 30, 60, 240]
MIN_N = 30                      # below this a group/horizon is "insufficient", no verdict
BOOT = 2000
SEED = 15                       # fixed seed: the same data always gives the same intervals

# health thresholds (daily)
COVERAGE_OK, COVERAGE_WARN = 0.95, 0.80      # share of the last 24 hours with at least one scan
GAP_ALERT_MIN = 90
MIN_GAP_ALERT_MIN = 50                       # review-1.4: two scans closer than this = duplicate/back-to-back scans
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
    rank = {"labelled": 2, "unknown": 1, "unreliable": 1, "pending": 0}
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
    unk = sum(1 for r in rows if r["status"] in ("unknown", "unreliable"))   # never counted as results
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


def code_tag_problems(dirs, sc):
    """Counts last-24h scans whose code_commit is blank or names a commit that changed only data_v15 files.
       Needs git and full history next to the data folder; otherwise returns (None, reason)."""
    import subprocess
    tagged = [s for s in sc if "code_commit" in s and s.get("version", "") >= "1.5.1"]
    if not tagged:
        return None, "no scans with code tags"
    repo = os.path.dirname(os.path.abspath(dirs[0]))
    seen, bad = {}, 0
    for s in tagged:
        c = s.get("code_commit", "")
        if not c:
            bad += 1
            continue
        if c not in seen:
            try:
                files = subprocess.run(["git", "-C", repo, "show", "--name-only", "--format=", c], capture_output=True,
                                       text=True, timeout=20)
            except Exception:
                return None, "git not available here"
            if files.returncode != 0:
                return None, f"commit {c} not in this checkout's history"
            paths = [x for x in files.stdout.splitlines() if x.strip()]
            seen[c] = bool(paths) and all(x.startswith("data_v15/") for x in paths)
        bad += seen[c]
    return bad, f"{bad} of {len(tagged)}"


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
    pair_gaps = [((b - a).total_seconds() / 60, a) for a, b in zip(times, times[1:]) if b >= since]
    min_gap, min_at = min(pair_gaps) if pair_gaps else (float("inf"), None)
    bad_tags, tag_note = code_tag_problems(dirs, sc)
    errs = [s for s in sc if s["errors"]]
    ids = {s["scan_id"] for s in sc}
    sg = [s for s in sights if s["scan_id"] in ids]
    deep = [s for s in sg if s["deep_checked"] == "1"]
    unv = sum(1 for s in deep if s["decision"] == "UNVERIFIED")
    passers = [s for s in sg if s["decision"] in ("CANDIDATE", "UNVERIFIED", "NOT_CHECKED") or s["deep_checked"] == "1"]
    notc = sum(1 for s in sg if s["decision"] == "NOT_CHECKED")
    cands = [s for s in sg if s["decision"] == "CANDIDATE"]
    fin = [r for r in labels if r["status"] in ("labelled", "unknown", "unreliable") and r["labelled_at"]
           and parse(r["labelled_at"]) >= since]
    unk = sum(1 for r in fin if r["status"] in ("unknown", "unreliable"))
    overdue = sum(1 for r in labels if r["status"] == "pending"
                  and parse(r["t0"]) + timedelta(minutes=247 + 60 * OVERDUE_H) < now)
    rules = Counter(s["rules"] for s in sc)
    can_n = sum(int(s.get("canary_n") or 0) for s in sc)
    can_unv = sum(int(s.get("canary_unverified") or 0) for s in sc)
    can_err = sum(int(s.get("canary_onchain_err") or 0) for s in sc)
    rows = [
        ("Scan coverage (hours with a scan, last 24h)", f"{len(hours)}/24 ({pct(coverage)})",
         "OK" if coverage >= COVERAGE_OK else ("WARN" if coverage >= COVERAGE_WARN else "ALERT")),
        ("Longest gap between scans", "none" if max_gap == float("inf") else f"{max_gap:.0f} min",
         status(max_gap <= GAP_ALERT_MIN)),
        ("Shortest gap between scans (last 24h)",
         "none" if min_gap == float("inf") else f"{min_gap:.0f} min" + (f" (at {min_at:%H:%M} UTC)" if min_at else ""),
         status(min_gap >= MIN_GAP_ALERT_MIN)),
        ("Scans tagged with a data-only or missing code commit", tag_note,
         "INFO" if bad_tags is None else status(bad_tags == 0)),
        ("Scans with errors", f"{len(errs)} of {len(sc)}", status(not errs, warn=len(errs) <= 2)),
        ("Tokens seen / liquid (median per scan)",
         f"{med([f(s['n_tokens']) for s in sc])} / {med([f(s['n_liquid']) for s in sc])}", status(bool(sc))),
        ("Deep-checked coins left UNVERIFIED", f"{unv} of {len(deep)} ({pct(unv / len(deep) if deep else None)})",
         status(not deep or unv / len(deep) <= UNVERIFIED_ALERT)),
        ("Safety canary (deep checks run when no coin reached them)",
         f"{can_n} checked, {can_unv} unverified, {can_err} on-chain errors",
         "INFO" if not can_n else status(can_unv / can_n <= UNVERIFIED_ALERT and not can_err, warn=True)),
        ("Gate-passers skipped by check budget", f"{notc} of {len(passers)}",
         status(not passers or notc / len(passers) <= NOT_CHECKED_ALERT, warn=True)),
        ("Paper candidates (last 24h)", str(len(cands)), "INFO"),
        ("Labels finished / unknown or unreliable (last 24h)", f"{len(fin)} / {unk}",
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
    # outcomes excluded as unreliable, by reason and group (the same frozen rules apply to every group)
    out += [f"### Excluded as UNRELIABLE at 60 minutes, by reason (price checks applied equally to all groups)", "",
            "| Group | Finished | invalid | wick_high | wick_low | jump_transient | jump_up | Share excluded |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    codes = ["invalid", "wick_high", "wick_low", "jump_transient", "jump_up"]
    for name, keep in GROUPS.items():
        g = [r for r in lab if r["horizon_min"] == "60" and keep(r) and r["status"] in ("labelled", "unknown", "unreliable")]
        c = Counter(r.get("exit_reason", "").split(":", 1)[1] for r in g if r["status"] == "unreliable" and ":" in r.get("exit_reason", ""))
        ex = sum(c.values())
        out.append(f"| {name} | {len(g)} | " + " | ".join(str(c.get(k, 0)) for k in codes) +
                   f" | {pct(ex / len(g)) if g else '-'} |")
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


def sensitivity(dirs):
    """Re-labels every archived window under different price-check thresholds (and with no checks at all) to show
       whether the frozen rules change any group's result. Reads data_v15/candles/*.jsonl.gz; never writes."""
    import glob, gzip, json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import nexus_v15 as nx
    _, _, labels = load(dirs)
    cand = {}
    for d in dirs:
        for fn in sorted(glob.glob(os.path.join(d, "candles", "*.jsonl.gz"))):
            with gzip.open(fn, "rt") as fh:
                for line in fh:
                    it = json.loads(line)
                    cand[it["sighting_id"]] = [tuple(c) for c in it["candles"]]
    settings = [("strict 3x / 5x", (3.0, 5.0)), ("FROZEN 5x / 10x", (nx.PRICE_WICK_MAX, nx.PRICE_JUMP_MAX)),
                ("loose 10x / 20x", (10.0, 20.0)), ("no price checks", None)]
    out = [f"PRICE-CHECK SENSITIVITY ({REVIEW_VERSION}, rules {nx.PRICE_CHECK_VERSION}) - 60 minutes, net %", "",
           f"Windows with archived candles: {len(cand)} sightings. Labels without archived candles are not included.", "",
           "| Group | Setting | Scored | Excluded | Mean net | Median net |", "| --- | --- | --- | --- | --- | --- |"]
    for name, keep in GROUPS.items():
        rows = [r for r in labels if r["horizon_min"] == "60" and keep(r) and r["sighting_id"] in cand]
        for label, chk in settings:
            nets, excl = [], 0
            for r in rows:
                tp, st = nx.HORIZONS[60]
                res = nx.label_from_candles(cand[r["sighting_id"]], parse(r["t0"]).timestamp(), 60, tp, st,
                                            f(r["cost_pct"]) or 0.0, checks=chk)
                if res is None:
                    continue
                if "unreliable" in res:
                    excl += 1
                    continue
                nets.append(res["net"])
            out.append(f"| {name} | {label} | {len(nets)} | {excl} | {num(sum(nets) / len(nets)) if nets else '-'} | "
                       f"{num(sorted(nets)[len(nets) // 2]) if nets else '-'} |")
    out += ["", "Read: if a group's conclusion changes between settings, the price checks are deciding the result "
            "and the finding must be reported as sensitive to them."]
    return "\n".join(out)


def bounds(dirs):
    """Results that cannot be scored are mostly dead pools or unreliable prices, i.e. likely losses, so a mean
       that leaves them out is flattered. Shows three readings: as reported; dead + unreliable as -100;
       every unscored result as -100 (worst case). Pending labels are not finished and are not included."""
    _, _, labels = load(dirs)
    out = [f"RESULT BOUNDS ({REVIEW_VERSION}) - net % after costs; pending labels excluded", "",
           "| Group | Horizon | Scored | Dead or unreliable | Other unknown | Mean as reported | Mean, dead as -100 | "
           "Mean, all unscored as -100 | Median as reported |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, keep in GROUPS.items():
        for h in HORIZONS:
            sel = [r for r in labels if r["horizon_min"] == str(h) and keep(r)]
            nets = [f(r["net_pct"]) for r in sel if r["status"] == "labelled" and f(r["net_pct"]) is not None]
            dead = sum(1 for r in sel if r["status"] == "unreliable" or
                       (r["status"] == "unknown" and "pool dead" in r.get("note", "")))
            other = sum(1 for r in sel if r["status"] == "unknown" and "pool dead" not in r.get("note", ""))
            if not nets and not dead and not other:
                out.append(f"| {name} | {h} | 0 | 0 | 0 | - | - | - | - |")
                continue
            m = lambda xs: num(sum(xs) / len(xs)) if xs else "-"
            out.append(f"| {name} | {h} | {len(nets)} | {dead} | {other} | {m(nets)} | {m(nets + [-100.0] * dead)} | "
                       f"{m(nets + [-100.0] * (dead + other))} | {num(sorted(nets)[len(nets) // 2]) if nets else '-'} |")
    return "\n".join(out)


def sample_size(dirs, mus=(5.0, 10.0), rhos=(0.0, 0.02, 0.05, 0.10), rates=(0.2, 0.5), ks=(5, 2), power=0.80):
    """Round 3 sample sizes. Every input is printed with its source so the table can be reproduced by hand.
       Unit: one SELECTED token (a token the hypothesis picks from the eligible set E), counted once, at its first
       eligible sighting. Eligible token = a liquid (B0) token seen for the first time (label_this=1).
       Formula (one-sided test that the mean 60-min net return of the selected tokens is above 0):
         n = (z[1 - alpha] + z[power])^2 * sd^2 / mu^2 * DE,   DE = 1 + (m - 1) * rho
         m = selected tokens per day = eligible tokens per day * selection rate;  days = n / m
         alpha = Holm's strictest step = 0.05 / k  (k = number of confirmatory hypotheses)."""
    from statistics import NormalDist, stdev
    N = NormalDist()
    scans, sights, labels = load(dirs)
    b0 = [f(r["net_pct"]) for r in labels if r["horizon_min"] == "60" and r["status"] == "labelled"
          and r["b0_liquid"] == "1"]
    b0 = [x for x in b0 if x is not None]
    sd = stdev(b0) if len(b0) > 1 else float("nan")
    gap_ok = {s["scan_id"] for s in scans if s.get("gap_min_before") and (f(s["gap_min_before"]) or 1e9) <= GAP_ALERT_MIN}
    new = Counter(r["scan_id"] for r in sights if r["b0_liquid"] == "1" and r.get("label_this") == "1")
    per_scan = [new[i] for i in gap_ok]
    per_day = 24 * sum(per_scan) / len(per_scan) if per_scan else float("nan")
    zb = N.inv_cdf(power)
    out = [f"SAMPLE SIZE ({REVIEW_VERSION})", "",
           f"sd of 60-min net return, B0 labelled tokens: {sd:.2f} points (sample sd, n={len(b0)})",
           f"eligible tokens per day: {per_day:.1f} = 24 x mean new eligible tokens per hourly scan "
           f"({sum(per_scan)}/{len(per_scan)} scans that followed a gap of {GAP_ALERT_MIN} min or less; "
           f"catch-up scans after outages excluded)",
           f"power {power:.0%} (z={zb:.4f}); one-sided; alpha = 0.05/k", "",
           "| k | alpha | z | mu | rho | rate | m/day | DE | n selected | days |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for k in ks:
        a = 0.05 / k
        za = N.inv_cdf(1 - a)
        for mu in mus:
            for rho in rhos:
                for rate in rates:
                    m = per_day * rate
                    de = 1 + (m - 1) * rho
                    n = (za + zb) ** 2 * sd ** 2 / mu ** 2 * de
                    ok = math.isfinite(n) and m > 0
                    out.append(f"| {k} | {a:.3f} | {za:.4f} | +{mu:g} | {rho:g} | {rate:.0%} | {m:.1f} | {de:.2f} | "
                               f"{math.ceil(n) if ok else '-'} | {math.ceil(n / m) if ok else '-'} |")
    return "\n".join(out)


def main():
    args = sys.argv[1:]
    dirs = [args[i + 1] for i, a in enumerate(args) if a == "--data"] or ["data_v15"]
    now = next((parse(args[i + 1]) for i, a in enumerate(args) if a == "--now"), datetime.now(timezone.utc))
    if "--bounds" in args:
        print(bounds(dirs))
    elif "--sample-size" in args:
        print(sample_size(dirs))
    elif "--sensitivity" in args:
        print(sensitivity(dirs))
    elif "--weekly" in args:
        print(weekly(dirs, now))
    else:
        print(daily(dirs, now)[0])


if __name__ == "__main__":
    main()
