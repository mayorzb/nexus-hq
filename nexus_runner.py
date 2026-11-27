"""
Nexus Runner Track 0.1 - early-entry PAPER scanner.  PAPER ONLY.

Goal: get into young, low-cap Solana coins at a good entry point and let real runners run,
while the safety checks keep out as many rugs as possible.

What it does every scan (plain English):
  1. Finds coins from DEX Screener (new profiles + boosts) and GeckoTerminal (new pools, 3 pages).
  2. Keeps coins worth $10k-$100k (market cap) with at least $5k liquidity. ANY age is allowed.
  3. Records ~30 facts about each coin at that moment (buyers vs sellers, volume speed, dip or chase,
     holders, top wallets, dev share, socials...). One entry per coin: the first time it qualifies.
  4. Runs the full safety checks (from v1.4.2): mint/freeze authority, Token-2022 traps, top-10 wallets,
     Jupiter sell test, RugCheck, trade patterns. A coin is a PICK only if every check passed.
     Anything unknown is never a pick.
  5. Follows every coin (picks AND the rest, so we can compare) for 7 days with 5-minute candles and
     scores a fixed paper exit: half out at 2x, the rest trails 40% below the peak, stop -40%.
  6. Telegram: picks, 2x/5x/10x milestones and stop hits for open picks, and a daily report.

What it never does: hold keys, connect a wallet, sign or send a transaction, or place a trade.
Nothing here is validated. Results only count after 300+ finished picks on fresh data.

The frozen v1.5 scanner (nexus_v15.py) and v1.4.2 (concept_scorer_v1_4.py) are NOT changed.
This file borrows v1.4.2's data fetchers and safety checks, read-only.
"""
import csv
import gzip
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import concept_scorer_v1_4 as legacy

VERSION = "runner-0.1"
DATA_DIR = os.environ.get("NEXUS_RUNNER_DATA", "data_runner")

# ---------------------------------------------------------------- rules (FROZEN for the test: change = new version)
MCAP_MIN_USD = 10_000           # early: market cap at entry between these two
MCAP_MAX_USD = 100_000
LIQ_MIN_USD = 5_000             # lower than v1.5's $15k: 7 of the 9 "$50k -> $500k" coins had $5-15k
PAPER_SIZE_USD = 50
MAX_ONE_WAY_IMPACT_PCT = 5.0    # a $50 buy must not move the price more than this
MAX_SELL_LOSS_PCT = 15.0        # Jupiter: selling $50 must not lose more than this
DEEP_CHECKS_PER_SCAN = 10       # safety checks are slow; coins with the most 5-minute buys go first
ENTRY_DELAY_MIN = 2             # paper entry 2 minutes after the signal, at that candle's HIGH (pessimistic)
ENTRY_MAX_WAIT_MIN = 10         # no trade within 10 minutes of the entry time = no entry (unknown, not a loss)
STOP_PCT = -40.0                # initial stop
SCALE_OUT_X = 2.0               # sell half here...
TRAIL_PCT = 40.0                # ...then the rest trails this far below the highest price, never below entry
RUG_FLOOR = 0.10                # a candle trading below 10% of entry = rug: exit at that candle's LOW
HOLD_HOURS = 168                # 7 days, then sell what is left at the last price
LABEL_HOURS = (24, 168)         # an early look at 24h, the final result at 7 days
COST_BUFFER_PCT = 1.0           # on top of modelled fees + price impact (v1.4.2 est_costs)
CANDLE_MIN = 5
LABEL_BUDGET = 8                # labels per scan (each needs 1-3 GeckoTerminal calls)
LABEL_RETRY_MIN = 30
LABEL_GIVE_UP_H = 72            # no usable candles this long after a label is due = UNKNOWN for good
STALE_H = 12                    # no trade in the last 12h of the window and pool liquidity unknown = UNKNOWN
DEAD_LIQ_USD = 500              # pool below this at the end = what is still held is worth nothing (-100%)
WICK_MAX = 5.0                  # a high above 5x the candle body = bad print -> UNRELIABLE (excluded, kept visible)
JUMP_MAX = 10.0                 # a 10x close-to-close jump that falls back next candle = glitch -> UNRELIABLE
MILESTONES = (2, 5, 10)
MAX_PICK_ALERTS_PER_SCAN = 3
REPORT_HOUR_UTC = 8
MIN_RESULT_N = 300              # finished picks needed before anyone calls this profitable or not
MIN_BUCKET_N = 30               # a group in the report is shown only from this many finished coins
ARCHIVE_EVERY = 10              # keep candles for picks, 2x+ coins and 1 in 10 of the rest (repo size)
DIP_H1, CHASE_H1 = -20.0, 100.0 # 1h price change: dip at or below -20%, chase at or above +100%

RULE_KEYS = ["MCAP_MIN_USD", "MCAP_MAX_USD", "LIQ_MIN_USD", "PAPER_SIZE_USD", "MAX_ONE_WAY_IMPACT_PCT",
             "MAX_SELL_LOSS_PCT", "ENTRY_DELAY_MIN", "ENTRY_MAX_WAIT_MIN", "STOP_PCT", "SCALE_OUT_X", "TRAIL_PCT",
             "RUG_FLOOR", "HOLD_HOURS", "COST_BUFFER_PCT", "CANDLE_MIN", "STALE_H", "DEAD_LIQ_USD", "WICK_MAX",
             "JUMP_MAX", "DIP_H1", "CHASE_H1"]


def rules_version():
    blob = json.dumps({k: globals()[k] for k in RULE_KEYS}, sort_keys=True)
    return VERSION + ":" + hashlib.sha256(blob.encode()).hexdigest()[:8]


# ---------------------------------------------------------------- files
SIGHTINGS, LABELS, SCANS, ALERTS, STATE = "sightings.csv", "labels.csv", "scans.csv", "alerts.csv", "state.json"
FEATURE_COLS = ["age_min", "mcap_usd", "fdv_usd", "liq_usd", "liq_to_mcap", "price_usd",
                "pc_m5", "pc_h1", "pc_h6", "pc_h24", "entry_type",
                "buys_m5", "sells_m5", "buys_h1", "sells_h1", "buy_ratio_m5", "buy_ratio_h1",
                "vol_m5", "vol_h1", "vol_h6", "vol_speed",
                "boosts", "n_socials", "has_website", "has_profile", "dex_id", "source",
                "mint_revoked", "freeze_revoked", "top10_wallets_pct", "total_holders", "holders_per_min",
                "creator_pct", "creator_in_top", "insiders", "rug_score", "rug_danger_n", "rug_warn_n",
                "lp_locked_pct", "sell_loss_pct", "drawdown_48h_pct", "trades_n", "distinct_ratio",
                "top_wallet_share", "bot_share", "uniform_share"]
SIGHT_COLS = ["sighting_id", "scan_id", "seen_at", "mint", "symbol", "pool", "decision", "reasons", "warns",
              "deep_checked", "cost_pct"] + FEATURE_COLS + ["rules"]
LABEL_COLS = ["sighting_id", "mint", "symbol", "pool", "seen_at", "decision", "horizon_h", "status", "detail",
              "entry_px", "exit_reason", "exit_min", "gross_pct", "net_pct", "cost_pct", "peak_x", "peak_min", "window_peak_x",
              "hit_2x", "hit_5x", "hit_10x", "min_to_2x", "min_to_5x", "min_to_10x", "max_mcap_usd",
              "n_candles", "candle_file", "labelled_at", "attempts", "rules"]
SCAN_COLS = ["scan_id", "started_at", "finished_at", "version", "rules", "n_pairs", "n_new_eligible",
             "n_deep", "n_not_checked", "n_pick", "n_reject", "n_unverified", "n_labels", "n_open", "errors"]
ALERT_COLS = ["at", "kind", "mint", "symbol", "detail", "sent"]


def path(name):
    return os.path.join(DATA_DIR, name)


def ensure_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    for name, cols in ((SIGHTINGS, SIGHT_COLS), (LABELS, LABEL_COLS), (SCANS, SCAN_COLS), (ALERTS, ALERT_COLS)):
        if not os.path.exists(path(name)):
            with open(path(name), "w", newline="") as fh:
                csv.writer(fh).writerow(cols)


def load_rows(name):
    if not os.path.exists(path(name)):
        return []
    with open(path(name), newline="") as fh:
        return list(csv.DictReader(fh))


def append_rows(name, cols, rows):
    if not rows:
        return
    with open(path(name), "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        for r in rows:
            w.writerow({k: fmt(r.get(k)) for k in cols})


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return "" if not math.isfinite(v) else f"{v:.6g}"
    return str(v)


def load_state():
    try:
        with open(path(STATE)) as fh:
            s = json.load(fh)
    except (OSError, ValueError):
        s = {}
    for k in ("seen", "open", "attempts", "done"):
        s.setdefault(k, {})
    return s


def save_state(s):
    tmp = path(STATE) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(s, fh, indent=1, sort_keys=True)
    os.replace(tmp, path(STATE))


# ---------------------------------------------------------------- helpers
def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def iso(t):
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(s):
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def ratio(a, b):
    a, b = num(a), num(b)
    if a is None or b is None or a + b <= 0:
        return None
    return a / (a + b)


def mcap_of(p):
    return num(p.get("marketCap")) or num(p.get("fdv"))


def liq_of(p):
    return num((p.get("liquidity") or {}).get("usd"))


def cost_pct(liq):
    c = legacy.est_costs(liq, PAPER_SIZE_USD) if liq else None
    return (c["round_trip_pct"] if c else legacy.UNKNOWN_COST_PCT) + COST_BUFFER_PCT


# ---------------------------------------------------------------- selection
def eligible(p):
    """Early coin with a known pool, price, market cap and enough liquidity. No age rule."""
    if p.get("chainId") != "solana":
        return False, "not Solana"
    if not (p.get("baseToken") or {}).get("address") or not p.get("pairAddress"):
        return False, "no mint or pool"
    if not (num(p.get("priceUsd")) or 0) > 0:
        return False, "no price"
    mc, liq = mcap_of(p), liq_of(p)
    if mc is None or not MCAP_MIN_USD <= mc <= MCAP_MAX_USD:
        return False, "market cap outside $10k-$100k"
    if liq is None or liq < LIQ_MIN_USD:
        return False, "liquidity under $5k"
    return True, ""


def entry_type(pc_h1):
    if pc_h1 is None:
        return "unknown"
    return "dip" if pc_h1 <= DIP_H1 else ("chase" if pc_h1 >= CHASE_H1 else "neutral")


def features(p, now, profiles=None):
    tx, vol, pc = p.get("txns") or {}, p.get("volume") or {}, p.get("priceChange") or {}
    m5, h1 = tx.get("m5") or {}, tx.get("h1") or {}
    info = p.get("info") or {}
    created = num(p.get("pairCreatedAt"))
    age_min = (now.timestamp() * 1000 - created) / 60000 if created else None
    mc, liq = mcap_of(p), liq_of(p)
    v5, vh1 = num(vol.get("m5")), num(vol.get("h1"))
    return {
        "age_min": age_min, "mcap_usd": mc, "fdv_usd": num(p.get("fdv")), "liq_usd": liq,
        "liq_to_mcap": liq / mc if liq and mc else None, "price_usd": num(p.get("priceUsd")),
        "pc_m5": num(pc.get("m5")), "pc_h1": num(pc.get("h1")), "pc_h6": num(pc.get("h6")),
        "pc_h24": num(pc.get("h24")), "entry_type": entry_type(num(pc.get("h1"))),
        "buys_m5": num(m5.get("buys")), "sells_m5": num(m5.get("sells")),
        "buys_h1": num(h1.get("buys")), "sells_h1": num(h1.get("sells")),
        "buy_ratio_m5": ratio(m5.get("buys"), m5.get("sells")), "buy_ratio_h1": ratio(h1.get("buys"), h1.get("sells")),
        "vol_m5": v5, "vol_h1": vh1, "vol_h6": num(vol.get("h6")),
        "vol_speed": (v5 * 12 / vh1) if v5 is not None and vh1 else None,   # >1 = last 5 min busier than the hour
        "boosts": num((p.get("boosts") or {}).get("active")) or 0,
        "n_socials": len(info.get("socials") or []), "has_website": bool(info.get("websites")),
        "has_profile": bool(profiles and p["baseToken"]["address"] in profiles),
        "dex_id": p.get("dexId") or "", "source": p.get("_source") or "",
    }


def cheap_fails(p):
    fails = []
    c = legacy.est_costs(liq_of(p), PAPER_SIZE_USD)
    if c and c["impact_pct"] > MAX_ONE_WAY_IMPACT_PCT:
        fails.append(f"${PAPER_SIZE_USD} buy moves price {c['impact_pct']:.1f}%")
    h1 = (p.get("txns") or {}).get("h1") or {}
    if (h1.get("buys") or 0) > 20 and (h1.get("sells") or 0) == 0:
        fails.append("buys but no sells (possible honeypot)")
    return fails


def check_rug(mint):
    """RugCheck report: the same fields v1.4.2 reads, plus holders, dev share and score."""
    rep = legacy.get_json(f"{legacy.RUG}/tokens/{mint}/report",
                          {"X-API-KEY": legacy.RUG_KEY} if legacy.RUG_KEY else None)
    risks = [((r or {}).get("name", "?"), (r or {}).get("level", "?")) for r in rep.get("risks") or []]
    locked = None
    for m in rep.get("markets") or []:
        v = num((((m or {}).get("lp")) or {}).get("lpLockedPct"))
        if v is not None:
            locked = v if locked is None else max(locked, v)
    holders = [h for h in (rep.get("topHolders") or []) if isinstance(h, dict)]
    creator = rep.get("creator")
    supply = num((rep.get("token") or {}).get("supply"))
    cbal = num(rep.get("creatorBalance"))
    return {"risks": risks, "lp_locked_pct": locked,
            "mint_authority": rep.get("mintAuthority"), "freeze_authority": rep.get("freezeAuthority"),
            "rugged": bool(rep.get("rugged")),
            "insiders": sum(1 for h in holders if h.get("insider")),
            "creator_in_top": bool(creator) and any(creator in (h.get("address"), h.get("owner")) for h in holders),
            "creator_rug_flag": any("creator" in n.lower() and ("rug" in n.lower() or "histor" in n.lower())
                                    for n, _ in risks),
            "total_holders": num(rep.get("totalHolders")),
            "creator_pct": 100 * cbal / supply if cbal is not None and supply else None,
            "score": num(rep.get("score_normalised") if rep.get("score_normalised") is not None else rep.get("score"))}


def deep_check(p, checks=None):
    """v1.4.2 safety checks, with one change for early coins: being far below the 48h peak is recorded
       as a fact (a dip can be a good entry), not a reason to reject. Returns a dict."""
    mint, pool = p["baseToken"]["address"], p.get("pairAddress")
    checks = checks or {"rpc": lambda m: legacy.check_rpc(m, pool), "rug": check_rug,
                        "sell": legacy.check_sell, "pool": legacy.check_pool}
    unknown, rpc_d, rug_d, sell_d, pool_d = [], None, None, None, None
    for name in ("rpc", "rug"):
        try:
            if name == "rpc":
                rpc_d = checks["rpc"](mint)
            else:
                rug_d = checks["rug"](mint)
        except Exception as e:
            unknown.append(f"{'on-chain' if name == 'rpc' else 'RugCheck'} check failed ({str(e)[:60]})")
    if rpc_d is not None:
        try:
            sell_d = checks["sell"](mint, rpc_d.get("decimals"), p.get("priceUsd"))
        except Exception as e:
            unknown.append(f"sell quote failed ({str(e)[:60]})")
    else:
        unknown.append("sell quote not tried (no on-chain data)")
    try:
        pool_d = checks["pool"](pool)
    except Exception as e:
        unknown.append(f"pool check failed ({str(e)[:60]})")
    verdict, fails, warns = legacy.judge(rpc_d, rug_d, pool_d, sell_d)
    if verdict == "UNVERIFIED":
        unknown += fails
        fails = []
    moved = [f for f in fails if "below its 48h peak" in f]
    fails = [f for f in fails if f not in moved]
    warns = list(warns) + [m + " (recorded, not a reject on this track)" for m in moved]
    if rug_d is None:
        unknown.append("RugCheck unavailable")
    if rpc_d is not None and not rpc_d.get("holders_read"):
        unknown.append("holder concentration unreadable")
    if sell_d is None:
        unknown.append("no sell quote")
    elif sell_d.get("ok") and (sell_d.get("loss_pct") or 0) > MAX_SELL_LOSS_PCT:
        fails.append(f"selling ${PAPER_SIZE_USD} loses {sell_d['loss_pct']:.0f}%")
    tr = (pool_d or {}).get("trades") or {}
    feat = {
        "mint_revoked": None if rpc_d is None else not rpc_d.get("mint_authority"),
        "freeze_revoked": None if rpc_d is None else not rpc_d.get("freeze_authority"),
        "top10_wallets_pct": (rpc_d or {}).get("top10_wallets_pct"),
        "total_holders": (rug_d or {}).get("total_holders"), "creator_pct": (rug_d or {}).get("creator_pct"),
        "creator_in_top": (rug_d or {}).get("creator_in_top"), "insiders": (rug_d or {}).get("insiders"),
        "rug_score": (rug_d or {}).get("score"),
        "rug_danger_n": None if rug_d is None else sum(1 for _, l in rug_d["risks"] if l in ("danger", "critical")),
        "rug_warn_n": None if rug_d is None else sum(1 for _, l in rug_d["risks"] if l == "warn"),
        "lp_locked_pct": (rug_d or {}).get("lp_locked_pct"),
        "sell_loss_pct": (sell_d or {}).get("loss_pct"), "drawdown_48h_pct": (pool_d or {}).get("drawdown_pct"),
        "trades_n": tr.get("n"), "distinct_ratio": tr.get("distinct_ratio"),
        "top_wallet_share": tr.get("top_wallet_share"), "bot_share": tr.get("bot_share"),
        "uniform_share": tr.get("uniform_share"),
    }
    return {"verdict": verdict, "fails": fails, "unknown": unknown, "warns": warns, "feat": feat}


def decide(cheap, deep):
    """REJECT if anything failed. UNVERIFIED if anything needed is unknown (never a pick).
       NOT_CHECKED when the safety-check budget ran out. PICK only when every check passed."""
    if cheap:
        return "REJECT", cheap
    if deep is None:
        return "NOT_CHECKED", ["safety-check budget used this scan"]
    if deep["fails"]:
        return "REJECT", deep["fails"]
    if deep["unknown"]:
        return "UNVERIFIED", deep["unknown"]
    return "PICK", ["authorities, Token-2022, top wallets, sell test, RugCheck and trade patterns all passed"]


# ---------------------------------------------------------------- discovery
def lookup_pairs(mints, getter=None):
    """Full DEX Screener pair data (5-minute buys/sells/volume) for mints; best-liquidity pair each."""
    getter = getter or legacy.get_json
    best, errors = {}, []
    mints = list(dict.fromkeys(mints))
    for i in range(0, len(mints), 30):
        try:
            data = getter(f"{legacy.DEX}/tokens/v1/solana/{','.join(mints[i:i + 30])}")
            if not isinstance(data, list):
                raise ValueError("pair response is not a list")
        except Exception as e:
            errors.append(f"pair lookup: {str(e)[:80]}")
            continue
        for p in data:
            if p.get("chainId") != "solana":
                continue
            p["_source"] = "dexscreener"
            a = (p.get("baseToken") or {}).get("address")
            if a and (a not in best or (liq_of(p) or 0) > (liq_of(best[a]) or 0)):
                best[a] = p
    return best, errors


def discover(getter=None):
    getter = getter or legacy.get_json
    errors, mints, profiles = [], [], {}
    try:
        for p in getter(f"{legacy.DEX}/token-profiles/latest/v1") or []:
            if p.get("chainId") == "solana" and p.get("tokenAddress"):
                profiles[p["tokenAddress"]] = p
                mints.append(p["tokenAddress"])
    except Exception as e:
        errors.append(f"profiles: {str(e)[:80]}")
    try:
        for p in getter(f"{legacy.DEX}/token-boosts/latest/v1") or []:
            if p.get("chainId") == "solana" and p.get("tokenAddress"):
                mints.append(p["tokenAddress"])
    except Exception as e:
        errors.append(f"boosts: {str(e)[:80]}")
    gecko = {}
    for page in (1, 2, 3):
        try:
            for pool in (getter(f"{legacy.GECKO}/networks/solana/new_pools?page={page}") or {}).get("data") or []:
                pair = legacy.gecko_to_pair(pool)
                if pair:
                    gecko[pair["baseToken"]["address"]] = pair
        except Exception as e:
            errors.append(f"new_pools p{page}: {str(e)[:80]}")
    mints += list(gecko)
    best, errs = lookup_pairs(mints, getter)
    errors += errs
    pairs = [best[m] if m in best else gecko[m] for m in dict.fromkeys(mints) if m in best or m in gecko]
    return pairs, profiles, errors


# ---------------------------------------------------------------- measurement (the fixed paper exit)
def clean_candles(candles):
    out = {}
    for c in candles or []:
        if len(c) < 5:
            continue
        v = [num(x) for x in c[:5]]
        if any(x is None for x in v):
            continue
        out[int(v[0])] = tuple(v)
    return [out[k] for k in sorted(out)]


def bad_prints(cs):
    """Wick far outside the body, or a 10x jump that falls straight back = data glitch."""
    for i, (_, o, h, l, c) in enumerate(cs):
        if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
            return "invalid candle"
        if h > WICK_MAX * max(o, c):
            return "wick high"
        if l * WICK_MAX < min(o, c) and i + 1 < len(cs) and cs[i + 1][4] > min(o, c) / 2:
            return "wick low"
        if i and i + 1 < len(cs):
            prev, nxt = cs[i - 1][4], cs[i + 1][4]
            if (c > JUMP_MAX * prev or c * JUMP_MAX < prev) and prev / 2 <= nxt <= prev * 2:
                return "transient jump"
    return ""


def simulate(candles, signal_ts, horizon_h, cost, final_liq=None, px0=None, mcap0=None):
    """Fixed exit on 5-minute candles. Pessimistic where unsure:
       entry at the HIGH of the candle 2 min after the signal; stop checked BEFORE the target in every
       candle; a gap below the stop exits at the open; a rug candle exits at its low.
       Missing data is UNKNOWN, never a win or a loss."""
    cs = clean_candles(candles)
    step = CANDLE_MIN * 60
    entry_t, end_t = signal_ts + ENTRY_DELAY_MIN * 60, signal_ts + horizon_h * 3600
    out = {"status": "unknown", "detail": "", "n_candles": 0, "entry_px": None, "exit_reason": "",
           "exit_min": None, "gross_pct": None, "net_pct": None, "cost_pct": cost, "peak_x": None,
           "peak_min": None, "window_peak_x": None, "max_mcap_usd": None}
    for m in MILESTONES:
        out[f"hit_{m}x"], out[f"min_to_{m}x"] = None, None
    first = next((i for i, c in enumerate(cs) if c[0] + step > entry_t), None)
    if first is None or cs[first][0] > entry_t + ENTRY_MAX_WAIT_MIN * 60:
        out.update(status="no_entry", detail="no trade within 10 min of the entry time")
        return out
    win = [c for c in cs[first:] if c[0] < end_t]
    out["n_candles"] = len(win)
    bad = bad_prints(cs[max(0, first - 1):first + len(win) + 1])
    if bad:
        out.update(status="unreliable", detail=bad)
        return out
    entry = win[0][2]
    out["entry_px"] = entry
    out["window_peak_x"] = max(c[2] for c in win[1:]) / entry if len(win) > 1 else 1.0   # even after our exit
    stop, peak, peak_t = entry * (1 + STOP_PCT / 100), entry, win[0][0]
    held, banked, scaled, reason, exit_t = 1.0, 0.0, False, "", None
    for t, o, h, l, c in win[1:]:
        if l <= entry * RUG_FLOOR or l <= stop:                     # 1. stop first
            if l <= entry * RUG_FLOOR:
                px, reason = l, "rug"
            elif o < stop:
                px, reason = o, "gap_below_stop"
            else:
                px, reason = stop, ("trail_stop" if scaled else "stop")
            banked += held * 100 * (px / entry - 1)
            held, exit_t = 0.0, t
            break
        if not scaled and h >= entry * SCALE_OUT_X:                 # 2. half out at 2x
            banked += 0.5 * 100 * (SCALE_OUT_X - 1)
            held, scaled = 0.5, True
        if h > peak:                                                # 3. peak and trailing stop for NEXT candle
            peak, peak_t = h, t
        for m in MILESTONES:
            if out[f"min_to_{m}x"] is None and h >= entry * m:
                out[f"min_to_{m}x"] = round((t - signal_ts) / 60, 1)
        if scaled:
            stop = max(stop, entry, peak * (1 - TRAIL_PCT / 100))
    if held > 0:
        last_t, last_c = win[-1][0], win[-1][4]
        if final_liq is not None and final_liq < DEAD_LIQ_USD:
            banked += held * -100.0
            reason = "dead_pool"
        elif final_liq is None and end_t - last_t > STALE_H * 3600:
            out.update(status="unknown", detail=f"no trade in the last {STALE_H}h and pool liquidity unknown")
            return out
        else:
            banked += held * 100 * (last_c / entry - 1)
            reason = "time"
        exit_t = last_t
    gross = max(-100.0, banked)
    for m in MILESTONES:
        out[f"hit_{m}x"] = out[f"min_to_{m}x"] is not None
    out.update(status="labelled", exit_reason=reason, exit_min=round((exit_t - signal_ts) / 60, 1),
               gross_pct=gross, net_pct=max(-100.0, gross - cost), peak_x=peak / entry,
               peak_min=round((peak_t - signal_ts) / 60, 1))
    if mcap0 and px0:
        out["max_mcap_usd"] = mcap0 * peak / px0
    return out


def fetch_candles(pool, start_ts, end_ts, getter=None):
    """5-minute candles for the pool's base token, paged backwards from end_ts (1000 per call)."""
    getter = getter or legacy.get_json
    got, before = {}, int(end_ts) + 60
    for _ in range(4):
        d = getter(f"{legacy.GECKO}/networks/solana/pools/{pool}/ohlcv/minute?aggregate={CANDLE_MIN}"
                   f"&limit=1000&currency=usd&token=base&before_timestamp={before}")
        lst = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        if not lst:
            break
        for c in lst:
            got[int(c[0])] = c
        earliest = min(int(c[0]) for c in lst)
        if earliest <= start_ts - 600 or len(lst) < 1000:
            break
        before = earliest
    return [got[k] for k in sorted(got)]


def pool_liquidity(pool, getter=None):
    d = (getter or legacy.get_json)(f"{legacy.GECKO}/networks/solana/pools/{pool}")
    return num((((d or {}).get("data") or {}).get("attributes") or {}).get("reserve_in_usd"))


def archive_candles(mint, pool, seen_at, candles, now, keep):
    if not keep:
        return ""
    os.makedirs(path("candles"), exist_ok=True)
    name = f"candles/{now.strftime('%Y-%m-%d')}.jsonl.gz"
    with gzip.open(path(name), "at") as fh:   # appended gzip members form one valid file
        fh.write(json.dumps({"mint": mint, "pool": pool, "seen_at": seen_at, "candles": candles}) + "\n")
    return name


def label_due(state, now, getter=None, liq_lookup=None):
    """Writes each 24h / 7-day result once. Budgeted, retried, never invented."""
    getter = getter or legacy.get_json
    liq_lookup = liq_lookup or (lambda pool: pool_liquidity(pool, getter))
    done, attempts = state["done"], state["attempts"]
    todo = []
    for r in load_rows(SIGHTINGS):
        t0 = parse(r["seen_at"]).timestamp()
        for hz in LABEL_HOURS:
            key = f"{r['sighting_id']}|{hz}"
            due = t0 + hz * 3600 + 15 * 60
            if key in done or now.timestamp() < due:
                continue
            a = attempts.get(key, {"n": 0, "last": 0})
            if now.timestamp() - a["last"] < LABEL_RETRY_MIN * 60:
                continue
            todo.append((due, key, hz, r, a))
    todo.sort(key=lambda x: x[0])
    rows, errors = [], []
    for due, key, hz, r, a in todo[:LABEL_BUDGET]:
        a = {"n": a["n"] + 1, "last": now.timestamp()}
        attempts[key] = a
        t0 = parse(r["seen_at"]).timestamp()
        base = {"sighting_id": r["sighting_id"], "mint": r["mint"], "symbol": r["symbol"], "pool": r["pool"],
                "seen_at": r["seen_at"], "decision": r["decision"], "horizon_h": hz, "labelled_at": iso(now),
                "attempts": a["n"], "rules": rules_version()}
        try:
            cs = fetch_candles(r["pool"], t0, t0 + hz * 3600, getter)
            out = simulate(cs, t0, hz, num(r["cost_pct"]) or cost_pct(None), None,
                           num(r["price_usd"]), num(r["mcap_usd"]))
            if out["status"] == "unknown" and "liquidity unknown" in out["detail"]:
                liq = liq_lookup(r["pool"])            # only asked when the chart went quiet
                out = simulate(cs, t0, hz, num(r["cost_pct"]) or cost_pct(None), liq,
                               num(r["price_usd"]), num(r["mcap_usd"]))
        except Exception as e:
            errors.append(f"{r['mint'][:8]} {hz}h: candles failed ({str(e)[:60]})")
            if now.timestamp() - due > LABEL_GIVE_UP_H * 3600:
                rows.append(dict(base, status="unknown", detail="candles unavailable for 72h"))
                done[key] = "unknown"
            continue
        if out["status"] in ("labelled", "unreliable", "no_entry") or now.timestamp() - due > LABEL_GIVE_UP_H * 3600:
            keep = hz == max(LABEL_HOURS) and (r["decision"] == "PICK" or (out.get("peak_x") or 0) >= 2
                                                or int(hashlib.sha256(r["mint"].encode()).hexdigest(), 16)
                                                % ARCHIVE_EVERY == 0)
            out["candle_file"] = archive_candles(r["mint"], r["pool"], r["seen_at"], cs, now, keep)
            rows.append(dict(base, **out))
            done[key] = out["status"]
    append_rows(LABELS, LABEL_COLS, rows)
    return rows, errors


# ---------------------------------------------------------------- Telegram
def send(text, sender=None):
    return (sender or legacy.tg_send)(text)


def alert(kind, mint, symbol, text, now, sender=None):
    ok = send(text, sender)
    append_rows(ALERTS, ALERT_COLS, [{"at": iso(now), "kind": kind, "mint": mint, "symbol": symbol,
                                      "detail": text.splitlines()[0][:120], "sent": bool(ok)}])
    return ok


def usd(x):
    x = num(x)
    return "?" if x is None else (f"${x / 1e6:.2f}M" if x >= 1e6 else f"${x / 1e3:.0f}k" if x >= 1e3 else f"${x:.0f}")


def pct(x, d=0):
    x = num(x)
    return "?" if x is None else f"{x:+.{d}f}%"


def pick_message(r):
    age, speed = num(r.get("age_min")), num(r.get("vol_speed"))
    age_s = "?" if age is None else f"{age:.0f} min"
    speed_s = "?" if speed is None else f"{speed:.1f}x"
    lines = [f"RUNNER PICK (paper, not advice): {r['symbol']}",
             f"mcap {usd(r['mcap_usd'])} | liq {usd(r['liq_usd'])} | age {age_s}",
             f"Entry: {r['entry_type']} (1h {pct(r['pc_h1'])}, 5m {pct(r['pc_m5'])})",
             f"5m flow: {fmt(r['buys_m5']) or '?'} buys / {fmt(r['sells_m5']) or '?'} sells | volume speed {speed_s}",
             f"Holders {fmt(r['total_holders']) or '?'} | top-10 wallets {pct(r['top10_wallets_pct']).lstrip('+')}"
             f" | dev {pct(r['creator_pct'], 1).lstrip('+')}",
             f"Safety passed. Sell test {pct(-(num(r['sell_loss_pct']) or 0), 1)}",
             "Plan: half out at 2x, rest trails 40% below peak, stop -40%, max 7 days",
             f"https://dexscreener.com/solana/{r['pool']}"]
    return "\n".join(lines)


def track_open(state, now, getter=None, sender=None):
    """Live check of open picks: milestones from the signal price and paper stop hits. Approximate:
       the final result always comes from candles, not from these snapshots."""
    opn = state["open"]
    for m in [m for m, o in opn.items() if now.timestamp() - o["t0"] > HOLD_HOURS * 3600]:
        opn.pop(m)
    if not opn:
        return 0, []
    best, errors = lookup_pairs(list(opn), getter)
    sent = 0
    for mint, o in opn.items():
        p = best.get(mint)
        if p is None or p.get("pairAddress") != o["pool"]:
            continue
        px = num(p.get("priceUsd"))
        if not px or o.get("closed"):
            continue
        x = px / o["px0"]
        o["peak_x"] = max(o.get("peak_x", 1.0), x)
        for m in MILESTONES:
            if x >= m and m not in o["alerted"]:
                o["alerted"].append(m)
                alert(f"{m}x", mint, o["symbol"], f"RUNNER {m}x (paper, live price): {o['symbol']} is {x:.1f}x from "
                      f"the pick price, mcap {usd(num(p.get('marketCap')) or num(p.get('fdv')))}\n"
                      f"https://dexscreener.com/solana/{o['pool']}", now, sender)
                sent += 1
        if o["peak_x"] < SCALE_OUT_X and x <= 1 + STOP_PCT / 100:
            o["closed"] = "stop"
            alert("stop", mint, o["symbol"], f"RUNNER stop (paper): {o['symbol']} hit -40% before 2x. "
                  "Position closed on paper.", now, sender)
        elif o["peak_x"] >= SCALE_OUT_X and x <= max(1.0, o["peak_x"] * (1 - TRAIL_PCT / 100)):
            o["closed"] = "trail"
            alert("trail", mint, o["symbol"], f"RUNNER trail stop (paper): {o['symbol']} fell 40% from its "
                  f"{o['peak_x']:.1f}x peak. Rest of the position closed on paper.", now, sender)
    return sent, errors


# ---------------------------------------------------------------- report
def report(now=None):
    """Plain-English results. Exploratory until MIN_RESULT_N finished picks."""
    now = now or datetime.now(timezone.utc)
    labels = [r for r in load_rows(LABELS) if r["horizon_h"] == str(max(LABEL_HOURS))]
    sights = {r["sighting_id"]: r for r in load_rows(SIGHTINGS)}
    fin = [r for r in labels if r["status"] == "labelled"]

    def summ(rows):
        nets = [num(r["net_pct"]) for r in rows if num(r["net_pct"]) is not None]
        if not nets:
            return "none yet"
        n = len(nets)
        hits = {m: sum(1 for r in rows if r.get(f"hit_{m}x") == "1") for m in MILESTONES}
        return (f"{n} | avg {sum(nets) / n:+.1f}% | won {100 * sum(1 for x in nets if x > 0) / n:.0f}% | "
                + " | ".join(f"{m}x {100 * hits[m] / n:.1f}%" for m in MILESTONES))

    picks = [r for r in fin if r["decision"] == "PICK"]
    lines = [f"# Nexus Runner report ({iso(now)})", "", f"Rules: `{rules_version()}`. PAPER ONLY.", "",
             "## 7-day results (after costs)",
             f"- Picks: {summ(picks)}",
             f"- All early coins seen (comparison): {summ(fin)}",
             f"- Rejected by safety: {summ([r for r in fin if r['decision'] == 'REJECT'])}",
             f"- Unfinished or unknown: {sum(1 for r in labels if r['status'] != 'labelled')}", ""]
    verdict = (f"TOO EARLY: {len(picks)} of {MIN_RESULT_N} finished picks needed." if len(picks) < MIN_RESULT_N
               else "ENOUGH DATA to judge. Positive average after costs = candidate edge; check it on later weeks.")
    lines += [f"**Verdict: {verdict}**", "", "## Which entry facts go with winners (all early coins, exploratory)",
              f"Groups under {MIN_BUCKET_N} coins are hidden. A pattern here is a lead, not proof.", ""]
    groups = {
        "entry type": lambda s: s.get("entry_type") or "unknown",
        "5m buy share": lambda s: bucket(num(s.get("buy_ratio_m5")), [0.5, 0.6, 0.7], "{:.0%}"),
        "volume speed": lambda s: bucket(num(s.get("vol_speed")), [1, 2, 4], "{:g}x"),
        "age (min)": lambda s: bucket(num(s.get("age_min")), [15, 60, 360], "{:g}"),
        "market cap": lambda s: bucket(num(s.get("mcap_usd")), [25e3, 50e3], "${:,.0f}"),
        "holders per min": lambda s: bucket(num(s.get("holders_per_min")), [1, 5, 20], "{:g}"),
        "top-10 wallets %": lambda s: bucket(num(s.get("top10_wallets_pct")), [15, 25], "{:g}"),
    }
    for title, fn in groups.items():
        agg = {}
        for r in fin:
            s = sights.get(r["sighting_id"])
            if s is None:
                continue
            agg.setdefault(fn(s), []).append(r)
        shown = [(k, v) for k, v in sorted(agg.items()) if len(v) >= MIN_BUCKET_N]
        if shown:
            lines.append(f"**{title}**")
            lines += [f"- {k}: {summ(v)}" for k, v in shown]
            lines.append("")
    text = "\n".join(lines) + "\n"
    with open(path("report.md"), "w") as fh:
        fh.write(text)
    return text, len(picks), summ(picks)


def bucket(x, edges, f):
    if x is None:
        return "unknown"
    lo = None
    for e in edges:
        if x < e:
            return (f"< {f.format(e)}" if lo is None else f"{f.format(lo)} to {f.format(e)}")
        lo = e
    return f">= {f.format(edges[-1])}"


# ---------------------------------------------------------------- one scan
def run(now=None, deps=None, sender=None):
    deps = deps or {}
    now = now or datetime.now(timezone.utc)
    ensure_files()
    state = load_state()
    scan_id = now.strftime("%Y%m%dT%H%M%S")
    pairs, profiles, errors = deps.get("discover", discover)()
    seen, new = state["seen"], {}
    for p in pairs:
        ok, _ = eligible(p)
        mint = (p.get("baseToken") or {}).get("address")
        if ok and mint not in seen and mint not in new:
            new[mint] = p
    order = sorted(new.values(), key=lambda p: -(num(((p.get("txns") or {}).get("m5") or {}).get("buys")) or 0))
    deep_fn = deps.get("deep", deep_check)
    rows, n_deep = [], 0
    for p in order:
        mint = p["baseToken"]["address"]
        feat = features(p, now, profiles)
        cheap = cheap_fails(p)
        deep = None
        if not cheap and n_deep < DEEP_CHECKS_PER_SCAN:
            n_deep += 1
            try:
                deep = deep_fn(p)
            except Exception as e:
                deep = {"verdict": "UNVERIFIED", "fails": [], "unknown": [f"safety check crashed ({str(e)[:60]})"],
                        "warns": [], "feat": {}}
        decision, reasons = decide(cheap, deep)
        if deep:
            feat.update(deep["feat"])
        th, age = num(feat.get("total_holders")), num(feat.get("age_min"))
        feat["holders_per_min"] = th / max(age, 1.0) if th is not None and age is not None else None
        rows.append(dict(feat, sighting_id=f"{scan_id}:{mint[:12]}", scan_id=scan_id, seen_at=iso(now), mint=mint,
                         symbol=str((p.get("baseToken") or {}).get("symbol") or "?")[:30], pool=p["pairAddress"],
                         decision=decision, reasons="; ".join(reasons), warns="; ".join((deep or {}).get("warns", [])),
                         deep_checked=deep is not None, cost_pct=cost_pct(feat["liq_usd"]), rules=rules_version()))
        seen[mint] = iso(now)
    append_rows(SIGHTINGS, SIGHT_COLS, rows)
    picks = [r for r in rows if r["decision"] == "PICK"]
    for r in picks:
        state["open"][r["mint"]] = {"symbol": r["symbol"], "pool": r["pool"], "t0": now.timestamp(),
                                    "px0": r["price_usd"], "alerted": [], "peak_x": 1.0}
    for r in picks[:MAX_PICK_ALERTS_PER_SCAN]:
        alert("pick", r["mint"], r["symbol"], pick_message(r), now, sender)
    if len(picks) > MAX_PICK_ALERTS_PER_SCAN:
        send(f"RUNNER: {len(picks) - MAX_PICK_ALERTS_PER_SCAN} more paper picks this scan (see sightings.csv).", sender)
    track_fn = deps.get("track", lambda st, t: track_open(st, t, sender=sender))
    _, errs = track_fn(state, now)
    errors += errs
    label_fn = deps.get("label", lambda st, t: label_due(st, t))
    labelled, errs = label_fn(state, now)
    errors += errs
    count = lambda d: sum(1 for r in rows if r["decision"] == d)
    n_open = sum(1 for o in state["open"].values() if not o.get("closed"))
    append_rows(SCANS, SCAN_COLS, [{
        "scan_id": scan_id, "started_at": iso(now), "finished_at": iso(datetime.now(timezone.utc)),
        "version": VERSION, "rules": rules_version(), "n_pairs": len(pairs), "n_new_eligible": len(rows),
        "n_deep": n_deep, "n_not_checked": count("NOT_CHECKED"), "n_pick": len(picks), "n_reject": count("REJECT"),
        "n_unverified": count("UNVERIFIED"), "n_labels": len(labelled), "n_open": n_open,
        "errors": " | ".join(errors)[:900]}])
    if now.hour >= REPORT_HOUR_UTC and state.get("last_report_day") != now.strftime("%Y-%m-%d"):
        text, n, line = report(now)
        state["last_report_day"] = now.strftime("%Y-%m-%d")
        send(f"RUNNER daily report (paper)\n7-day picks: {line}\n"
             f"{'TOO EARLY to judge' if n < MIN_RESULT_N else 'Enough picks to judge: see report.md'}", sender)
    save_state(state)
    print(f"{VERSION} scan {scan_id}: {len(pairs)} pairs, {len(rows)} new early coins, {n_deep} safety-checked, "
          f"{len(picks)} picks, {len(labelled)} results written, {n_open} open, {len(errors)} issues")
    for e in errors[:10]:
        print("  issue:", e)
    return rows, errors


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "--scan"
    if arg == "--telegram-test":
        ok = send("Nexus Runner Track: Telegram test (paper only).")
        print("Telegram test sent." if ok else "Telegram test NOT sent (check secrets).")
    elif arg == "--report":
        ensure_files()
        print(report()[0])
    else:
        run()


if __name__ == "__main__":
    main()
