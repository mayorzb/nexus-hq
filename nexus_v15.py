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
import io
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import concept_scorer_v1_4 as legacy

VERSION = "1.5.3"   # 1.5.3 (6 Nov 2026): fresh paper evaluation eval-2 (traceable outcomes); new version = new test period
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
SETTLE_MIN = 30                 # v1.5.2: a window that ended this long ago, with trades seen AFTER it, and still too
                                # few trades inside it, is FINAL (UNKNOWN now): empty minutes never get candles later
SETTLE_NO_DATA_H = 4            # ...and with no trade at all since the window ended, it is final after this long
DEAD_LIQ_USD = 500
DEAD_CONFIRM_GAP_MIN = 30       # "dead" needs two readings at least this far apart (one blip is not death)
# ---- price-validity rules, FROZEN as "price-1" (6 Nov 2026). Applied by the one labeller to every label, so every
# comparison group (B0, legacy, H1, candidates, random) is treated identically. Changing any value = new version.
PRICE_CHECK_VERSION = "price-1"
PRICE_WICK_MAX = 5.0            # high above 5x the candle's open/close body, or low below 1/5 of it = bad print
PRICE_JUMP_MAX = 10.0           # one-minute close-to-close move above 10x (up) or below 1/10 (down)
PRICE_REVERT = 2.0              # ...that comes back within 2x of the previous close next minute = transient glitch
MEASUREMENT_VERSION = "label-1.5.3+" + PRICE_CHECK_VERSION
# ---- fresh paper evaluation eval-2 (frozen in PROTOCOL_EVAL2.md; its SHA-256 is pinned here and checked by a test)
EVAL_PROTOCOL = "eval-2"
PROTOCOL_FILE = "PROTOCOL_EVAL2.md"
PROTOCOL_SHA256 = "e7ec9869b68e73dbf271726179915f6cf5d9e0ed5a56fd7dd154dbdec0c3b909"
DUE_BUFFER_MIN = 10             # eval-2: a horizon is due ENTRY_DELAY_MIN + horizon + this many minutes after the sighting
ATTEMPTS = "label_attempts.csv" # eval-2: every labelling attempt, successful or not, one row per horizon (append-only)
ATTEMPT_COLS = ["attempted_at", "sighting_id", "mint", "pool", "horizon_min", "due_at", "outcome", "detail",
                "n_candles", "candle_file", "code_version", "measurement_version"]
ALERT_COOLDOWN_H = 24           # the same token is not alerted twice within this
CANARY_CHECKS = 2               # safety-layer self-test: when no coin reached deep checks (e.g. RED market), deep-check
                                # the 2 most liquid coins anyway. Recorded per scan; NEVER changes any decision.
SCAN_GAP_ALERT_MIN = 90         # warn on Telegram if scans stopped for this long
ERROR_ALERT_COOLDOWN_H = 6
REPORT_HOUR_UTC = 8             # daily performance report at the first scan after this hour
MIN_BUCKET_N = 30               # a bucket's history is shown only from this many labels
PROB_VALIDATED = False          # stays False until the CEO signs off a held-out validation

RULE_KEYS = ["MIN_LIQ_USD", "MIN_AGE_H", "MAX_ONE_WAY_IMPACT_PCT", "MAX_SELL_LOSS_PCT", "BLOCKED_REGIMES",
             "DEEP_CHECKS_PER_RUN", "PAPER_SIZE_USD", "COST_BUFFER_PCT", "ENTRY_DELAY_MIN", "RUG_DROP",
             "HORIZONS", "DEAD_LIQ_USD", "DEAD_CONFIRM_GAP_MIN"]


# ---------------------------------------------------------------- secrets hygiene
HELIUS_RPC = "https://mainnet.helius-rpc.com/?api-key="


def fix_rpc_url():
    """If SOLANA_RPC_URL holds a bare API key instead of a URL, build the Helius URL from it.
       (1 Nov: a bare key was saved as the secret; every on-chain check failed and the error text,
       which included part of the key, was written to the public log.)"""
    v = (os.environ.get("SOLANA_RPC_URL") or "").strip()
    if v and "://" not in v:
        legacy.RPC_URL = HELIUS_RPC + v
    return legacy.RPC_URL


def redact(text):
    """Removes every secret value (and anything after api-key=) from text before it is logged or sent."""
    text = str(text)
    for name in ("SOLANA_RPC_URL", "RUGCHECK_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        v = (os.environ.get(name) or "").strip()
        if len(v) >= 6:
            text = text.replace(v, "***")
    if legacy.RPC_URL and "api-key" in legacy.RPC_URL:
        text = text.replace(legacy.RPC_URL, "***")
    import re
    return re.sub(r"(api[-_]?key=)[^&\s'\")]+", r"\1***", text, flags=re.I)


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
             "n_deep", "n_candidates", "n_unverified", "n_rejected", "errors", "gap_min_before",
             "canary_n", "canary_unverified", "canary_onchain_err", "code_commit"]
SIGHT_COLS = ["sighting_id", "scan_id", "seen_at", "mint", "symbol", "pool", "source", "price_usd", "liq_usd",
              "liq_known", "mcap_usd", "age_h", "ch_h1", "weather", "rt_cost_pct", "b0_liquid",
              "legacy_gate", "legacy_score", "legacy_deep", "deep_checked", "decision", "reasons", "h1_mature",
              "bucket", "label_this", "rules", "quote_symbol", "quote_address", "protocol"]
LABEL_COLS = ["sighting_id", "mint", "pool", "t0", "horizon_min", "status", "entry_px", "exit_px",
              "exit_reason", "gross_pct", "net_pct", "cost_pct", "decision", "b0_liquid", "legacy_gate",
              "legacy_deep", "h1_mature", "bucket", "labelled_at", "attempts", "note", "rules",
              "px0", "due_at", "protocol", "candle_file"]


def path(name):
    return os.path.join(DATA_DIR, name)


def ensure_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    for name, cols in ((SCANS, SCAN_COLS), (SIGHTINGS, SIGHT_COLS), (LABELS, LABEL_COLS)):
        if not os.path.exists(path(name)):
            with open(path(name), "w", newline="") as f:
                csv.writer(f).writerow(cols)
    for name, cols in ((SCANS, SCAN_COLS), (SIGHTINGS, SIGHT_COLS), (LABELS, LABEL_COLS)):
        upgrade_header(name, cols)
    for name in (POOLS, STATE_FILE, DEAD_FILE):
        if not os.path.exists(path(name)):
            save_json(name, {})


def upgrade_header(name, cols):
    """Adds new columns to an existing file (old rows keep blank values) so appended rows never misalign."""
    with open(path(name), newline="") as f:
        header = next(csv.reader(f), [])
    if header and header != cols and set(header) <= set(cols):
        write_rows(name, cols, load_rows(name))


TORN_LOG = "torn_rows.log"


def load_rows(name):
    """Short rows (written before a column was added) read as blanks. Rows with EXTRA fields cannot be trusted
       and are skipped (count via load_rows.skipped)."""
    with open(path(name), newline="") as f:
        rows = list(csv.DictReader(f, restval=""))
    good = [r for r in rows if None not in r]
    load_rows.skipped[name] = len(rows) - len(good)
    return good


load_rows.skipped = {}


def append_rows(name, cols, rows):
    """Atomic append: the new file is written beside the old one and swapped in, so an interruption leaves the
       previous file intact. A half line left by an older, non-atomic writer is removed and logged first."""
    p = path(name)
    with open(p, "rb") as f:
        data = f.read()
    if data and not data.endswith(b"\n"):
        cut = data.rfind(b"\n") + 1
        with open(path(TORN_LOG), "ab") as log:
            log.write(f"{iso(datetime.now(timezone.utc))} {name}: removed torn line: ".encode() + data[cut:] + b"\n")
        data = data[:cut]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    for r in rows:
        w.writerow(r)
    with open(p + ".tmp", "wb") as f:
        f.write(data + buf.getvalue().encode())
    os.replace(p + ".tmp", p)


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


def label_from_candles(candles, t0, horizon, tp_pct, stop_pct, cost_pct, checks=(PRICE_WICK_MAX, PRICE_JUMP_MAX)):
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
    if checks is not None:                    # D8: unreliable prices are flagged, never scored (checks=None: raw)
        code, detail = price_problem([c for c in cs if c[0] < end], *checks)
        if code:
            return {"unreliable": code, "detail": detail}
    tp, stop = entry * (1 + tp_pct / 100), entry * (1 + stop_pct / 100)
    exit_px, reason = None, None
    for c in cs[1:]:                          # D4: the entry candle's own low/high may come before the fill
        if c[0] >= end:
            break
        lo, hi = c[3], c[2]
        if lo <= entry * (1 - RUG_DROP):
            return {"entry": entry, "exit": lo, "reason": "rug", "gross": -100.0, "net": -100.0}
        if lo <= stop:
            exit_px, reason = lo, "stop"
            break
        if hi >= tp:
            exit_px, reason = tp, "take_profit"
            break
    if exit_px is None:
        inside = [c for c in cs if c[0] < end]
        last = inside[-1]
        tol = min(15, max(2, horizon // 3))    # D3: every horizon needs trades near its end (5m: 2, 15m: 5 min)
        if len(inside) < 2 or end - last[0] > (tol + 1) * 60:
            return None
        exit_px, reason = last[4], "time"
    gross = 100 * (exit_px - entry) / entry
    return {"entry": entry, "exit": exit_px, "reason": reason, "gross": gross, "net": net_return(gross, cost_pct)}


def price_problem(cs, wick=PRICE_WICK_MAX, jump=PRICE_JUMP_MAX, revert=PRICE_REVERT):
    """Returns (reason_code, detail) for the first implausible print in the window, else ("", "").
       Codes: invalid | wick_high | wick_low | jump_transient (either direction, reverts next minute) | jump_up.
       A persistent one-minute fall of 10x is NOT flagged: that is how a liquidity pull (rug) looks, it is the
       documented failure mode in this market, it is consistent with later candles, and the scanner already
       fills stops at the candle low. Its mirror image, a persistent 10x rise in one minute on a $15k+ pool, has
       no comparable mechanism we can verify, and a gain is capped at the take-profit anyway, so excluding it can
       remove at most one take-profit win per case (measured by --sensitivity)."""
    for i, (ts, o, h, lo, c) in enumerate(cs):
        if min(o, h, lo, c) <= 0 or h < max(o, c) or lo > min(o, c):
            return "invalid", f"invalid candle at {ts}"
        if h > wick * max(o, c):
            return "wick_high", f"high {h / max(o, c):.1f}x the body at {ts}"
        if lo * wick < min(o, c):
            return "wick_low", f"low {min(o, c) / lo:.1f}x below the body at {ts}"
        if i:
            prev = cs[i - 1][4]
            up, down = c > jump * prev, c * jump < prev
            if up or down:
                nxt = cs[i + 1][4] if i + 1 < len(cs) else None
                if nxt is not None and prev / revert <= nxt <= prev * revert:
                    return "jump_transient", f"{c / prev:.3g}x move reverted next minute at {ts}"
                if up:
                    return "jump_up", f"one-minute rise {c / prev:.1f}x at {ts}"
    return "", ""


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


def quote_of(p, pool):
    """(symbol, address) of the quote token of the pool we record. Blank when the feed's pair is not that pool."""
    if not pool or p.get("pairAddress") != pool:
        return "", ""
    q = p.get("quoteToken") or {}
    return (q.get("symbol") or "")[:20], q.get("address") or ""


def due_time(t0, horizon):
    """eval-2: when a horizon's label is due (its window has ended plus a short buffer for late candles)."""
    return t0 + timedelta(minutes=ENTRY_DELAY_MIN + horizon + DUE_BUFFER_MIN)


def entry_check(candles, t0, px0):
    """eval-2: was there a valid paper entry? Returns (code, detail):
       "ok"             - no collapse before the entry fill
       "no_valid_entry" - the price fell RUG_DROP or more below the sighting price (px0) before the entry fill;
                          the outcome is NOT scored and is counted separately
       "ref_mismatch"   - no candle in the 15 minutes before entry trades within 3x of px0, so px0 cannot be
                          compared with this price series (e.g. base/quote reversed); the check is skipped
       "no_px0"         - no sighting price recorded (rows made before eval-2); the check is skipped"""
    if not px0 or px0 <= 0:
        return "no_px0", ""
    start = t0 + ENTRY_DELAY_MIN * 60
    near = sorted((c for c in candles if t0 - 15 * 60 <= c[0] < start + 5 * 60), key=lambda c: c[0])
    entry_c = next((c for c in near if c[0] >= start), None)
    before = [c for c in near if c[0] < (entry_c[0] if entry_c else start + 5 * 60)]
    if not any(px0 / 3 <= c[2] and c[3] <= px0 * 3 for c in before + ([entry_c] if entry_c else [])):
        return "ref_mismatch", f"no candle within 3x of sighting price {px0:.6g} before entry"
    floor = px0 * (1 - RUG_DROP)
    for c in before:
        if c[0] >= t0 - 120 and c[4] <= floor:
            return "no_valid_entry", (f"close {c[4]:.6g} at {iso(datetime.fromtimestamp(c[0], timezone.utc))} is "
                                      f"{100 * c[4] / px0:.1f}% of sighting price {px0:.6g}, before the entry fill")
    if entry_c and entry_c[2] <= floor:
        return "no_valid_entry", f"entry candle high {entry_c[2]:.6g} is {100 * entry_c[2] / px0:.1f}% of sighting price"
    return "ok", ""


def log_attempts(rows):
    """Append-only attempt log (eval-2). Never rewritten, so failed attempts stay visible."""
    if not rows:
        return
    if not os.path.exists(path(ATTEMPTS)):
        with open(path(ATTEMPTS), "w", newline="") as f:
            csv.writer(f).writerow(ATTEMPT_COLS)
    append_rows(ATTEMPTS, ATTEMPT_COLS, [dict(r, code_version=VERSION, measurement_version=MEASUREMENT_VERSION)
                                          for r in rows])


def is_due(r, t0, now):
    """eval-2 rows carry their own due time per horizon; older rows keep the old rule (all horizons after
       LABEL_AFTER_MIN) so earlier measurements are not changed."""
    if r.get("due_at"):
        return now >= parse(r["due_at"])
    return (now - t0).total_seconds() / 60 >= LABEL_AFTER_MIN


def label_pending(now, getter=None, dead_lookup=None):
    """Labels every horizon that is due. Each label is written ONCE (F03).
       Network failure -> stays pending and is retried (F02). No data after LABEL_GIVE_UP_H -> 'unknown'.
       eval-2: every attempt is logged (label_attempts.csv); the candle file behind each attempt is recorded;
       a collapse before a valid entry is 'no_valid_entry' (not scored, counted separately)."""
    rows = load_rows(LABELS)
    dead = load_json(DEAD_FILE)
    done = 0
    archive = []                                 # raw candles behind every label, kept for audit and --sensitivity
    candle_file = os.path.join("candles", f"{now.strftime('%Y%m%dT%H%M%S')}.jsonl.gz")
    attempts = []
    by_sight = {}
    for r in rows:
        if r["status"] == "pending":
            by_sight.setdefault(r["sighting_id"], []).append(r)
    for sid, group in by_sight.items():
        t0 = parse(group[0]["t0"])
        age_min = (now - t0).total_seconds() / 60
        group = [r for r in group if is_due(r, t0, now)]
        if not group:
            continue

        def note(r, outcome, detail="", n=""):
            if r.get("protocol"):
                attempts.append({"attempted_at": iso(now), "sighting_id": sid, "mint": r["mint"], "pool": r["pool"],
                                 "horizon_min": r["horizon_min"], "due_at": r.get("due_at", ""), "outcome": outcome,
                                 "detail": detail[:200], "n_candles": n,
                                 "candle_file": candle_file if n != "" else ""})
        try:
            candles = fetch_candles(group[0]["pool"], t0.timestamp(), getter)
        except Exception as e:
            for r in group:
                r["attempts"] = str(int(r["attempts"] or 0) + 1)
                r["note"] = f"lookup failed, will retry ({str(e)[:60]})"
                note(r, "failed", f"lookup failed: {redact(e)[:150]}")
            continue
        archive.append({"sighting_id": sid, "pool": group[0]["pool"], "t0": group[0]["t0"], "fetched_at": iso(now),
                        "candles": candles})
        ec, edetail = entry_check(candles, t0.timestamp(), f2(group[0].get("px0"))) if group[0].get("protocol") \
            else ("no_px0", "")
        for r in group:
            h = int(r["horizon_min"])
            tp, st = HORIZONS[h]
            r["attempts"] = str(int(r["attempts"] or 0) + 1)
            n = len(candles)
            if r.get("protocol"):
                r["candle_file"] = candle_file
            if ec == "no_valid_entry":
                r.update(status="no_valid_entry", exit_reason="collapse_before_entry", labelled_at=iso(now),
                         note=f"{edetail[:150]}; NOT scored")
                note(r, "no_valid_entry", edetail, n)
                continue
            res = label_from_candles(candles, t0.timestamp(), h, tp, st, f2(r["cost_pct"]) or 0.0)
            if res is not None and "unreliable" in res:
                r.update(status="unreliable", exit_reason="unreliable:" + res["unreliable"], labelled_at=iso(now),
                         note=f"{PRICE_CHECK_VERSION}: {res['detail'][:80]}; NOT counted")
                note(r, "unreliable", res["detail"], n)
                continue
            if res is None:
                confirmed_dead = dead_lookup(r, dead, now) if dead_lookup else False
                window_end = t0 + timedelta(minutes=ENTRY_DELAY_MIN + h)
                first_low = (dead.get(r["pool"]) or {}).get("first_low")
                died_in_window = confirmed_dead and first_low and parse(first_low) <= window_end
                if died_in_window:
                    r.update(status="labelled", exit_reason="rug_confirmed", gross_pct="-100.0",
                             net_pct="-100.0", labelled_at=iso(now), note="pool confirmed dead inside the window")
                    done += 1
                elif confirmed_dead:                   # D5: death seen only after the window: outcome unknowable
                    r.update(status="unknown", labelled_at=iso(now),
                             note=f"pool dead, first seen {first_low} after the window; NOT counted as a loss")
                elif age_min > LABEL_GIVE_UP_H * 60:
                    r.update(status="unknown", labelled_at=iso(now), note="no candle data; NOT counted as a loss")
                elif now > window_end + timedelta(minutes=SETTLE_MIN) and (
                        any(c[0] >= window_end.timestamp() for c in candles)
                        or now > window_end + timedelta(hours=SETTLE_NO_DATA_H)):
                    r.update(status="unknown", labelled_at=iso(now),
                             note="thin trading: too few trades in the finished window; NOT counted as a loss")
                else:
                    r["note"] = "not enough candle data yet"
                note(r, r["status"] if r["status"] != "pending" else "pending", r["note"] +
                     (f"; entry check {ec}: {edetail}" if ec == "ref_mismatch" else ""), n)
                continue
            r.update(status="labelled", entry_px=f"{res['entry']:.12g}", exit_px=f"{res['exit']:.12g}",
                     exit_reason=res["reason"], gross_pct=f"{res['gross']:.2f}", net_pct=f"{res['net']:.2f}",
                     labelled_at=iso(now), note="" if ec != "ref_mismatch" else f"entry check skipped: {edetail}")
            note(r, "labelled", f"{res['reason']} net {res['net']:.2f}%" +
                 (f"; entry check {ec}" if ec == "ref_mismatch" else ""), n)
            done += 1
    archive_candles(archive, now)
    write_rows(LABELS, LABEL_COLS, rows)
    log_attempts(attempts)
    save_json(DEAD_FILE, dead)
    return done


def archive_candles(items, now, prefix=""):
    """Write-once file per labelling run: data_v15/candles/<prefix><UTC time>.jsonl.gz (never rewritten)."""
    if not items:
        return None
    import gzip
    os.makedirs(path("candles"), exist_ok=True)
    name = os.path.join("candles", f"{prefix}{now.strftime('%Y%m%dT%H%M%S')}.jsonl.gz")
    with gzip.open(path(name) + ".tmp", "wt") as f:
        for it in items:
            f.write(json.dumps(it, separators=(",", ":")) + "\n")
    os.replace(path(name) + ".tmp", path(name))
    return name


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
        unknown.append(f"on-chain check failed ({redact(e)[:50]})")
    try:
        rug_d = checks["rug"](mint)
    except Exception as e:
        unknown.append(f"RugCheck failed ({redact(e)[:50]})")
    if rpc_d is not None:
        try:
            sell_d = checks["sell"](mint, rpc_d.get("decimals"), p.get("priceUsd"))
        except Exception as e:
            unknown.append(f"sell quote failed ({redact(e)[:50]})")
    else:
        unknown.append("sell quote not tried (no on-chain data)")
    if p.get("pairAddress"):
        try:
            pool_d = checks["pool"](p["pairAddress"])
        except Exception as e:
            unknown.append(f"pool check failed ({redact(e)[:50]})")
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
    fix_rpc_url()

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
             "quote_symbol": quote_of(p, pool)[0], "quote_address": quote_of(p, pool)[1], "protocol": EVAL_PROTOCOL,
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
            errors.append(f"deep check crashed for {s['symbol']}: {redact(e)}")
    canary = []
    if not deep_results:                                   # safety-layer self-test; decisions untouched
        liquid = sorted((s for s in sightings if s["b0_liquid"] == "1"), key=lambda s: -(f2(s["liq_usd"]) or 0))
        for s in liquid[:CANARY_CHECKS]:
            try:
                canary.append(deep_check(s["_p"], deep_fn(s["_p"]) if deep_fn else None))
            except Exception as e:
                errors.append(f"safety canary crashed for {s['symbol']}: {redact(e)}")
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
                               "bucket": s["bucket"], "attempts": "0", "rules": rules_version(),
                               "px0": s["price_usd"], "due_at": iso(due_time(parse(s["seen_at"]), h)),
                               "protocol": EVAL_PROTOCOL})
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
            "errors": redact(" | ".join(errors))[:500], "gap_min_before": f"{gap:.0f}" if gap is not None else "",
            "canary_n": len(canary), "canary_unverified": sum(1 for c in canary if not c[1] and c[2]),
            "canary_onchain_err": sum(1 for c in canary if any("on-chain check failed" in u for u in c[2])),
            "code_commit": os.environ.get("NEXUS_CODE_COMMIT", "")[:12]}
    append_rows(SCANS, SCAN_COLS, [scan])
    tg(summary_message(scan, [s for s in rejected if s["decision"] != "NOT_CHECKED"]), sender)
    for e in errors:
        error_alert(state, e, now, sender)
    errors = [redact(e) for e in errors]
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


MONEY_FIELDS = ("entry_px", "exit_px", "exit_reason", "gross_pct", "net_pct")
AUDIT_FIELDS = ("status",) + MONEY_FIELDS


def relabel_corrected(now, getter=None):
    """Round 1: re-scores every finished ORIGINAL label with the current labeller. The original labels.csv is
       never touched. Corrected rows go to corrected/labels_v151.csv (with the measurement version); every row
       whose status, prices, exit reason or returns differ gets one audit row holding old AND new values."""
    os.makedirs(path("corrected"), exist_ok=True)
    rows, dead = load_rows(LABELS), load_json(DEAD_FILE)
    out, changes, cache = [], [], {}
    cleared = {k: "" for k in MONEY_FIELDS}
    for r in rows:
        new = dict(r, measurement_version=MEASUREMENT_VERSION)
        if r["status"] in ("labelled", "unknown", "unreliable"):
            t0 = parse(r["t0"])
            key = (r["sighting_id"], r["t0"], r["pool"])
            if key not in cache:
                try:
                    cache[key] = fetch_candles(r["pool"], t0.timestamp(), getter)
                except Exception as e:
                    cache[key] = e
            h = int(r["horizon_min"])
            tp, st = HORIZONS[h]
            if isinstance(cache[key], Exception):
                new.update(cleared, status="unknown", note=f"relabel lookup failed ({str(cache[key])[:50]})")
            else:
                res = label_from_candles(cache[key], t0.timestamp(), h, tp, st, f2(r["cost_pct"]) or 0.0)
                if res is None:
                    fl = (dead.get(r["pool"]) or {}).get("first_low")
                    in_win = r["exit_reason"] == "rug_confirmed" and fl and \
                        parse(fl) <= t0 + timedelta(minutes=ENTRY_DELAY_MIN + h)
                    new.update(cleared)
                    if in_win:
                        new.update(status="labelled", exit_reason="rug_confirmed", gross_pct="-100.0",
                                   net_pct="-100.0", note="relabel: pool dead inside the window")
                    else:
                        new.update(status="unknown", note="relabel: data cannot decide")
                elif "unreliable" in res:
                    new.update(cleared, status="unreliable", exit_reason="unreliable:" + res["unreliable"],
                               note=f"relabel {PRICE_CHECK_VERSION}: {res['detail'][:80]}")
                else:
                    new.update(status="labelled", entry_px=f"{res['entry']:.12g}", exit_px=f"{res['exit']:.12g}",
                               exit_reason=res["reason"], gross_pct=f"{res['gross']:.2f}",
                               net_pct=f"{res['net']:.2f}", note="relabel")
            new["labelled_at"] = iso(now)
            diff = [k for k in AUDIT_FIELDS if (new.get(k) or "") != (r.get(k) or "")]
            if diff:
                ch = {"sighting_id": r["sighting_id"], "horizon_min": r["horizon_min"],
                      "changed_fields": "|".join(diff), "relabelled_at": iso(now),
                      "measurement_version": MEASUREMENT_VERSION, "code_version": VERSION}
                for k in AUDIT_FIELDS:
                    ch["old_" + k], ch["new_" + k] = r.get(k) or "", new.get(k) or ""
                changes.append(ch)
        out.append(new)
    archive_candles([{"sighting_id": k[0], "pool": k[2], "t0": k[1], "fetched_at": iso(now), "candles": v}
                     for k, v in cache.items() if not isinstance(v, Exception)], now, prefix="relabel_")
    write_rows(os.path.join("corrected", "labels_v151.csv"), LABEL_COLS + ["measurement_version"], out)
    ch_cols = ["sighting_id", "horizon_min", "changed_fields"] + \
        [f"{w}_{k}" for k in AUDIT_FIELDS for w in ("old", "new")] + \
        ["relabelled_at", "measurement_version", "code_version"]
    write_rows(os.path.join("corrected", "changes_v151.csv"), ch_cols, changes)
    n = sum(1 for r in rows if r["status"] in ("labelled", "unknown", "unreliable"))
    return f"relabelled {n} labels; {len(changes)} changed; originals untouched ({MEASUREMENT_VERSION})"


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
    if "--relabel" in args:
        print(relabel_corrected(datetime.now(timezone.utc)))
        return
    scan = run()
    print(json.dumps(scan, indent=1))
    if scan.get("errors") or not scan.get("n_tokens"):   # D6: a failed scan must fail the run, not stay green
        sys.exit(1)


if __name__ == "__main__":
    main()
