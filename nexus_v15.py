"""
Nexus Scanner v1.5.0 - risk-first selection + honest measurement.  PAPER ONLY.

What this file does (plain English):
  1. Every run it looks at the same token feeds as v1.4.2 (DEX Screener + GeckoTerminal), plus
     GeckoTerminal "trending" pools so older tokens are seen too.
  2. It records EVERY token it sees, with the facts known at that moment ("as of" rows).
  3. It applies a risk-first decision: liquidity, executable exit, token safety and market
     conditions must all pass. Unknown data never passes. There is no narrative/meme score.
  4. Later, it labels what a fixed paper strategy would have earned at 5, 15, 30, 60 and 240
     minutes, using one-minute price candles from the pool that was recorded at the time.
     Labels are written once and never repriced. Missing data stays UNKNOWN, never a loss.
  5. It sends Telegram messages: paper candidates, a per-scan summary, errors, and a daily report.

What it never does: hold keys, connect a wallet, sign or send a transaction, or place a trade.
No probability is shown until a bucket has been validated (it is not, in this version).

The v1.4.2 file (concept_scorer_v1_4.py) is NOT changed: it is the frozen baseline. This file only
borrows its data fetchers and safety checks, and records the old verdict for comparison.
"""
import csv
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import concept_scorer_v1_4 as legacy

VERSION = "1.5.0"
DATA_DIR = os.environ.get("NEXUS_V15_DATA", "data_v15")

# ---------------------------------------------------------------- tunable rules (frozen for the test)
MIN_LIQ_USD = 15_000            # liquidity floor (same as the v1.4.2 base floor = baseline B0)
MIN_AGE_H = 3.0                 # hypothesis H1 from the 31 Oct review: tokens >= 3h old. NOT validated.
MAX_ONE_WAY_IMPACT_PCT = 5.0    # a $50 trade must not move the price more than this
MAX_SELL_LOSS_PCT = 15.0        # Jupiter sell quote for $50 must not lose more than this
BLOCKED_REGIMES = ("RED", "DEEP_RED")   # abstain when the wider market is falling
DEEP_CHECKS_PER_RUN = 8         # safety checks are slow; most-mature, most-liquid coins first
PAPER_SIZE_USD = 50
COST_BUFFER_PCT = 1.0           # extra cost on top of modelled fees + impact
ENTRY_DELAY_MIN = 2             # paper entry 2 minutes after the signal
RUG_DROP = 0.90                 # price falling 90%+ from entry inside a window = scored as -100%
HORIZONS = {                    # minutes: (take profit %, stop %)  - fixed in advance, never tuned on results
    5: (10, -8), 15: (20, -12), 30: (30, -18), 60: (40, -25), 240: (80, -40)}
LABEL_AFTER_MIN = 240 + ENTRY_DELAY_MIN + 5   # all horizons are labelled in one go after this
LABEL_GIVE_UP_H = 72            # after this, a label that still has no data is UNKNOWN for good
DEAD_LIQ_USD = 500
DEAD_CONFIRM_GAP_MIN = 30       # "dead" needs two readings at least this far apart (one blip is not death)
ALERT_COOLDOWN_H = 24           # the same token is not alerted twice within this
SCAN_GAP_ALERT_MIN = 90         # warn on Telegram if scans stopped for this long
ERROR_ALERT_COOLDOWN_H = 6
REPORT_HOUR_UTC = 8             # daily performance report at the first scan after this hour
MIN_BUCKET_N = 30               # a bucket's history is shown only from this many labels
PROB_VALIDATED = False          # stays False until the CEO signs off a held-out validation

RULE_KEYS = ["MIN_LIQ_USD", "MIN_AGE_H", "MAX_ONE_WAY_IMPACT_PCT", "MAX_SELL_LOSS_PCT", "BLOCKED_REGIMES",
             "DEEP_CHECKS_PER_RUN", "PAPER_SIZE_USD", "COST_BUFFER_PCT", "ENTRY_DELAY_MIN", "RUG_DROP",
             "HORIZONS", "DEAD_LIQ_USD", "DEAD_CONFIRM_GAP_MIN"]


def rules_version():
    blob = json.dumps({k: globals()[k] for k in RULE_KEYS}, sort_keys=True, default=str)
    return f"{VERSION}-{hashlib.sha1(blob.encode()).hexdigest()[:6]}"


# ---------------------------------------------------------------- files
SCANS = "scans.csv"
SIGHTINGS = "sightings.csv"
LABELS = "labels.csv"
POOLS = "pools.json"
STATE_FILE = "state.json"
DEAD_FILE = "dead_checks.json"

SCAN_COLS = ["scan_id", "started_at", "finished_at", "version", "rules", "weather", "n_tokens", "n_liquid",
             "n_deep", "n_candidates", "n_unverified", "n_rejected", "errors", "gap_min_before"]
SIGHT_COLS = ["sighting_id", "scan_id", "seen_at", "mint", "symbol", "pool", "source", "price_usd", "liq_usd",
              "liq_known", "mcap_usd", "age_h", "ch_h1", "weather", "rt_cost_pct", "b0_liquid",
              "legacy_gate", "legacy_score", "legacy_deep", "deep_checked", "decision", "reasons", "h1_mature",
              "bucket", "label_this", "rules"]
LABEL_COLS = ["sighting_id", "mint", "pool", "t0", "horizon_min", "status", "entry_px", "exit_px",
              "exit_reason", "gross_pct", "net_pct", "cost_pct", "decision", "b0_liquid", "legacy_gate",
              "legacy_deep", "h1_mature", "bucket", "labelled_at", "attempts", "note", "rules"]


def path(name):
    return os.path.join(DATA_DIR, name)


def ensure_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    for name, cols in ((SCANS, SCAN_COLS), (SIGHTINGS, SIGHT_COLS), (LABELS, LABEL_COLS)):
        if not os.path.exists(path(name)):
            with open(path(name), "w", newline="") as f:
                csv.writer(f).writerow(cols)
    for name in (POOLS, STATE_FILE, DEAD_FILE):
        if not os.path.exists(path(name)):
            save_json(name, {})


def load_rows(name):
    with open(path(name), newline="") as f:
        return list(csv.DictReader(f))


def append_rows(name, cols, rows):
    with open(path(name), "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        for r in rows:
            w.writerow(r)


def write_rows(name, cols, rows):
    tmp = path(name) + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, path(name))


def load_json(name):
    try:
        with open(path(name)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(name, obj):
    tmp = path(name) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
    os.replace(tmp, path(name))


def iso(t):
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(s):
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def f2(x):
    return legacy.to_float(x)


# ---------------------------------------------------------------- measurement layer (defect fixes)
def round_trip_cost_pct(liq):
    """One cost convention for everything (F04): modelled fees + impact for $50, plus a buffer.
       Unknown liquidity -> None (the coin cannot be a candidate)."""
    c = legacy.est_costs(liq, PAPER_SIZE_USD) if liq else None
    return None if not c else c["round_trip_pct"] + COST_BUFFER_PCT


def net_return(gross_pct, cost_pct):
    """F04: a position can never lose more than its stake. -100% is a total loss, costs included."""
    return max(-100.0, gross_pct - cost_pct)


def pin_pool(pools, mint, pool):
    """N3: the first pool recorded for a coin is the one it is always measured on."""
    if mint not in pools and pool:
        pools[mint] = pool
    return pools.get(mint)


def liquidity_known(p):
    """N2: liquidity of 0 and missing liquidity are both treated as NOT KNOWN, never as 'dead'."""
    liq = legacy.liquidity_of(p)
    return liq if liq and liq > 0 else None


def dead_check(dead, mint, liq, now):
    """F07/F02: a pool is 'dead' only after two low-liquidity readings at least DEAD_CONFIRM_GAP_MIN apart.
       A failed or empty lookup (liq None) records nothing. Returns True only when confirmed."""
    if liq is None:
        return False
    rec = dead.get(mint)
    if liq >= DEAD_LIQ_USD:
        dead.pop(mint, None)
        return False
    if rec is None:
        dead[mint] = {"first_low": iso(now)}
        return False
    return (now - parse(rec["first_low"])).total_seconds() / 60 >= DEAD_CONFIRM_GAP_MIN


def label_from_candles(candles, t0, horizon, tp_pct, stop_pct, cost_pct):
    """Triple-barrier paper label from 1-minute candles [(ts_sec, o, h, l, c), ...] (any order).
       Entry: the first candle starting at or after t0 + ENTRY_DELAY_MIN, filled at that candle's HIGH.
       Exit: first barrier touched. A candle touching both = stop first (pessimistic). Stop fills at the
       candle LOW, not the stop line. A fall of RUG_DROP or more = rug, scored -100%. Time barrier = close
       of the last candle inside the window. Returns dict or None when the data cannot decide (UNKNOWN)."""
    start = t0 + ENTRY_DELAY_MIN * 60
    end = start + horizon * 60
    cs = sorted((c for c in candles if start <= c[0] < end + 60), key=lambda c: c[0])
    if not cs:
        return None
    entry_c = cs[0]
    if entry_c[0] - start > 5 * 60:          # no trade within 5 minutes of the planned entry: cannot enter
        return None
    entry = entry_c[2]
    if not entry or entry <= 0:
        return None
    tp, stop = entry * (1 + tp_pct / 100), entry * (1 + stop_pct / 100)
    exit_px, reason = None, None
    for c in cs:
        if c[0] >= end:
            break
        lo, hi = c[3], c[2]
        if lo <= entry * (1 - RUG_DROP):
            return {"entry": entry, "exit": lo, "reason": "rug", "gross": -100.0, "net": -100.0}
        if lo <= stop:
            exit_px, reason = lo, "stop"
            break
        if hi >= tp and c is not entry_c:
            exit_px, reason = tp, "take_profit"
            break
    if exit_px is None:
        inside = [c for c in cs if c[0] < end]
        last = inside[-1]
        if end - last[0] > 15 * 60 and horizon >= 30:   # no trades in the last 15 min of a long window
            return None
        exit_px, reason = last[4], "time"
    gross = 100 * (exit_px - entry) / entry
    return {"entry": entry, "exit": exit_px, "reason": reason, "gross": gross, "net": net_return(gross, cost_pct)}


def fetch_candles(pool, t0, getter=None):
    """1-minute candles for the window after t0, from GeckoTerminal (free). Raises on network trouble."""
    getter = getter or legacy.get_json
    before = int(t0 + (ENTRY_DELAY_MIN + 240 + 10) * 60)
    url = (f"{legacy.GECKO}/networks/solana/pools/{pool}/ohlcv/minute?aggregate=1&limit=300"
           f"&before_timestamp={before}&currency=usd")
    d = getter(url)
    rows = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows if len(r) >= 5]


def pool_liquidity(pool, getter=None):
    """Liquidity of the PINNED pool. A failed or empty lookup returns None (unknown), never 0."""
    getter = getter or legacy.get_json
    try:
        d = getter(f"{legacy.DEX}/latest/dex/pairs/solana/{pool}")
    except Exception:
        return None
    pairs = d.get("pairs") or ([d["pair"]] if d.get("pair") else [])
    if not pairs:
        return None
    liq = f2((pairs[0].get("liquidity") or {}).get("usd"))
    return liq if liq is not None and liq >= 0 else None


def dead_lookup_live(row, dead, now):
    return dead_check(dead, row["pool"], pool_liquidity(row["pool"]), now)


def label_pending(now, getter=None, dead_lookup=None):
    """Labels every horizon for sightings that are old enough. Each label is written ONCE (F03).
       Network failure -> stays pending and is retried (F02). No data after LABEL_GIVE_UP_H -> 'unknown'."""
    rows = load_rows(LABELS)
    dead = load_json(DEAD_FILE)
    done = 0
    by_sight = {}
    for r in rows:
        if r["status"] == "pending":
            by_sight.setdefault(r["sighting_id"], []).append(r)
    for sid, group in by_sight.items():
        t0 = parse(group[0]["t0"])
        age_min = (now - t0).total_seconds() / 60
        if age_min < LABEL_AFTER_MIN:
            continue
        try:
            candles = fetch_candles(group[0]["pool"], t0.timestamp(), getter)
        except Exception as e:
            for r in group:
                r["attempts"] = str(int(r["attempts"] or 0) + 1)
                r["note"] = f"lookup failed, will retry ({str(e)[:60]})"
            continue
        for r in group:
            h = int(r["horizon_min"])
            tp, st = HORIZONS[h]
            res = label_from_candles(candles, t0.timestamp(), h, tp, st, f2(r["cost_pct"]) or 0.0)
            r["attempts"] = str(int(r["attempts"] or 0) + 1)
            if res is None:
                confirmed_dead = dead_lookup(r, dead, now) if dead_lookup else False
                if confirmed_dead:
                    r.update(status="labelled", exit_reason="rug_confirmed", gross_pct="-100.0",
                             net_pct="-100.0", labelled_at=iso(now), note="pool confirmed dead twice")
                    done += 1
                elif age_min > LABEL_GIVE_UP_H * 60:
                    r.update(status="unknown", labelled_at=iso(now), note="no candle data; NOT counted as a loss")
                else:
                    r["note"] = "not enough candle data yet"
                continue
            r.update(status="labelled", entry_px=f"{res['entry']:.12g}", exit_px=f"{res['exit']:.12g}",
                     exit_reason=res["reason"], gross_pct=f"{res['gross']:.2f}", net_pct=f"{res['net']:.2f}",
                     labelled_at=iso(now), note="")
            done += 1
    write_rows(LABELS, LABEL_COLS, rows)
    save_json(DEAD_FILE, dead)
    return done


# ---------------------------------------------------------------- risk-first decision
def bucket_of(liq, age_h, weather):
    lb = "liq?" if not liq else ("liq15-50k" if liq < 50_000 else ("liq50-200k" if liq < 200_000 else "liq200k+"))
    ab = "age?" if age_h is None else ("age<3h" if age_h < 3 else ("age3-24h" if age_h < 24 else "age24h+"))
    return f"{lb}|{ab}|{weather}"


def age_at(p, now):
    """Token age in hours at the scan time (not at whatever time the code happens to run)."""
    created = p.get("pairCreatedAt")
    return (now.timestamp() * 1000 - created) / 3.6e6 if created else None


def cheap_gate(p, weather, now):
    """Checks that need no extra API calls. Returns (fails, unknowns)."""
    fails, unknown = [], []
    liq = liquidity_known(p)
    age = age_at(p, now)
    if liq is None:
        unknown.append("liquidity unknown")
    elif liq < MIN_LIQ_USD:
        fails.append(f"liquidity ${liq:,.0f} under ${MIN_LIQ_USD:,}")
    else:
        c = legacy.est_costs(liq, PAPER_SIZE_USD)
        if c and c["impact_pct"] > MAX_ONE_WAY_IMPACT_PCT:
            fails.append(f"${PAPER_SIZE_USD} trade moves price {c['impact_pct']:.1f}%")
    if age is None:
        unknown.append("age unknown")
    elif age < MIN_AGE_H:
        fails.append(f"younger than {MIN_AGE_H:g}h (H1 maturity rule)")
    if weather in BLOCKED_REGIMES:
        fails.append(f"market regime {weather}: abstain")
    ch1 = f2((p.get("priceChange") or {}).get("h1"))
    if ch1 is not None and ch1 <= legacy.COLLAPSE_1H:
        fails.append(f"collapsing {ch1:.0f}% in 1h")
    h1 = (p.get("txns") or {}).get("h1") or {}
    if h1.get("buys", 0) > 20 and h1.get("sells", 0) == 0:
        fails.append("buys but no sells (possible honeypot)")
    return fails, unknown


def deep_check(p, checks=None):
    """Safety checks from v1.4.2 (RPC authorities + Token-2022 traps + holders, RugCheck, Jupiter sell quote,
       pool trade patterns). Returns (legacy_verdict, fails, unknowns, warns)."""
    mint = p["baseToken"]["address"]
    checks = checks or {"rpc": lambda m: legacy.check_rpc(m, p.get("pairAddress")),
                        "rug": legacy.check_rugcheck, "sell": legacy.check_sell, "pool": legacy.check_pool}
    rpc_d = rug_d = sell_d = pool_d = None
    unknown = []
    try:
        rpc_d = checks["rpc"](mint)
    except Exception as e:
        unknown.append(f"on-chain check failed ({str(e)[:50]})")
    try:
        rug_d = checks["rug"](mint)
    except Exception as e:
        unknown.append(f"RugCheck failed ({str(e)[:50]})")
    if rpc_d is not None:
        try:
            sell_d = checks["sell"](mint, rpc_d.get("decimals"), p.get("priceUsd"))
        except Exception as e:
            unknown.append(f"sell quote failed ({str(e)[:50]})")
    else:
        unknown.append("sell quote not tried (no on-chain data)")
    if p.get("pairAddress"):
        try:
            pool_d = checks["pool"](p["pairAddress"])
        except Exception as e:
            unknown.append(f"pool check failed ({str(e)[:50]})")
    verdict, fails, warns = legacy.judge(rpc_d, rug_d, pool_d, sell_d)
    if verdict == "UNVERIFIED":
        unknown += fails
        fails = []
    if rpc_d is not None and not rpc_d.get("holders_read"):
        unknown.append("holder concentration unreadable")
    if sell_d is None:
        unknown.append("no sell quote")
    elif sell_d.get("ok") and (sell_d.get("loss_pct") or 0) > MAX_SELL_LOSS_PCT:
        fails.append(f"selling ${PAPER_SIZE_USD} loses {sell_d['loss_pct']:.0f}%")
    return verdict, fails, unknown, warns


def decide(cheap_fails, cheap_unknown, deep):
    """REJECT if any hard check fails; UNVERIFIED if anything needed is unknown (F01: never a candidate);
       CANDIDATE only when every check passed. NOT_CHECKED when the deep-check budget ran out."""
    if cheap_fails:
        return "REJECT", cheap_fails
    if deep is None:
        return ("UNVERIFIED", cheap_unknown) if cheap_unknown else ("NOT_CHECKED", ["deep-check budget used"])
    _, fails, unknown, _ = deep
    if fails:
        return "REJECT", fails
    if cheap_unknown or unknown:
        return "UNVERIFIED", cheap_unknown + unknown
    return "CANDIDATE", ["liquidity, exit, safety and market checks all passed",
                         f"age >= {MIN_AGE_H:g}h (hypothesis H1, not validated)"]


# ---------------------------------------------------------------- feeds
def fetch_trending(getter=None):
    """Older, active pools (the population the maturity hypothesis is about)."""
    getter = getter or legacy.get_json
    out = {}
    try:
        for pool in (getter(f"{legacy.GECKO}/networks/solana/trending_pools").get("data") or []):
            pair = legacy.gecko_to_pair(pool)
            if pair:
                out[pair["baseToken"]["address"]] = pair
    except Exception as e:
        print("GeckoTerminal trending feed failed:", e)
    return out


def gather(fetch_live=None, fetch_trend=None, enrich=None):
    fetch_live = fetch_live or (lambda: legacy.fetch_live())
    fetch_trend = fetch_trend or fetch_trending
    pairs, profiles = fetch_live()
    seen = {p["baseToken"]["address"] for p in pairs}
    for mint, pair in fetch_trend().items():
        if mint not in seen:
            pairs.append(pair)
            seen.add(mint)
    if enrich is None:
        jup = legacy.fetch_enrichment(pairs)
        legacy.resolve_liquidity(pairs, jup)
    else:
        enrich(pairs)
    return pairs, profiles


# ---------------------------------------------------------------- Telegram
def tg(text, sender=None):
    return (sender or legacy.tg_send)(text)


def bucket_history(bucket, horizon=60):
    rows = [r for r in load_rows(LABELS) if r["bucket"] == bucket and r["horizon_min"] == str(horizon)
            and r["status"] == "labelled"]
    wins = sum(1 for r in rows if (f2(r["net_pct"]) or 0) > 0)
    return wins, len(rows)


def signal_message(s, deep_warns):
    wins, n = bucket_history(s["bucket"])
    if PROB_VALIDATED and n >= MIN_BUCKET_N:
        prob = f"{wins}/{n} paper wins at 60m in this bucket (validated)"
    elif n >= MIN_BUCKET_N:
        prob = f"not validated. Bucket history at 60m: {wins} of {n} paper trades were net positive"
    else:
        prob = f"not validated (this bucket has {n} labelled outcomes; {MIN_BUCKET_N} needed to show history)"
    lines = [f"NEXUS v{VERSION} PAPER CANDIDATE: {s['symbol']}",
             f"Time: {s['seen_at']} UTC",
             f"Risk: all hard checks passed. Liquidity ${f2(s['liq_usd']):,.0f}, age {f2(s['age_h']):.1f}h, "
             f"est. round-trip cost {f2(s['rt_cost_pct']):.1f}%, market {s['weather']}",
             f"Horizons tracked: 5, 15, 30, 60, 240 min (paper entry +{ENTRY_DELAY_MIN} min)",
             f"Probability: {prob}",
             f"Why: {s['reasons']}"]
    if deep_warns:
        lines.append("Cautions: " + "; ".join(deep_warns[:3]))
    lines += [f"Mint: {s['mint']}", f"Pool: {s['pool']}",
              "PAPER ONLY. Not validated. Not financial advice."]
    return "\n".join(lines)


def summary_message(scan, rejected):
    top = {}
    for s in rejected:
        key = s["reasons"].split(";")[0].split(" $")[0].split(" (")[0][:40]
        top[key] = top.get(key, 0) + 1
    common = ", ".join(f"{k} ({v})" for k, v in sorted(top.items(), key=lambda kv: -kv[1])[:3])
    return (f"Nexus v{VERSION} scan {scan['started_at'][11:16]} UTC: {scan['n_tokens']} tokens, "
            f"{scan['n_liquid']} liquid, {scan['n_candidates']} candidates, {scan['n_unverified']} unverified, "
            f"{scan['n_rejected']} rejected. Top reasons: {common or 'none'}. Weather {scan['weather']}.")


def error_alert(state, text, now, sender=None):
    """Errors go to Telegram, but the same error at most once per ERROR_ALERT_COOLDOWN_H."""
    key = hashlib.sha1(text.encode()).hexdigest()[:10]
    sent = state.setdefault("errors_sent", {})
    last = sent.get(key)
    if last and (now - parse(last)).total_seconds() < ERROR_ALERT_COOLDOWN_H * 3600:
        return False
    sent[key] = iso(now)
    return tg(f"NEXUS v{VERSION} ERROR: {text}", sender)


def should_alert(state, mint, now):
    """Duplicate suppression: one alert per token per ALERT_COOLDOWN_H."""
    last = state.setdefault("alerted", {}).get(mint)
    return not (last and (now - parse(last)).total_seconds() < ALERT_COOLDOWN_H * 3600)


def mark_alerted(state, mint, now):
    state.setdefault("alerted", {})[mint] = iso(now)


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - m), min(1.0, c + m)


def performance_report(now):
    rows = [r for r in load_rows(LABELS) if r["rules"] == rules_version()]
    groups = {"B0 liquid (baseline)": lambda r: r["b0_liquid"] == "1",
              "Legacy v1.4.2 gate": lambda r: r["legacy_gate"] == "1",
              "v1.5 candidates": lambda r: r["decision"] == "CANDIDATE"}
    lines = [f"NEXUS v{VERSION} daily paper report {now:%d %b %Y} (rules {rules_version()}). NOT validated."]
    for h in (60, 240):
        lines.append(f"-- {h} min --")
        for name, keep in groups.items():
            g = [r for r in rows if r["horizon_min"] == str(h) and keep(r)]
            lab = [f2(r["net_pct"]) for r in g if r["status"] == "labelled"]
            unk = sum(1 for r in g if r["status"] == "unknown")
            pend = sum(1 for r in g if r["status"] == "pending")
            if not lab:
                lines.append(f"{name}: 0 labelled ({pend} pending, {unk} unknown)")
                continue
            wins = sum(1 for x in lab if x > 0)
            ci = wilson(wins, len(lab))
            lines.append(f"{name}: {len(lab)} labelled, {wins} net-positive "
                         f"({100 * ci[0]:.0f}-{100 * ci[1]:.0f}% range), mean {sum(lab) / len(lab):+.1f}%, "
                         f"{pend} pending, {unk} unknown")
    lines.append("Unknown outcomes are excluded, never counted as losses.")
    return "\n".join(lines)


# ---------------------------------------------------------------- one scan
def run(now=None, deps=None, sender=None):
    """deps (for tests): {'gather', 'weather', 'deep_checks', 'candles_getter', 'dead_lookup'}"""
    deps = deps or {}
    now = now or datetime.now(timezone.utc)
    ensure_files()
    state, pools = load_json(STATE_FILE), load_json(POOLS)
    scan_id = now.strftime("%Y%m%dT%H%M%S")
    errors = []

    prev = state.get("last_scan_finished")
    gap = (now - parse(prev)).total_seconds() / 60 if prev else None
    if gap is not None and gap > SCAN_GAP_ALERT_MIN:                       # F05: gaps are reported, not hidden
        error_alert(state, f"scans stopped for {gap / 60:.1f}h before this run", now, sender)

    try:
        weather = (deps.get("weather") or (lambda: legacy.market_weather()["regime"]))()
    except Exception as e:
        weather = "UNKNOWN"
        errors.append(f"market weather failed: {e}")
    try:
        pairs, profiles = (deps.get("gather") or gather)()
    except Exception as e:
        pairs, profiles = [], {}
        errors.append(f"feeds failed: {e}")

    firsts = {r["mint"] for r in load_rows(SIGHTINGS) if r["b0_liquid"] == "1"}
    sightings, order = [], []
    for p in pairs:
        mint = p["baseToken"]["address"]
        liq = liquidity_known(p)
        age = age_at(p, now)
        fails, unknown = cheap_gate(p, weather, now)
        try:
            lgate, _, _ = legacy.safety_gate(p, legacy.BASE_MIN_LIQUIDITY, {})
            _, lscore = legacy.score_concept(p, profiles.get(mint))
        except Exception:
            lgate, lscore = False, ""
        pool = pin_pool(pools, mint, p.get("pairAddress"))
        s = {"sighting_id": f"{scan_id}-{mint[:8]}", "scan_id": scan_id, "seen_at": iso(now), "mint": mint,
             "symbol": (p["baseToken"].get("symbol") or "?")[:20], "pool": pool or "",
             "source": p.get("_source", ""), "price_usd": p.get("priceUsd") or "",
             "liq_usd": f"{liq:.2f}" if liq else "", "liq_known": "1" if liq else "0",
             "mcap_usd": p.get("marketCap") or p.get("fdv") or "", "age_h": f"{age:.2f}" if age is not None else "",
             "ch_h1": (p.get("priceChange") or {}).get("h1", ""), "weather": weather,
             "rt_cost_pct": f"{round_trip_cost_pct(liq):.2f}" if liq else "",
             "b0_liquid": "1" if liq and liq >= MIN_LIQ_USD else "0", "legacy_gate": "1" if lgate else "0",
             "legacy_score": lscore, "legacy_deep": "", "deep_checked": "0", "decision": "", "reasons": "",
             "h1_mature": "1" if age is not None and age >= MIN_AGE_H else "0",
             "bucket": bucket_of(liq, age, weather), "label_this": "0", "rules": rules_version(),
             "_p": p, "_fails": fails, "_unknown": unknown}
        sightings.append(s)
        if not fails:
            order.append(s)

    order.sort(key=lambda s: (-(f2(s["age_h"]) or 0), -(f2(s["liq_usd"]) or 0)))   # most mature, most liquid first
    deep_fn = deps.get("deep_checks")
    deep_results = {}
    for s in order[:DEEP_CHECKS_PER_RUN]:
        try:
            deep_results[s["sighting_id"]] = deep_check(s["_p"], deep_fn(s["_p"]) if deep_fn else None)
        except Exception as e:
            errors.append(f"deep check crashed for {s['symbol']}: {e}")
    candidates, rejected = [], []
    for s in sightings:
        deep = deep_results.get(s["sighting_id"])
        if deep:
            s["deep_checked"], s["legacy_deep"] = "1", deep[0]
        decision, reasons = decide(s["_fails"], s["_unknown"], deep)
        s["decision"], s["reasons"] = decision, "; ".join(reasons)[:300]
        s["_warns"] = deep[3] if deep else []
        first_liquid = s["b0_liquid"] == "1" and s["mint"] not in firsts
        if first_liquid:
            firsts.add(s["mint"])
        s["label_this"] = "1" if (first_liquid or decision == "CANDIDATE") and s["pool"] else "0"
        (candidates if decision == "CANDIDATE" else rejected).append(s)

    append_rows(SIGHTINGS, SIGHT_COLS, sightings)
    new_labels = []
    for s in sightings:
        if s["label_this"] != "1":
            continue
        for h in HORIZONS:
            new_labels.append({"sighting_id": s["sighting_id"], "mint": s["mint"], "pool": s["pool"],
                               "t0": s["seen_at"], "horizon_min": h, "status": "pending",
                               "cost_pct": s["rt_cost_pct"], "decision": s["decision"],
                               "b0_liquid": s["b0_liquid"], "legacy_gate": s["legacy_gate"],
                               "legacy_deep": s["legacy_deep"], "h1_mature": s["h1_mature"],
                               "bucket": s["bucket"], "attempts": "0", "rules": rules_version()})
    append_rows(LABELS, LABEL_COLS, new_labels)
    save_json(POOLS, pools)

    try:
        n_labelled = label_pending(now, deps.get("candles_getter"), deps.get("dead_lookup", dead_lookup_live))
    except Exception as e:
        n_labelled = 0
        errors.append(f"labelling failed: {e}")

    sent = 0
    for s in candidates:
        if should_alert(state, s["mint"], now) and tg(signal_message(s, s["_warns"]), sender):
            mark_alerted(state, s["mint"], now)
            sent += 1
    scan = {"scan_id": scan_id, "started_at": iso(now), "finished_at": iso(datetime.now(timezone.utc)),
            "version": VERSION, "rules": rules_version(), "weather": weather, "n_tokens": len(sightings),
            "n_liquid": sum(1 for s in sightings if s["b0_liquid"] == "1"), "n_deep": len(deep_results),
            "n_candidates": len(candidates), "n_unverified": sum(1 for s in sightings if s["decision"] == "UNVERIFIED"),
            "n_rejected": sum(1 for s in sightings if s["decision"] == "REJECT"),
            "errors": " | ".join(errors)[:500], "gap_min_before": f"{gap:.0f}" if gap is not None else ""}
    append_rows(SCANS, SCAN_COLS, [scan])
    tg(summary_message(scan, [s for s in rejected if s["decision"] != "NOT_CHECKED"]), sender)
    for e in errors:
        error_alert(state, e, now, sender)
    if not pairs:
        error_alert(state, "no tokens returned by any feed this run", now, sender)
    today = now.strftime("%Y-%m-%d")
    if now.hour >= REPORT_HOUR_UTC and state.get("last_report") != today:
        if tg(performance_report(now), sender):
            state["last_report"] = today
    state["last_scan_finished"] = iso(now)
    save_json(STATE_FILE, state)
    scan["labelled_now"], scan["alerts_sent"] = n_labelled, sent
    return scan


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        import unittest
        suite = unittest.defaultTestLoader.loadTestsFromName("test_nexus_v15")
        ok = unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()
        sys.exit(0 if ok else 1)
    if "--telegram-test" in args:
        ok = tg(f"Nexus v{VERSION} test notification (rules {rules_version()}). PAPER ONLY.")
        print("Telegram test notification delivered." if ok else "Telegram test FAILED: check the two secrets.")
        sys.exit(0 if ok else 1)
    if "--report" in args:
        ensure_files()
        print(performance_report(datetime.now(timezone.utc)))
        return
    scan = run()
    print(json.dumps(scan, indent=1))


if __name__ == "__main__":
    main()
