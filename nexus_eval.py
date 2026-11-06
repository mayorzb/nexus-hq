"""eval-2 report: the frozen protocol in PROTOCOL_EVAL2.md, applied to the paper records. Read only.

    python3 nexus_eval.py --data data_v15 [--protocol eval-2] [--json]

Same records -> same report (seeded bootstrap). Prints the token funnel, every pair, every comparator reuse,
the scan-level after-cost difference, how often young did worse, no-valid-entry counts, and milestone status.
"""
import argparse, collections, csv, json, math, os, random, re, statistics as st, sys

REGIME = re.compile(r"market regime (RED|DEEP_RED)")
NONFAIL = ("deep-check budget used",)
PASS = ("UNVERIFIED", "NOT_CHECKED", "CANDIDATE")
RATIO = (0.5, 2.0)
REUSE_CAP = 2
BIG_LOSS = -20.0
MILESTONE_PAIRS, MILESTONE_SCANS, SHORTFALL_SCANS = 50, 20, 40
BOOT_N, BOOT_SEED = 2000, 7


def read(p):
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f, restval=""))


def own_fails(s):
    if s.get("decision") in PASS:
        return []
    xs = [x.strip() for x in (s.get("reasons") or "").split(";") if x.strip()]
    return [x for x in xs if not REGIME.search(x) and x not in NONFAIL]


def group_of(s):
    try:
        age = float(s.get("age_h") or "nan")
    except ValueError:
        return "other"
    if math.isnan(age):
        return "other"
    f = own_fails(s)
    if age < 3 and len(f) == 1 and f[0].startswith("younger than"):
        return "young"
    if age >= 3 and not f:
        return "mature"
    return "other"


def pair_scan(young, mature):
    """Frozen matching inside one scan: nearest liquidity, ratio 0.5-2x, each mature used at most REUSE_CAP times."""
    uses = collections.Counter()
    out = []
    for y in sorted(young, key=lambda r: (-float(r["liq_usd"]), r["sighting_id"])):
        ly = float(y["liq_usd"])
        cands = [m for m in mature if RATIO[0] <= float(m["liq_usd"]) / ly <= RATIO[1]]
        free = [m for m in cands if uses[m["sighting_id"]] < REUSE_CAP]
        if not free:
            out.append((y, None, "no eligible comparator" if not cands else "comparators used twice"))
            continue
        m = min(free, key=lambda m: (abs(math.log(float(m["liq_usd"]) / ly)), uses[m["sighting_id"]], m["sighting_id"]))
        uses[m["sighting_id"]] += 1
        out.append((y, m, ""))
    return out


def boot_ci(vals, n=BOOT_N, seed=BOOT_SEED):
    if len(vals) < 2:
        return None
    rnd = random.Random(seed)
    means = sorted(st.mean(rnd.choice(vals) for _ in vals) for _ in range(n))
    return round(means[int(0.025 * n)], 2), round(means[int(0.975 * n) - 1], 2)


def build(data, protocol="eval-2"):
    scans = [r for r in read(os.path.join(data, "scans.csv"))]
    S = [r for r in read(os.path.join(data, "sightings.csv")) if r.get("protocol") == protocol]
    L = {}
    for r in read(os.path.join(data, "labels.csv")):
        if r.get("protocol") == protocol and r["horizon_min"] == "60":
            L[r["sighting_id"]] = r
    scan_ids = sorted({s["scan_id"] for s in S})
    f = collections.OrderedDict()
    f["eval-2 scans"] = len(scan_ids)
    f["sightings"] = len(S)
    liquid = [s for s in S if s["b0_liquid"] == "1"]
    f["liquid sightings"] = len(liquid)
    first = [s for s in S if s["label_this"] == "1"]
    f["first liquid sightings = unique tokens with an outcome row"] = len(first)
    for s in first:
        s["_group"] = group_of(s)
        lab = L.get(s["sighting_id"]) or {}
        s["_status"] = lab.get("status", "no label row")
        s["_net"] = float(lab["net_pct"]) if s["_status"] == "labelled" and lab.get("net_pct") else None
        s["_label"] = lab
    for g in ("young", "mature", "other"):
        f[f"  {g}"] = sum(s["_group"] == g for s in first)
    status = {g: collections.Counter(s["_status"] for s in first if s["_group"] == g) for g in ("young", "mature")}
    pairs = []
    for sid in scan_ids:
        Y = [s for s in first if s["scan_id"] == sid and s["_group"] == "young"]
        M = [s for s in first if s["scan_id"] == sid and s["_group"] == "mature"]
        pairs += pair_scan(Y, M)
    matched = [(y, m) for y, m, why in pairs if m]
    f["young with a comparator (cap 2)"] = len(matched)
    f["young without a comparator"] = sum(1 for _, m, _ in pairs if not m)
    yn = [(y, m) for y, m in matched if y["_status"] == "no_valid_entry"]
    f["  pairs: young had no valid entry (counted, not scored)"] = len(yn)
    comp = [(y, m) for y, m in matched if y["_net"] is not None and m["_net"] is not None]
    f["  pairs: young or mature outcome not yet usable"] = len(matched) - len(yn) - len(comp)
    f["complete pairs (both 60m outcomes labelled)"] = len(comp)
    by_scan = collections.defaultdict(list)
    for y, m in comp:
        by_scan[y["scan_id"]].append(y["_net"] - m["_net"])
    scan_means = {k: st.mean(v) for k, v in by_scan.items()}
    f["scans contributing a complete pair"] = len(scan_means)
    diffs = [y["_net"] - m["_net"] for y, m in comp]
    res = {"funnel": f, "status": {g: dict(c) for g, c in status.items()},
           "pairs": [{"scan_id": y["scan_id"], "regime": y["weather"], "young": y["symbol"], "young_sid": y["sighting_id"],
                      "young_liq": y["liq_usd"], "young_status": y["_status"], "young_net": y["_net"],
                      "mature": m["symbol"] if m else "", "mature_sid": m["sighting_id"] if m else "",
                      "mature_liq": m["liq_usd"] if m else "", "mature_status": m["_status"] if m else "",
                      "mature_net": m["_net"] if m else None, "why_unmatched": why} for y, m, why in pairs],
           "reuse": {}, "effect": {}}
    use = collections.Counter(m["sighting_id"] for _, m in matched)
    for msid, k in use.items():
        if k > 1:
            res["reuse"][msid] = [y["symbol"] + " (" + y["scan_id"] + ")" for y, m in matched if m["sighting_id"] == msid]
    if comp:
        sm = list(scan_means.values())
        res["effect"] = {
            "scan_level_mean_diff": round(st.mean(sm), 2), "scan_level_ci95": boot_ci(sm),
            "scans_young_worse": f"{sum(v < 0 for v in sm)}/{len(sm)}",
            "pair_mean_diff": round(st.mean(diffs), 2), "pair_median_diff": round(st.median(diffs), 2),
            "pairs_young_worse": f"{sum(d < 0 for d in diffs)}/{len(diffs)}",
            "share_young_worse_pct": round(100 * sum(d < 0 for d in diffs) / len(diffs), 1),
            "young_big_loss": f"{sum(y['_net'] <= BIG_LOSS for y, _ in comp)}/{len(comp)}",
            "mature_big_loss": f"{sum(m['_net'] <= BIG_LOSS for _, m in comp)}/{len(comp)}"}
    nve = {g: (status[g].get("no_valid_entry", 0), sum(status[g].values())) for g in status}
    res["no_valid_entry"] = {g: f"{a}/{b}" for g, (a, b) in nve.items()}
    done_pairs, done_scans = len(comp), len(scan_means)
    if done_pairs >= MILESTONE_PAIRS and done_scans >= MILESTONE_SCANS:
        res["milestone"] = "REVIEW MILESTONE REACHED: read the result against PROTOCOL_EVAL2.md section 7"
    elif len(scan_ids) >= SHORTFALL_SCANS:
        res["milestone"] = (f"SHORTFALL after {len(scan_ids)} scans: {max(0, MILESTONE_PAIRS - done_pairs)} pairs and "
                            f"{max(0, MILESTONE_SCANS - done_scans)} scans short of the milestone; collection continues")
    else:
        res["milestone"] = (f"collecting: {done_pairs}/{MILESTONE_PAIRS} complete pairs, {done_scans}/{MILESTONE_SCANS} "
                            f"scans, {len(scan_ids)}/{SHORTFALL_SCANS} scans used. No decision before the milestone.")
    return res


def render(r, protocol):
    L = [f"# Paper evaluation {protocol} (frozen protocol: PROTOCOL_EVAL2.md)", "", f"**Status:** {r['milestone']}", "",
         "## Token funnel", "", "| stage | count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in r["funnel"].items()]
    L += ["", "## 60m outcome status by group", ""]
    for g, c in r["status"].items():
        n = sum(c.values())
        L.append(f"- {g}: " + (", ".join(f"{k} {v}/{n}" for k, v in sorted(c.items())) or "none yet"))
    L += [f"- no valid entry: young {r['no_valid_entry'].get('young', '0/0')}, mature {r['no_valid_entry'].get('mature', '0/0')}",
          "", "## Effect (after costs; unit = scan)", ""]
    if r["effect"]:
        e = r["effect"]
        L += [f"- Scan-level mean difference (young - mature): {e['scan_level_mean_diff']} points, 95% interval {e['scan_level_ci95']}; scans with young worse {e['scans_young_worse']}",
              f"- Pairs with young worse: {e['pairs_young_worse']} ({e['share_young_worse_pct']}%); pair mean {e['pair_mean_diff']}, median {e['pair_median_diff']}",
              f"- Big loss (<= -20%): young {e['young_big_loss']}, mature {e['mature_big_loss']}"]
    else:
        L.append("- No complete pairs yet.")
    L += ["", "## Comparator reuse (cap 2)", ""]
    L += [f"- {k}: {', '.join(v)}" for k, v in r["reuse"].items()] or ["- none"]
    L += ["", "## Every pair", "", "| scan | regime | young | liq | status | net | mature | liq | status | net | note |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in r["pairs"]:
        L.append(f"| {p['scan_id']} | {p['regime']} | {p['young']} | {p['young_liq']} | {p['young_status']} | {p['young_net']} | "
                 f"{p['mature']} | {p['mature_liq']} | {p['mature_status']} | {p['mature_net']} | {p['why_unmatched']} |")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_v15")
    ap.add_argument("--protocol", default="eval-2")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = build(a.data, a.protocol)
    print(json.dumps(r, indent=1, default=str) if a.json else render(r, a.protocol))
    return 0


if __name__ == "__main__":
    sys.exit(main())
