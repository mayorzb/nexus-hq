"""
Timmy's Concept Scorer - v1.4.2  "NEXUS DEEP SCAN"

v1.4.2 = honest-counting update, built from the 4-agent code review (SCOUT, FILTER, TRACKER, ANALYST).
  THIS RESTARTS THE TEST COUNT. Every shadow row is now stamped with rules_version; --report only counts
  rows from the current version (old rows are kept and shown as a "pilot" line; --report --all shows them).
  Counting fixes
  - WATCH_LOGGED (already on your paper list) now counts as a survivor. UNVERIFIED (checks never ran) gets
    its own group instead of being counted as a survivor.
  - A coin blocked at first sight but WATCHed later is moved out of "blocked" into its own group.
  - DEAD carries forward: dead at 1h/6h stays dead at 24h/72h instead of vanishing as NA.
  - The exit simulation keeps coins whose stop already fired, even if the 24h snapshot was missed.
  - Unknown trading cost now defaults to a 10% penalty (was 2%); the exit side is costed at the thinnest
    liquidity seen, not the entry liquidity.
  - New p72h snapshot (exit plan is still "out by 24h"; 72h shows slow bleeds and late rugs).
  Data fixes
  - Price lookups also match a coin listed as the QUOTE token, and a coin missing from a batch reply is
    looked up on its own before anything is called DEAD.
  - One failed batch no longer stops a fallback liquidity feed; liquidity of $0 counts as known (thin), not blind.
  - scan_health.csv gets one row per run (blind %, rate limits, timeouts) with an ALERT flag.
  Gate fixes (FILTER)
  - Holder concentration = top-10 WALLETS / total supply. Pool vaults, bonding curves, burn addresses and
    program-owned accounts are left out by who owns them. If it can't be read, the coin is UNVERIFIED.
  - Token-2022 traps are instant REJECTs: permanent delegate, transfer hook, non-transferable, frozen by
    default, pausable, transfer fee over 10%.
  - Sell test: a Jupiter quote to sell $50 of the coin for USDC. No route = REJECT; losing over 15% = REJECT.
  Report fixes (ANALYST)
  - A TEST VERDICT block: the three success rules as PASS / LEANING / FAIL / NOT YET, 24h only, needing
    20+ coins in each group, with 95% ranges and the missing-data share per group.
  - A weather split, and the rule-by-rule and score lines are labelled exploratory.

TELEGRAM ALERTS (added to v1.4.2, rules unchanged so the test count is NOT restarted)
  Every NEW paper trade (a WATCH coin) is sent to your Telegram. Set two secrets:
  TELEGRAM_BOT_TOKEN (from @BotFather) and TELEGRAM_CHAT_ID (find it with --telegram-setup).
  --telegram-test sends a test message. If Telegram is down or not set up, the scan carries on as normal.

v1.4.1 = speed + reliability update. Same rules, same thresholds, same files, so a v1.4 test keeps going.
  - Smart per-API rate limiter replaces fixed sleeps (waits only when needed, slows down by itself on a 429,
    honours Retry-After). GeckoTerminal spacing 6.5s -> 2.5s; if you see repeated rate-limit lines,
    set GECKO_INTERVAL back to 6.5.
  - Deep checks run in parallel (4 at a time) instead of one after another.
  - Cheapest checks first: if RPC/RugCheck already reject a coin, the slow chart + trades calls are skipped.
  - RPC + RugCheck results cached for 6h (spot_cache.json), so repeat coins don't burn API calls.
  - A 10-minute time budget: a slow API can no longer hang the run; unfinished coins become UNCHECKED.
  - --recheck skips paper trades already settled (older than 72h with a price), so it gets faster over time.
  - Every run prints its timing, API calls, rate-limit hits and cache hits, so speed is measurable.
  Note: skipping the chart/trades checks on already-rejected coins means fewer extra reasons get logged for
  them. The verdict is unchanged (still REJECT).

v1.3 had a blind gate: in your screenshot 35 of 36 coins died on "liquidity UNKNOWN", including
two with scores of 96 and 82. v1.4 fixes the blindness first, then makes the whole tool MEASURABLE.

What's new vs v1.3
  1. LIQUIDITY RESOLVER  - when the main feed has no liquidity, try Jupiter, then GeckoTerminal's
                           token endpoint, then DEX Screener's token endpoint. If two sources
                           disagree by 3x or more, the LOWER number is used. Anything still
                           unknown is reported as a "blind spot" (a data gap, not a verdict).
  2. MINT-KEYED IDENTITY - everything is keyed on the mint address. Coins sharing a name/symbol
                           are flagged as possible clones; the weaker one is rejected.
  3. SHADOW LOG          - EVERY scanned coin is logged once (shadow_log.csv) with its price, then
                           re-priced at 1h / 6h / 24h. A coin whose pool vanished or whose
                           liquidity was pulled counts as DEAD (-100%).
  4. GATE REPORT         - `--report` compares what the gate blocked with what it let through,
                           rule by rule: did each rule block rugs, or block winners? It also
                           checks whether N/M/C/T/V scores predict anything (Spearman), and
                           only SUGGESTS reweighting - never auto-applies it.
  5. ADVERSARIAL CHECKS  - identical-size trade repetition (bot fingerprint), RugCheck insider
                           flags, "rugged" flag, creator-rug-history flag, creator still among
                           top holders, plus the v1.3 wallet/round-trip checks.
  6. REAL EXIT MODEL     - price impact + swap fee + network fee at your paper size, a
                           "can't exit cleanly" gate, and a snapshot-based simulation of the
                           exit plan (stop -30%, sell half at 2x, out at 24h) net of costs.
  7. NO DOUBLE LOGGING   - a coin already on your paper list (48h) isn't logged again.
                           Price drift since FIRST seen is tracked; chasing a coin that has
                           already run is warned (+50%) or rejected (+150%).
  8. ONE ENGINE          - run_scan() is reusable, so the dashboard and the CLI share the logic.

Run:
    python concept_scorer_v1_4.py                  live scan + spot checks + shadow logging
    python concept_scorer_v1_4.py --recheck        re-price paper trades AND the shadow log
    python concept_scorer_v1_4.py --report         the gate scorecard (needs data to be useful)
    python concept_scorer_v1_4.py --demo           fake data, no internet (writes demo_*.csv)
    python concept_scorer_v1_4.py --demo --weather=RED   (GREEN / NEUTRAL / RED / DEEP_RED)
    python concept_scorer_v1_4.py --selftest       offline logic tests (no internet)

Run --recheck at least every few hours (the GitHub workflow does it hourly). A 1h/6h/24h
snapshot is only recorded if the recheck happens inside that horizon's window; otherwise it is
marked NA rather than faked.

Optional environment variables:  SOLANA_RPC_URL, RUGCHECK_API_KEY

HONEST NOTES
  * Research + paper trading only. WATCH does not mean safe. Not financial advice.
  * The live API field names (Jupiter, RugCheck insider fields, GeckoTerminal) were written from
    their public docs and could not be tested against live servers while this was built.
    Every call is wrapped so a changed field degrades to "unavailable" instead of crashing.
    If a source keeps failing for you, the run output will say so.
  * Shadow-log returns are measured from the FIRST-SEEN price. You could not have bought at that
    exact price, and small pools slip. Treat the report as a direction, not a P&L.
  * A few dozen coins prove nothing. The report says so until you have 100+ with 24h outcomes.
  * v1.4.2's new live calls (getTokenSupply, getMultipleAccounts owner lookup, Token-2022 extensions,
    Jupiter /swap/v1/quote sell test) were written from the public docs and tested offline only. If one
    breaks, the coin becomes UNVERIFIED or gets a "sell test unavailable" warning - never a fake WATCH.
    Holder checks now make 4 RPC calls per deep-checked coin; on the free public RPC, set SOLANA_RPC_URL to a
    free Helius/QuickNode endpoint if you see many "holder read failed" lines.
  * New files: scan_health.csv and spot_cache_v142.json. Add them to your workflow's commit step if it
    lists files by name.
"""
import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as fut_wait
from urllib.parse import urlparse
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone

VERSION = "1.4.2"
DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"
JUP = "https://lite-api.jup.ag"
RUG = "https://api.rugcheck.xyz/v1"
BINANCE = "https://api.binance.com/api/v3/ticker/24hr"
COINGECKO = "https://api.coingecko.com/api/v3/simple/price"
RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
RUG_KEY = os.environ.get("RUGCHECK_API_KEY")
TG_API = "https://api.telegram.org"

LOG_FILE = "concept_log_v1_4.csv"
SHADOW_FILE = "shadow_log.csv"
PAPER_FILE = "paper_trades.csv"        # same file as v1.2/v1.3, old rows are migrated, not lost
STATE = {"demo": False}

# ---- tunable rules (change as YOUR data teaches you) ----
BASE_MIN_LIQUIDITY = 15_000
MIN_LIQ_TO_MCAP = 0.05
MIN_AGE_HOURS = 0.5
VOL_MCAP_WARN, VOL_MCAP_FAIL = 10, 30
COLLAPSE_1H, COLLAPSE_24H = -25, -50
MAX_TOP10_PCT, WARN_TOP10_PCT = 35, 25
DRAWDOWN_FAIL, DRAWDOWN_WARN = 60, 40
TOP_WALLET_FAIL, TOP_WALLET_WARN = 35, 20
BOT_VOLUME_FAIL = 30
DISTINCT_FAIL, DISTINCT_WARN = 0.15, 0.30
UNIFORM_WARN, UNIFORM_FAIL = 0.20, 0.40            # share of trades with the same ~size
INSIDER_WARN, INSIDER_FAIL = 1, 4                  # insider-flagged wallets among top holders
SPOT_CHECK_TOP_N = 5          # unchanged in v1.4.1 so your v1.4 test stays comparable
GECKO_INTERVAL = 2.5          # seconds between GeckoTerminal calls; doubles automatically on a 429
CACHE_TTL_H = 6               # reuse RPC + RugCheck results for a coin for this long
MAX_RUN_SECONDS = 600         # deep checks stop here so a slow API can never hang the workflow
CHECK_WORKERS = 4
CACHE_FILE = "spot_cache_v142.json"   # new name: v1.4.1 cache entries used the old concentration maths
HEALTH_FILE = "scan_health.csv"
WEIGHTS = {"narrative": 1.0, "meme": 1.0, "community": 1.5, "timing": 1.0, "value": 1.0}

LIQ_DISAGREE_X = 3.0           # sources differing by this factor -> warn + use the lower
CLONE_LIQ_RATIO = 2.0          # another same-name token with 2x the liquidity -> reject as clone
CHASE_WARN_PCT, CHASE_FAIL_PCT = 50, 150

PAPER_SIZE_USD = 50            # what a paper trade is sized at, for impact/fee estimates
SWAP_FEE_PCT = 0.5             # per swap, incl. platform/pool fees (assumption - tune it)
NETWORK_FEE_USD = 0.05         # per transaction (assumption)
MAX_IMPACT_PCT = 5.0           # one-way price impact above this = cannot exit cleanly
STOP_PCT, TAKE_X = 30, 2.0     # exit plan: stop -30%, sell half at 2x, out at 24h
DEAD_LIQ_USD = 500             # pool liquidity below this at recheck = effectively rugged
UNKNOWN_COST_PCT = 10.0        # round-trip cost assumed when it could not be estimated (was 2%)
SELL_LOSS_WARN, SELL_LOSS_FAIL = 7.0, 15.0   # % lost selling $PAPER_SIZE_USD for USDC (impact + fees + hidden tax)
TRANSFER_FEE_FAIL_BPS = 1000   # Token-2022 transfer fee above 10% = REJECT
MIN_GROUP = 20                 # coins needed in EACH group before a success rule is judged (50 is better)
HEALTH_BLIND_ALERT = 35        # % blind coins in a run that raises an ALERT in scan_health.csv
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SYSTEM_PROGRAM = "11111111111111111111111111111111"
BURN_OWNERS = {"1nc1nerator11111111111111111111111111111111", SYSTEM_PROGRAM}
KNOWN_POOL_AUTHORITIES = {     # wallets that hold pool tokens for AMMs (add more if you spot them)
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",   # Raydium AMM v4 authority
    "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL",   # Raydium CPMM authority
}
PAPER_COOLDOWN_H = 48

WEATHER_RULES = {
    "GREEN":    {"liq_mult": 1.0,  "min_score": 50, "max_watch": 3},
    "NEUTRAL":  {"liq_mult": 1.0,  "min_score": 55, "max_watch": 2},
    "RED":      {"liq_mult": 1.5,  "min_score": 65, "max_watch": 1},
    "DEEP_RED": {"liq_mult": 2.0,  "min_score": 75, "max_watch": 0},
    "UNKNOWN":  {"liq_mult": 1.25, "min_score": 60, "max_watch": 2},
}

HORIZONS = [("p1h", 1, 2.5), ("p6h", 6, 9.0), ("p24h", 24, 36.0), ("p72h", 72, 96.0)]   # column, hours, latest valid age
LIQ_COL = {"p1h": "l1h", "p6h": "l6h", "p24h": "l24h", "p72h": "l72h"}   # liquidity seen at each snapshot

SHADOW_COLS = ["mint", "symbol", "name", "first_seen", "last_seen", "seen_count", "weather", "source",
               "liq_usd", "liq_src", "mcap", "age_h", "entry_price", "verdict", "categories", "reasons",
               "warnings", "narrative", "meme", "community", "timing", "value", "total", "organic",
               "est_cost_pct", "p1h", "p6h", "p24h", "rules_version", "final_verdict", "final_at",
               "p72h", "l1h", "l6h", "l24h", "l72h"]
PAPER_COLS = ["logged_at", "symbol", "address", "entry_price_usd", "entry_mcap", "checked_at",
              "price_now_usd", "change_pct", "note", "first_seen_price", "drift_pct", "est_cost_pct",
              "liq_usd", "size_usd", "net_change_pct", "status"]


def _rules_fingerprint():
    """Rules version = VERSION + a short hash of every tunable constant. Change any rule -> new version ->
       the report starts a fresh count automatically (old rows are kept, just not mixed in)."""
    import hashlib
    keys = ["BASE_MIN_LIQUIDITY", "MIN_LIQ_TO_MCAP", "MIN_AGE_HOURS", "VOL_MCAP_WARN", "VOL_MCAP_FAIL",
            "COLLAPSE_1H", "COLLAPSE_24H", "MAX_TOP10_PCT", "WARN_TOP10_PCT", "DRAWDOWN_FAIL", "DRAWDOWN_WARN",
            "TOP_WALLET_FAIL", "TOP_WALLET_WARN", "BOT_VOLUME_FAIL", "DISTINCT_FAIL", "DISTINCT_WARN",
            "UNIFORM_WARN", "UNIFORM_FAIL", "INSIDER_WARN", "INSIDER_FAIL", "SPOT_CHECK_TOP_N", "WEIGHTS",
            "LIQ_DISAGREE_X", "CLONE_LIQ_RATIO", "CHASE_WARN_PCT", "CHASE_FAIL_PCT", "PAPER_SIZE_USD",
            "MAX_IMPACT_PCT", "STOP_PCT", "TAKE_X", "DEAD_LIQ_USD", "SELL_LOSS_WARN", "SELL_LOSS_FAIL",
            "TRANSFER_FEE_FAIL_BPS", "WEATHER_RULES"]
    blob = json.dumps({k: globals()[k] for k in keys}, sort_keys=True, default=str)
    return f"{VERSION}-{hashlib.sha1(blob.encode()).hexdigest()[:6]}"


def fp(name):
    return ("demo_" if STATE["demo"] else "") + name


# ======================= helpers =======================
class Limiter:
    """Per-host spacing between calls. Thread-safe. Replaces v1.4's fixed sleeps: it only waits
       when calls would otherwise come too close together, and slows itself down after a 429."""
    def __init__(self, interval, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.next, self.hits = interval, 0.0, 0
        self.lock, self.clock, self.sleep = threading.Lock(), clock, sleep

    def wait(self):
        with self.lock:
            now = self.clock()
            slot = max(now, self.next)
            self.next = slot + self.interval
        if slot > now:
            self.sleep(slot - now)

    def backoff(self):
        with self.lock:
            self.interval = min(self.interval * 2, 15.0)
            self.hits += 1


LIMITS = {"api.geckoterminal.com": Limiter(GECKO_INTERVAL), "api.dexscreener.com": Limiter(1.0),
          "api.rugcheck.xyz": Limiter(1.0), "lite-api.jup.ag": Limiter(0.5)}
STATS = {"calls": 0, "rate_limited": 0}


def get_json(url, headers=None, retry_429=True):
    h = {"User-Agent": "concept-scorer/1.4.2", "Accept": "application/json"}
    if headers:
        h.update(headers)
    lim = LIMITS.get(urlparse(url).netloc)
    if lim:
        lim.wait()
    STATS["calls"] += 1
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 429 and retry_429:
            STATS["rate_limited"] += 1
            if lim:
                lim.backoff()
            wait_s = to_float(e.headers.get("Retry-After") if e.headers else None) or 15
            print(f"  (rate limited by {urlparse(url).netloc} - pausing {min(wait_s, 60):.0f}s, then one retry)")
            time.sleep(min(wait_s, 60))
            return get_json(url, headers, retry_429=False)
        raise


RPC_LIMIT = Limiter(0.25)


def rpc(method, params, retry_429=True):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC_URL, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "concept-scorer/1.4.2"})
    RPC_LIMIT.wait()
    STATS["calls"] += 1
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 429 and retry_429:
            STATS["rate_limited"] += 1
            RPC_LIMIT.backoff()
            time.sleep(5)
            return rpc(method, params, retry_429=False)
        raise
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def to_float(x):
    try:
        return float(x) if x is not None and x != "" else None
    except (TypeError, ValueError):
        return None


def clamp(x, lo=0, hi=5):
    return max(lo, min(hi, x))


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="minutes")


def fmt_usd(x):
    if x is None:
        return "?"
    return f"${x / 1000:.0f}k" if x >= 10_000 else f"${x:,.0f}"


def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def save_csv(path, cols, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)


def ensure_files():
    """Migrate an older paper_trades.csv (v1.2/v1.3 columns) to the v1.4 columns, keeping every row."""
    path = fp(PAPER_FILE)
    if os.path.exists(path):
        with open(path, newline="") as f:
            header = next(csv.reader(f), [])
        if header != PAPER_COLS:
            save_csv(path, PAPER_COLS, load_csv(path))


# ======================= market weather =======================
def regime_from(avg):
    if avg is None:
        return "UNKNOWN"
    if avg <= -5:
        return "DEEP_RED"
    if avg <= -2:
        return "RED"
    if avg >= 2:
        return "GREEN"
    return "NEUTRAL"


def market_weather(demo=False, demo_regime="NEUTRAL"):
    changes = {}
    if demo:
        v = {"GREEN": 3.0, "NEUTRAL": 0.2, "RED": -3.5, "DEEP_RED": -6.0}.get(demo_regime, 0.2)
        changes = {"BTC": v + 0.4, "ETH": v - 0.3, "SOL": v - 0.1}
    else:
        for name, sym in {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}.items():
            try:
                changes[name] = to_float(get_json(f"{BINANCE}?symbol={sym}").get("priceChangePercent"))
            except Exception:
                pass
        if len([c for c in changes.values() if c is not None]) < 3:
            try:
                d = get_json(f"{COINGECKO}?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true")
                for n, cid in {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}.items():
                    if changes.get(n) is None:
                        changes[n] = to_float((d.get(cid) or {}).get("usd_24h_change"))
            except Exception:
                pass
    vals = [c for c in changes.values() if c is not None]
    avg = sum(vals) / len(vals) if vals else None
    return {"regime": regime_from(avg), "avg": avg, "changes": changes}


# ======================= data collection =======================
def gecko_to_pair(pool):
    a = pool.get("attributes") or {}
    rel = ((pool.get("relationships") or {}).get("base_token") or {}).get("data") or {}
    token_id = rel.get("id", "")
    if "_" not in token_id:
        return None
    addr = token_id.split("_", 1)[1]
    name = (a.get("name") or "").split(" / ")[0] or "?"
    created_ms = None
    if a.get("pool_created_at"):
        dt = datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00"))
        created_ms = dt.timestamp() * 1000
    reserve = to_float(a.get("reserve_in_usd"))
    tx = (a.get("transactions") or {}).get("h1") or {}
    pc = a.get("price_change_percentage") or {}
    vol = a.get("volume_usd") or {}
    return {
        "chainId": "solana", "_source": "gecko", "pairAddress": a.get("address"),
        "baseToken": {"address": addr, "name": name, "symbol": name},
        "liquidity": {"usd": reserve} if reserve is not None else {},
        "marketCap": to_float(a.get("market_cap_usd")) or to_float(a.get("fdv_usd")),
        "priceUsd": a.get("base_token_price_usd"),
        "txns": {"h1": {"buys": tx.get("buys", 0), "sells": tx.get("sells", 0)}},
        "priceChange": {"h1": to_float(pc.get("h1")) or 0, "h24": to_float(pc.get("h24"))},
        "volume": {"h24": to_float(vol.get("h24"))},
        "pairCreatedAt": created_ms, "info": {},
    }


def fetch_live(limit=30):
    profiles, gecko_pairs = {}, {}
    try:
        for p in get_json(f"{DEX}/token-profiles/latest/v1"):
            if p.get("chainId") == "solana":
                profiles[p["tokenAddress"]] = p
    except Exception as e:
        print("DEX Screener profiles feed failed:", e)
    try:
        for pool in get_json(f"{GECKO}/networks/solana/new_pools").get("data", []):
            pair = gecko_to_pair(pool)
            if pair:
                gecko_pairs[pair["baseToken"]["address"]] = pair
    except Exception as e:
        print("GeckoTerminal feed failed:", e)

    addrs = list(dict.fromkeys(list(profiles)[:limit] + list(gecko_pairs)[:limit]))
    best = {}
    for batch in chunks(addrs, 30):
        try:
            data = get_json(f"{DEX}/latest/dex/tokens/{','.join(batch)}")
        except Exception as e:
            print("DEX Screener token lookup failed:", e)
            continue
        for p in data.get("pairs") or []:
            if p.get("chainId") != "solana":
                continue
            a = p["baseToken"]["address"]
            liq = (p.get("liquidity") or {}).get("usd") or 0
            p["_source"] = "dexscreener"
            if a not in best or liq > best[a][0]:
                best[a] = (liq, p)
    pairs = [best[a][1] if a in best else gecko_pairs[a] for a in addrs if a in best or a in gecko_pairs]
    return pairs, profiles


def _best_pairs(pairs, wanted):
    """For each wanted mint, the deepest pool it trades in - as the BASE or the QUOTE token.
       Returns {mint: {"price", "liq"}}. (v1.4.1 only matched the base token, so a coin listed as the
       quote side looked like it had no pool and was logged DEAD.)"""
    best = {}
    for p in pairs or []:
        liq = to_float((p.get("liquidity") or {}).get("usd")) or 0
        base = (p.get("baseToken") or {}).get("address")
        quote = (p.get("quoteToken") or {}).get("address")
        if base in wanted:
            price = to_float(p.get("priceUsd"))
            if base not in best or liq > best[base][0]:
                best[base] = (liq, price, p)
        if quote in wanted:
            pu, pn = to_float(p.get("priceUsd")), to_float(p.get("priceNative"))
            price = pu / pn if pu and pn else None          # quote's USD price = base USD / base-in-quote
            if quote not in best or liq > best[quote][0]:
                best[quote] = (liq, price, p)
    return {a: {"price": v[1], "liq": to_float((v[2].get("liquidity") or {}).get("usd"))} for a, v in best.items()}


def fetch_prices(addresses, single=None):
    """Returns {address: {"price": float|None, "liq": float|None} | None}.
       None  = the lookup worked AND the coin's own lookup confirmed no pool exists (dead).
       Missing key = a lookup FAILED (unknown - retry later, do not call it dead).
       A coin missing from a 30-coin batch reply is looked up on its own first, because batch replies
       can leave pairs out."""
    single = single or (lambda a: get_json(f"{DEX}/tokens/v1/solana/{a}"))
    out = {}
    for batch in chunks(dict.fromkeys(addresses), 30):
        try:
            data = get_json(f"{DEX}/latest/dex/tokens/{','.join(batch)}")
        except Exception as e:
            print(f"  (price lookup failed for a batch of {len(batch)}: {e})")
            continue
        found = _best_pairs(data.get("pairs") or [], set(batch))
        for a in batch:
            if a in found:
                out[a] = found[a]
                continue
            try:
                one = single(a)
            except Exception as e:
                print(f"  (single price lookup failed for {a[:6]}...: {e} - will retry)")
                continue
            got = _best_pairs(one if isinstance(one, list) else (one or {}).get("pairs") or [], {a})
            out[a] = got.get(a)          # still nothing after its own lookup -> None = dead
    return out


def exit_price(info):
    """The price you could actually have exited at. Dead pool or pulled liquidity -> 0.0."""
    if info is None:
        return 0.0
    liq = info.get("liq")
    if liq is not None and liq < DEAD_LIQ_USD:
        return 0.0
    return info.get("price")


# ======================= 1. liquidity resolver (tiers 2-4) =======================
def liquidity_of(p):
    liq = (p.get("liquidity") or {}).get("usd")
    return None if liq is None else float(liq)


def fetch_jupiter(mints):
    """Third feed. Best-effort enrichment: liquidity cross-check + organic score."""
    out = {}
    for batch in chunks(mints, 50):
        try:
            data = get_json(f"{JUP}/tokens/v2/search?query={','.join(batch)}")
        except Exception as e:
            print(f"  (Jupiter feed unavailable for a batch of {len(batch)}: {e})")
            continue
        for t in data if isinstance(data, list) else []:
            if isinstance(t, dict) and t.get("id"):
                out[t["id"]] = {"liquidity": to_float(t.get("liquidity")),
                                "mcap": to_float(t.get("mcap")) or to_float(t.get("fdv")),
                                "organic": to_float(t.get("organicScore")),
                                "price": to_float(t.get("usdPrice"))}
    return out


def fetch_gecko_tokens(mints):
    out = {}
    for batch in chunks(mints, 30):
        try:
            data = get_json(f"{GECKO}/networks/solana/tokens/multi/{','.join(batch)}")
        except Exception as e:
            print(f"  (GeckoTerminal token lookup unavailable for a batch of {len(batch)}: {e})")
            continue
        for item in data.get("data") or []:
            a = (item or {}).get("attributes") or {}
            if a.get("address"):
                out[a["address"]] = {"liquidity": to_float(a.get("total_reserve_in_usd")),
                                     "mcap": to_float(a.get("market_cap_usd")) or to_float(a.get("fdv_usd")),
                                     "price": to_float(a.get("price_usd"))}
    return out


def fetch_dex_tokens(mints):
    out = {}
    for batch in chunks(mints, 30):
        try:
            data = get_json(f"{DEX}/tokens/v1/solana/{','.join(batch)}")
        except Exception as e:
            print(f"  (DEX Screener v1 token lookup unavailable for a batch of {len(batch)}: {e})")
            continue
        for p in data if isinstance(data, list) else []:
            a = (p.get("baseToken") or {}).get("address")
            liq = to_float((p.get("liquidity") or {}).get("usd"))
            if a and liq is not None and liq >= (out.get(a, {}).get("liquidity") or 0):
                out[a] = {"liquidity": liq, "mcap": to_float(p.get("marketCap")) or to_float(p.get("fdv")),
                          "price": to_float(p.get("priceUsd"))}
    return out


def _apply(p, d, src):
    p["liquidity"] = {"usd": d["liquidity"]}
    p["_liq_src"] = src
    if not p.get("marketCap") and d.get("mcap"):
        p["marketCap"] = d["mcap"]
    if not p.get("priceUsd") and d.get("price"):
        p["priceUsd"] = str(d["price"])
    if src != "feed":
        p["_liq_note"] = f"liquidity came from {src} (may be total across pools, not this pool alone)"


def fetch_enrichment(pairs, demo=False):
    mints = [p["baseToken"]["address"] for p in pairs]
    return demo_jupiter(mints) if demo else fetch_jupiter(mints)


def resolve_liquidity(pairs, jup, fetchers=None):
    """Tier 1 = the feed itself. Then Jupiter -> GeckoTerminal token endpoint -> DEX Screener tokens.
       Mutates the pairs. Returns stats so the run can say how blind it still is."""
    if fetchers is None:
        fetchers = {"gecko_token": fetch_gecko_tokens, "dexscreener_v1": fetch_dex_tokens}
    for p in pairs:
        if liquidity_of(p) is not None:
            p["_liq_src"] = p.get("_source") or "feed"
    unknown = [p for p in pairs if liquidity_of(p) is None]
    stats = {"total": len(pairs), "unknown_before": len(unknown), "unknown_after": None,
             "resolved_by": Counter(), "disagreements": 0}

    for p in list(unknown):
        j = jup.get(p["baseToken"]["address"])
        if j and j.get("liquidity") is not None:
            _apply(p, j, "jupiter")
            stats["resolved_by"]["jupiter"] += 1
    for name, fn in fetchers.items():
        unknown = [p for p in pairs if liquidity_of(p) is None]
        if not unknown:
            break
        got = fn([p["baseToken"]["address"] for p in unknown])
        for p in unknown:
            d = got.get(p["baseToken"]["address"])
            if d and d.get("liquidity") is not None:
                _apply(p, d, name)
                stats["resolved_by"][name] += 1

    # cross-check: two sources disagreeing by 3x+ means one of them is wrong -> trust the LOWER
    for p in pairs:
        j = jup.get(p["baseToken"]["address"]) or {}
        a, b = liquidity_of(p), j.get("liquidity")
        if p.get("_liq_src") not in ("jupiter",) and a and b:
            hi, lo = max(a, b), min(a, b)
            if lo > 0 and hi / lo >= LIQ_DISAGREE_X:
                stats["disagreements"] += 1
                p["_liq_note"] = (f"sources disagree on liquidity ({fmt_usd(a)} vs Jupiter {fmt_usd(b)}); "
                                  f"using the lower")
                if b < a:
                    p["liquidity"] = {"usd": b}
                    p["_liq_src"] = "jupiter(lower)"
    stats["unknown_after"] = sum(1 for p in pairs if liquidity_of(p) is None)
    return stats


# ======================= 2. identity: mint-keyed clone detection =======================
def norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def duplicate_groups(pairs):
    """Map normalised name/symbol -> {mint: liquidity}. Only entries with 2+ distinct mints matter."""
    groups = {}
    for p in pairs:
        b = p["baseToken"]
        for key in {norm(b.get("symbol")), norm(b.get("name"))}:
            if len(key) >= 2:
                groups.setdefault(key, {})[b["address"]] = liquidity_of(p) or 0
    return {k: v for k, v in groups.items() if len(v) > 1}


def clone_peers(p, groups):
    """Other mints (in this scan) that share this coin's name or symbol -> list of (mint, liq)."""
    b, mint = p["baseToken"], p["baseToken"]["address"]
    peers = {}
    for key in {norm(b.get("symbol")), norm(b.get("name"))}:
        for m, liq in (groups.get(key) or {}).items():
            if m != mint:
                peers[m] = liq
    return list(peers.items())


# ======================= 6. exit model =======================
def est_costs(liq, size=PAPER_SIZE_USD):
    """Constant-product approximation: each side of the pool holds about half the liquidity.
       A rough estimate, not a quote. Real pools (concentrated liquidity, bonding curves) differ."""
    if not liq or liq <= 0:
        return None
    half = liq / 2.0
    impact = 100 * size / (half + size)
    impact10 = 100 * size * 10 / (half + size * 10)
    rt = 2 * impact + 2 * SWAP_FEE_PCT + 100 * 2 * NETWORK_FEE_USD / size
    return {"impact_pct": impact, "impact_10x_pct": impact10, "round_trip_pct": rt}


def simulate_exit(entry, snaps, cost_pct):
    r = simulate_exit_full(entry, snaps, cost_pct)
    return None if r is None else r[0]


def simulate_exit_full(entry, snaps, cost_pct):
    """snaps = [(hours, exit_price_or_None)] in time order; price 0.0 means dead/pulled.
       Plan: stop at -STOP_PCT, sell half at TAKE_X, close the rest at the last snapshot (24h).
       Snapshot-based, so gaps matter: a stop is filled at the next snapshot price, not the stop line.
       Returns (net % on the original position, closed_by_stop) or None if there is no usable data."""
    if not entry:
        return None
    pos, realised, sold_half, used, last = 1.0, 0.0, False, False, 1.0
    for _, pr in snaps:
        if pr is None:
            continue
        used = True
        ratio = pr / entry
        if ratio <= 1 - STOP_PCT / 100:
            realised += pos * (ratio - 1) * 100
            pos = 0.0
            break
        if not sold_half and ratio >= TAKE_X:
            realised += 0.5 * (ratio - 1) * 100
            pos -= 0.5
            sold_half = True
        last = ratio
    if not used:
        return None
    if pos > 0:
        realised += pos * (last - 1) * 100
    return realised - cost_pct * (1.5 if sold_half else 1.0), pos == 0.0


# ======================= gate + scoring =======================
def age_hours(p):
    created = p.get("pairCreatedAt")
    return (time.time() * 1000 - created) / 3.6e6 if created else None


def safety_gate(p, liq_floor=BASE_MIN_LIQUIDITY, ctx=None):
    """Returns (passed, hard_fail_reasons, warnings). ctx = {"peers": [(mint, liq)], "first_price": float}"""
    ctx = ctx or {}
    fails, warns = [], []
    liq = liquidity_of(p)
    mcap = p.get("marketCap") or p.get("fdv") or 0
    h1 = (p.get("txns") or {}).get("h1") or {}
    buys, sells = h1.get("buys", 0), h1.get("sells", 0)
    age = age_hours(p)
    pc = p.get("priceChange") or {}
    ch1, ch24 = to_float(pc.get("h1")), to_float(pc.get("h24"))
    vol24 = to_float((p.get("volume") or {}).get("h24"))

    if liq is None:
        fails.append("liquidity UNKNOWN (no data from any source)")
    elif liq < liq_floor:
        fails.append(f"liquidity ${liq:,.0f} below today's ${liq_floor:,.0f} floor")
    if liq is not None and mcap and liq / mcap < MIN_LIQ_TO_MCAP:
        fails.append("liquidity under 5% of market cap")
    if p.get("_liq_note"):
        warns.append(p["_liq_note"])
    c = est_costs(liq)
    if c and c["impact_pct"] > MAX_IMPACT_PCT:
        fails.append(f"a ${PAPER_SIZE_USD} trade would move the price ~{c['impact_pct']:.1f}% (cannot exit cleanly)")
    if buys > 20 and sells == 0:
        fails.append("many buys but zero sells (possible honeypot)")
    if age is not None and age < MIN_AGE_HOURS:
        fails.append("too new (under 30 min)")
    if ch1 is not None and ch1 <= COLLAPSE_1H:
        fails.append(f"price collapsing: {ch1:.0f}% in 1h")
    if ch24 is not None and ch24 <= COLLAPSE_24H:
        fails.append(f"price collapsed: {ch24:.0f}% in 24h")
    if vol24 and mcap:
        ratio = vol24 / mcap
        if ratio > VOL_MCAP_FAIL:
            fails.append(f"volume is {ratio:.0f}x market cap (churn / wash-trading hint)")
        elif ratio > VOL_MCAP_WARN:
            warns.append(f"volume is {ratio:.0f}x market cap (unusually high churn)")

    peers = ctx.get("peers") or []
    if peers:
        best_peer = max(l for _, l in peers)
        name = p["baseToken"].get("symbol") or p["baseToken"].get("name")
        if best_peer > (liq or 0) * CLONE_LIQ_RATIO:
            fails.append(f"possible clone: {len(peers)} other token(s) named '{name}', one with more liquidity")
        else:
            warns.append(f"{len(peers)} other token(s) share the name '{name}' - verify the mint on the official page")
    fp_ = to_float(ctx.get("first_price"))
    now_p = to_float(p.get("priceUsd"))
    if fp_ and now_p:
        drift = 100 * (now_p - fp_) / fp_
        p["_drift"] = drift
        if drift >= CHASE_FAIL_PCT:
            fails.append(f"already up {drift:.0f}% since first seen (you'd be chasing)")
        elif drift >= CHASE_WARN_PCT:
            warns.append(f"up {drift:.0f}% since first seen")
    return (len(fails) == 0), fails, warns


def score_concept(p, profile):
    """Crude rule-based proxies. The shadow log + --report tell you which of these earn their weight."""
    base = p.get("baseToken") or {}
    info = p.get("info") or {}
    socials = info.get("socials") or []
    has_site = bool(info.get("websites"))
    has_image = bool(info.get("imageUrl"))
    desc = ((profile or {}).get("description") or "").strip()
    h1 = (p.get("txns") or {}).get("h1") or {}
    buys, sells = h1.get("buys", 0), h1.get("sells", 0)
    change_h1 = to_float((p.get("priceChange") or {}).get("h1")) or 0
    age = age_hours(p)
    age = 9999 if age is None else age

    narrative = (0 if not desc else (2 if len(desc) > 160 else 4)) + (1 if has_site else 0)
    meme = (2 if len(base.get("name", "")) <= 14 else 0) + (1 if len(base.get("symbol", "")) <= 6 else 0)
    meme += 2 if has_image else 0
    community = min(len(socials), 2)
    community += 1 if buys + sells >= 100 else 0
    community += 1 if (buys + sells) and buys / (buys + sells) >= 0.5 else 0
    community += 1 if len(socials) >= 2 else 0
    timing = (3 if 1 <= age <= 48 else (2 if age <= 336 else 0)) + (2 if 0 <= change_h1 <= 100 else 0)
    value = (3 if has_site else 0) + (2 if len(socials) >= 2 else 0)

    scores = {k: clamp(v) for k, v in {"narrative": narrative, "meme": meme, "community": community,
                                        "timing": timing, "value": value}.items()}
    total = sum(scores[k] * WEIGHTS[k] for k in scores)
    return scores, round(100 * total / (5 * sum(WEIGHTS.values())))


# ======================= deep spot checks =======================
def concentration(holdings, supply):
    """holdings = [(amount, is_wallet)], supply = total supply (ui units).
       Returns (top-10 of everything / supply, top-10 WALLETS / supply). v1.4.1 divided by the top-20
       total instead of the supply, which made spread-out coins look concentrated."""
    if not supply or supply <= 0:
        return None, None
    alls = sorted((a for a, _ in holdings), reverse=True)
    wallets = sorted((a for a, w in holdings if w), reverse=True)
    return 100 * sum(alls[:10]) / supply, 100 * sum(wallets[:10]) / supply


def token2022_flags(ext_list):
    """Reads the Token-2022 extensions from a jsonParsed mint. Returns {name: detail} for each trap found."""
    out = {}
    for e in ext_list or []:
        if not isinstance(e, dict):
            continue
        name, st = e.get("extension"), e.get("state") or {}
        if name == "permanentDelegate" and st.get("delegate"):
            out["permanent_delegate"] = "a permanent delegate can move or burn tokens out of ANY wallet"
        elif name == "transferHook" and st.get("programId"):
            out["transfer_hook"] = "a transfer hook program runs on every transfer (can block sells)"
        elif name == "nonTransferable":
            out["non_transferable"] = "token is non-transferable (cannot be sold)"
        elif name == "defaultAccountState" and str(st.get("accountState", "")).lower() == "frozen":
            out["default_frozen"] = "new holder accounts start frozen"
        elif name == "pausableConfig" and st.get("authority"):
            out["pausable"] = "an authority can pause all transfers"
        elif name == "transferFeeConfig":
            bps = max(to_float(((st.get(k) or {}).get("transferFeeBasisPoints"))) or 0
                      for k in ("newerTransferFee", "olderTransferFee"))
            out["transfer_fee_bps"] = bps
            if st.get("transferFeeConfigAuthority"):
                out["fee_changeable"] = "the transfer fee can be raised later"
    return out


def check_rpc(mint, pool=None):
    info = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    val = (info or {}).get("value") or {}
    pinfo = (((val.get("data") or {}) if isinstance(val.get("data"), dict) else {}).get("parsed") or {}).get("info") or {}
    if not pinfo:
        raise RuntimeError("not a readable token mint")
    out = {"mint_authority": pinfo.get("mintAuthority"), "freeze_authority": pinfo.get("freezeAuthority"),
           "decimals": pinfo.get("decimals"), "token_program": val.get("owner"),
           "t22": token2022_flags(pinfo.get("extensions")),
           "top10_pct": None, "top10_wallets_pct": None, "holders_read": False}
    try:
        supply = to_float(((rpc("getTokenSupply", [mint]) or {}).get("value") or {}).get("uiAmountString"))
        accts = rpc("getTokenLargestAccounts", [mint]).get("value") or []
        addrs = [a["address"] for a in accts if a.get("address")]
        parsed = (rpc("getMultipleAccounts", [addrs, {"encoding": "jsonParsed"}]) or {}).get("value") or []
        owners = [((((x or {}).get("data") or {}).get("parsed") or {}).get("info") or {}).get("owner") for x in parsed]
        uniq = [o for o in dict.fromkeys(owners) if o]
        progs = (rpc("getMultipleAccounts", [uniq, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])
                 or {}).get("value") or []
        owner_prog = {o: (x or {}).get("owner") for o, x in zip(uniq, progs)}
        holdings = []
        for a, o in zip(accts, owners):
            is_wallet = bool(o) and o not in BURN_OWNERS and o not in KNOWN_POOL_AUTHORITIES and o != pool \
                and owner_prog.get(o) == SYSTEM_PROGRAM      # program-owned / PDA / missing = pool, curve, vault
            holdings.append((to_float(a.get("uiAmountString")) or 0, is_wallet))
        out["top10_pct"], out["top10_wallets_pct"] = concentration(holdings, supply)
        out["holders_read"] = out["top10_wallets_pct"] is not None
    except Exception as e:
        print(f"  (holder read failed for {mint[:6]}...: {e})")
    return out


def check_sell(mint, decimals, price_usd, size=PAPER_SIZE_USD):
    """Asks Jupiter for a quote to sell $size of the coin for USDC. Catches no-route honeypots and hidden
       taxes that a price chart can't show. Returns {"ok": bool, "loss_pct": float|None, "detail": str}.
       Raises on network trouble (so the caller can tell 'API down' from 'cannot sell')."""
    price = to_float(price_usd)
    if not price or decimals is None:
        raise RuntimeError("no price or decimals to size the sell test")
    raw = int(size / price * (10 ** int(decimals)))
    url = f"{JUP}/swap/v1/quote?inputMint={mint}&outputMint={USDC}&amount={raw}&slippageBps=1000"
    try:
        q = get_json(url)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404, 422):
            try:
                body = json.loads(e.read().decode() or "{}")
            except Exception:
                body = {}
            code = body.get("errorCode") or body.get("error") or f"HTTP {e.code}"
            return {"ok": False, "loss_pct": None, "detail": f"no sell route ({code})"}
        raise
    out_usd = (to_float(q.get("outAmount")) or 0) / 1e6
    loss = 100 * (1 - out_usd / size)
    return {"ok": True, "loss_pct": loss, "detail": f"selling ${size} returns ${out_usd:.2f}"}


def check_rugcheck(mint):
    headers = {"X-API-KEY": RUG_KEY} if RUG_KEY else None
    rep = get_json(f"{RUG}/tokens/{mint}/report", headers)
    risks = [((r or {}).get("name", "?"), (r or {}).get("level", "?")) for r in rep.get("risks") or []]
    locked = None
    for m in rep.get("markets") or []:
        v = to_float((((m or {}).get("lp")) or {}).get("lpLockedPct"))
        if v is not None:
            locked = v if locked is None else max(locked, v)
    holders = [h for h in (rep.get("topHolders") or []) if isinstance(h, dict)]
    creator = rep.get("creator")
    creator_in_top = bool(creator) and any(creator in (h.get("address"), h.get("owner")) for h in holders)
    creator_rug_flag = any("creator" in n.lower() and ("rug" in n.lower() or "histor" in n.lower())
                           for n, _ in risks)
    return {"risks": risks, "lp_locked_pct": locked,
            "mint_authority": rep.get("mintAuthority"), "freeze_authority": rep.get("freezeAuthority"),
            "rugged": bool(rep.get("rugged")),
            "insiders": sum(1 for h in holders if h.get("insider")),
            "creator_in_top": creator_in_top, "creator_rug_flag": creator_rug_flag}


def analyse_trades(rows):
    """rows = [(wallet, 'buy'/'sell', usd)]. Few wallets driving everything, round-trip bots,
       and the same trade size repeated again and again (a bot fingerprint)."""
    if not rows:
        return {"n": 0}
    by, total = {}, 0.0
    for wallet, kind, usd in rows:
        d = by.setdefault(wallet or "?", {"n": 0, "vol": 0.0, "buy": 0.0, "sell": 0.0})
        d["n"] += 1
        d["vol"] += usd
        d["buy" if kind == "buy" else "sell"] += usd
        total += usd
    top_wallet = max(by.items(), key=lambda kv: kv[1]["vol"])
    bots = [w for w, d in by.items()
            if d["n"] >= 15 and d["vol"] > 0 and abs(d["buy"] - d["sell"]) / d["vol"] < 0.15]
    bot_vol = sum(by[w]["vol"] for w in bots)
    sizes = Counter(round(usd, 1) for _, _, usd in rows if usd > 0)
    uniform = (sizes.most_common(1)[0][1] / len(rows)) if sizes else 0
    return {"n": len(rows), "unique": len(by), "distinct_ratio": len(by) / len(rows),
            "top_wallet": top_wallet[0], "top_wallet_share": 100 * top_wallet[1]["vol"] / total if total else 0,
            "bot_wallets": bots, "bot_share": 100 * bot_vol / total if total else 0,
            "uniform_share": uniform}


def check_pool(pool_address):
    out = {"drawdown_pct": None, "trades": {"n": 0}}
    try:
        d = get_json(f"{GECKO}/networks/solana/pools/{pool_address}/ohlcv/hour?aggregate=1&limit=48&currency=usd")
        candles = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        if candles:
            peak = max(c[2] for c in candles)
            last = sorted(candles, key=lambda c: c[0])[-1][4]
            out["drawdown_pct"] = 100 * (peak - last) / peak if peak else None
    except Exception as e:
        print(f"  (chart check failed: {e})")
    try:
        d = get_json(f"{GECKO}/networks/solana/pools/{pool_address}/trades")
        rows = []
        for t in d.get("data") or []:
            a = t.get("attributes") or {}
            rows.append((a.get("tx_from_address"), a.get("kind"), to_float(a.get("volume_in_usd")) or 0))
        out["trades"] = analyse_trades(rows)
    except Exception as e:
        print(f"  (trades check failed: {e})")
    return out


def judge(rpc_data, rug_data, pool_data, sell_data=None):
    """Combine all sources: REJECT / WATCH / UNVERIFIED."""
    fails, warns = [], []
    unverified = []
    if rpc_data is None and rug_data is None:
        return "UNVERIFIED", ["could not reach Solana RPC or RugCheck"], []

    src = rpc_data or rug_data
    if src.get("mint_authority"):
        fails.append("mint authority NOT revoked (dev can print more supply)")
    if src.get("freeze_authority"):
        fails.append("freeze authority NOT revoked (dev can freeze your tokens)")

    t22 = (rpc_data or {}).get("t22") or {}
    for k in ("permanent_delegate", "transfer_hook", "non_transferable", "default_frozen", "pausable"):
        if k in t22:
            fails.append(f"Token-2022 trap: {t22[k]}")
    fee = to_float(t22.get("transfer_fee_bps")) or 0
    if fee > TRANSFER_FEE_FAIL_BPS:
        fails.append(f"Token-2022 transfer fee {fee / 100:.1f}% on every transfer")
    elif fee > 0:
        warns.append(f"Token-2022 transfer fee {fee / 100:.1f}%")
    if "fee_changeable" in t22:
        warns.append(t22["fee_changeable"])

    if rpc_data and rpc_data.get("top10_wallets_pct") is not None:
        t = rpc_data["top10_wallets_pct"]
        if t > MAX_TOP10_PCT:
            fails.append(f"top-10 wallets own {t:.0f}% of supply (pools, curves and burns excluded)")
        elif t > WARN_TOP10_PCT:
            warns.append(f"top-10 wallets own {t:.0f}% of supply (watch concentration)")
    elif rpc_data:
        unverified.append("holder concentration could not be read")

    if sell_data is not None:
        if not sell_data.get("ok"):
            fails.append(f"sell test failed: {sell_data.get('detail')} (possible honeypot)")
        else:
            loss = sell_data.get("loss_pct")
            if loss is not None and loss > SELL_LOSS_FAIL:
                fails.append(f"sell test: selling ${PAPER_SIZE_USD} loses {loss:.0f}% (impact or hidden tax)")
            elif loss is not None and loss > SELL_LOSS_WARN:
                warns.append(f"sell test: selling ${PAPER_SIZE_USD} loses {loss:.0f}%")

    if rug_data:
        bad = [n for n, lvl in rug_data["risks"] if lvl in ("danger", "critical")]
        meh = [n for n, lvl in rug_data["risks"] if lvl == "warn"]
        if bad:
            fails.append("RugCheck danger flags: " + ", ".join(bad[:3]))
        if meh:
            warns.append("RugCheck warnings: " + ", ".join(meh[:3]))
        if rug_data.get("rugged"):
            fails.append("RugCheck marks this token as already rugged")
        if rug_data.get("creator_rug_flag"):
            fails.append("deployer has a rug / bad-history flag on RugCheck")
        ins = rug_data.get("insiders") or 0
        if ins >= INSIDER_FAIL:
            fails.append(f"{ins} insider-flagged wallets among top holders")
        elif ins >= INSIDER_WARN:
            warns.append(f"{ins} insider-flagged wallet(s) among top holders")
        if rug_data.get("creator_in_top"):
            warns.append("deployer wallet is still among the top holders")
        lp = rug_data.get("lp_locked_pct")
        if lp is not None and lp < 50:
            warns.append(f"only {lp:.0f}% of liquidity locked")
    else:
        warns.append("RugCheck unavailable - check rugcheck.xyz by hand")

    pd = pool_data or {}
    dd = pd.get("drawdown_pct")
    if dd is None:
        warns.append("48h chart check unavailable")
    elif dd > DRAWDOWN_FAIL:
        fails.append(f"already {dd:.0f}% below its 48h peak (spike-then-bleed pattern)")
    elif dd > DRAWDOWN_WARN:
        warns.append(f"{dd:.0f}% below its 48h peak")

    tr = pd.get("trades") or {"n": 0}
    if tr.get("n", 0) >= 30:
        if tr["distinct_ratio"] < DISTINCT_FAIL:
            fails.append(f"only {tr['unique']} wallets made the last {tr['n']} trades (a few wallets dominate)")
        elif tr["distinct_ratio"] < DISTINCT_WARN:
            warns.append(f"only {tr['unique']} wallets in the last {tr['n']} trades")
        if tr["top_wallet_share"] > TOP_WALLET_FAIL:
            fails.append(f"one wallet drives {tr['top_wallet_share']:.0f}% of recent volume")
        elif tr["top_wallet_share"] > TOP_WALLET_WARN:
            warns.append(f"one wallet drives {tr['top_wallet_share']:.0f}% of recent volume")
        if tr["bot_share"] > BOT_VOLUME_FAIL:
            fails.append(f"bot-like round-tripping wallets drive {tr['bot_share']:.0f}% of volume")
        elif tr["bot_wallets"]:
            warns.append(f"{len(tr['bot_wallets'])} wallet(s) trade like volume bots")
        if tr.get("uniform_share", 0) >= UNIFORM_FAIL:
            fails.append(f"{100 * tr['uniform_share']:.0f}% of recent trades are the same size (bot fingerprint)")
        elif tr.get("uniform_share", 0) >= UNIFORM_WARN:
            warns.append(f"{100 * tr['uniform_share']:.0f}% of recent trades are the same size")
    else:
        warns.append("trade-pattern check unavailable (too few trades to read)")

    if fails:
        return "REJECT", fails, warns
    if rpc_data is None:
        return "UNVERIFIED", ["Solana RPC unavailable - verify authorities on Solscan by hand"] + warns, []
    if unverified:
        return "UNVERIFIED", [u + " - verify on Solscan/RugCheck by hand" for u in unverified], warns
    return "WATCH", [], warns


def load_cache():
    try:
        with open(fp(CACHE_FILE)) as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def save_cache(cache, now=None):
    now = now or datetime.now(timezone.utc)
    keep = {}
    for m, v in cache.items():
        try:
            if (now - datetime.fromisoformat(v["at"])).total_seconds() < 72 * 3600:
                keep[m] = v
        except Exception:
            pass
    try:
        with open(fp(CACHE_FILE), "w") as f:
            json.dump(keep, f)
    except Exception as e:
        print(f"  (could not save cache: {e})")


def cache_fresh(entry, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        return (now - datetime.fromisoformat(entry["at"])).total_seconds() < CACHE_TTL_H * 3600
    except Exception:
        return False


def spot_check(p, demo=False, cache=None, checks=None):
    """Cheapest checks first. RPC + RugCheck results are cached for CACHE_TTL_H hours. If those already
       reject the coin (or both are unreachable), the slower chart/trades calls are skipped.
       Returns (verdict, fails, warns, fresh_cache_entry_or_None)."""
    mint = p["baseToken"]["address"]
    if demo:
        return judge(*demo_checks(mint)) + (None,)
    checks = checks or {"rpc": lambda m: check_rpc(m, p.get("pairAddress")), "rug": check_rugcheck,
                        "pool": check_pool, "sell": check_sell}
    entry = (cache or {}).get(mint)
    new_entry = None
    if entry and cache_fresh(entry):
        rpc_data, rug_data = entry.get("rpc"), entry.get("rug")
    else:
        rpc_data = rug_data = None
        try:
            rpc_data = checks["rpc"](mint)
        except Exception as e:
            print(f"  (RPC check failed for {mint[:6]}...: {e})")
        try:
            rug_data = checks["rug"](mint)
        except Exception as e:
            print(f"  (RugCheck failed for {mint[:6]}...: {e})")
        if (rpc_data is not None and rpc_data.get("holders_read", True)) or (rpc_data is None and rug_data is not None):
            new_entry = {"at": datetime.now(timezone.utc).isoformat(), "rpc": rpc_data, "rug": rug_data}
    sell_data, sell_warn = None, []
    if "sell" in checks and rpc_data is not None:
        try:
            sell_data = checks["sell"](mint, rpc_data.get("decimals"), p.get("priceUsd"))
        except Exception as e:
            sell_warn = [f"sell test unavailable ({e}) - try a tiny test sell quote by hand"]
    early, fails, warns = judge(rpc_data, rug_data, {}, sell_data)
    if early == "REJECT" or (rpc_data is None and rug_data is None):
        return early, fails, warns + sell_warn, new_entry
    pool_data = checks["pool"](p["pairAddress"]) if p.get("pairAddress") else None
    v, fails, warns = judge(rpc_data, rug_data, pool_data, sell_data)
    return v, fails, warns + sell_warn, new_entry


def recommendation(verdict, p, fails, warns, cost):
    price = p.get("priceUsd")
    if verdict == "WATCH":
        extra = f" Cautions: {'; '.join(warns)}." if warns else ""
        c = (f" Est. round-trip cost ~{cost['round_trip_pct']:.1f}% at ${PAPER_SIZE_USD} "
             f"(impact would be ~{cost['impact_10x_pct']:.1f}% at 10x that size).") if cost else ""
        return ("A calm look, paper only. Log entry at current price"
                f"{f' (${price})' if price else ''}, stop -30%, sell half at 2x, out by 24h." + c + extra)
    if verdict == "WATCH_LOGGED":
        return "Already on your paper list (logged within 48h), so it was not logged again."
    if verdict == "BENCH":
        return "Passed everything, but today's weather allows no more paper trades. Check again tomorrow."
    if verdict == "REJECT":
        return "Skip. " + "; ".join(fails)
    return "Not verified. " + "; ".join(fails) + " Do not trade until checked by hand."


# ======================= reason categories =======================
def reason_category(reason):
    t = reason.lower()
    if "liquidity unknown" in t:
        return "liquidity unknown"
    if "clone" in t:
        return "possible clone"
    if "chasing" in t:
        return "already ran (chasing)"
    if "exit cleanly" in t:
        return "cannot exit cleanly"
    if "liquidity" in t:
        return "thin liquidity"
    if "honeypot" in t or "sell test" in t or "token-2022" in t:
        return "honeypot / can't sell"
    if "too new" in t:
        return "too new to judge"
    if "collapse" in t or "peak" in t or "dump" in t:
        return "already collapsing"
    if any(w in t for w in ("volume", "wallet", "bot", "wash", "same size")):
        return "wash / bot volume"
    if any(w in t for w in ("authority", "rugcheck", "top-10", "insider", "rugged", "deployer", "concentration")):
        return "dev / insider risk"
    return "other"


def categories(reasons):
    return sorted({reason_category(r) for r in reasons})


# ======================= demo data =======================
def fetch_demo():
    now_ms = time.time() * 1000

    def mk(name, sym, liq, mcap, age_h, b, s, ch1, ch24, vol24, socials, site, desc):
        return ({
            "chainId": "solana", "_source": "demo", "priceUsd": "0.00012", "pairAddress": f"POOL{sym}",
            "baseToken": {"address": f"DEMO{sym}", "name": name, "symbol": sym},
            "liquidity": {} if liq is None else {"usd": liq}, "marketCap": mcap,
            "txns": {"h1": {"buys": b, "sells": s}},
            "priceChange": {"h1": ch1, "h24": ch24}, "volume": {"h24": vol24},
            "pairCreatedAt": now_ms - age_h * 3.6e6,
            "info": {"imageUrl": "x", "socials": [{"type": t} for t in socials],
                     "websites": [{"url": "x"}] if site else []},
        }, {"description": desc})

    tw = ["twitter", "telegram"]
    rows = [
        mk("Dublin Rain Cat", "DRAIN", 60_000, 400_000, 8, 220, 150, 35, 60, 500_000, tw, True,
           "A cat that only sleeps in the rain."),
        mk("Calm Heron", "CALM", 55_000, 450_000, 14, 120, 100, 12, 25, 300_000, tw, True,
           "A heron that waits for the market to settle."),
        mk("Ghost Dog Walker", "GHOST", 50_000, 250_000, 30, 90, 70, 5, 20, 300_000, tw, True,
           "Dog walking for ghosts after midnight."),
        mk("Botty McBotface", "BOTTY", 45_000, 300_000, 18, 160, 140, 10, 30, 400_000, tw, True,
           "A bot that trades with itself."),
        mk("Spike Frog", "SPIKE", 40_000, 280_000, 20, 130, 110, 4, 10, 350_000, tw, True,
           "Jumped once, never again."),
        mk("Quiet Owl", "OWL", 52_000, 280_000, 20, 60, 50, 8, 15, 90_000, tw, True,
           "An owl that audits other animals."),
        mk("Wash Frog", "WASH", 20_000, 40_000, 11, 300, 280, 10, 20, 1_900_000, ["twitter"], True, "Frog."),
        mk("Falling Knife", "DUMP", 18_000, 60_000, 12, 50, 400, -35, -88, 150_000, ["twitter"], True, "Fell."),
        mk("Pepper", "PEPPER", 70_000, 600_000, 26, 140, 120, 6, 12, 200_000, tw, True,
           "The original pepper, grown slowly."),
        mk("Pepper", "PEPPER", 16_000, 90_000, 5, 80, 70, 9, 18, 120_000, tw, True, "Totally the same pepper."),
        mk("Resolvable Rook", "ROOK", None, 500_000, 6, 90, 70, 15, 30, 100_000, tw, True,
           "A chess bird whose liquidity the main feed could not see, but Jupiter can."),
        mk("Mystery Moth", "MOTH", None, 500_000, 9, 95, 80, 10, 20, 100_000, tw, True,
           "A moth no feed can see. A blind spot, not a verdict."),
        mk("Insider Ibis", "IBIS", 48_000, 300_000, 16, 110, 95, 7, 14, 150_000, tw, True,
           "An ibis whose friends all arrived early."),
    ]
    # give PEPPER copies distinct mints
    rows[9][0]["baseToken"]["address"] = "DEMOPEPPER2"
    rows[9][0]["pairAddress"] = "POOLPEPPER2"
    return [r[0] for r in rows], {r[0]["baseToken"]["address"]: r[1] for r in rows}


def demo_jupiter(mints):
    out = {m: {"liquidity": None, "mcap": None, "organic": 72.0, "price": None} for m in mints}
    out["DEMOROOK"]["liquidity"] = 47_000
    out["DEMOWASH"]["organic"] = 9.0
    out["DEMOCALM"]["liquidity"] = 12_000       # disagrees with the main feed (55k) by 4.6x -> lower is used
    return out


def demo_checks(mint):
    import random
    rnd = random.Random(mint)
    good = {"mint_authority": None, "freeze_authority": None, "top10_pct": 40, "top10_wallets_pct": 18, "t22": {}}
    rug = {"risks": [("Mutable metadata", "warn")], "lp_locked_pct": 100, "mint_authority": None,
           "freeze_authority": None, "rugged": False, "insiders": 0, "creator_in_top": False,
           "creator_rug_flag": False}
    healthy = [(f"W{i % 140}", "buy" if rnd.random() < 0.55 else "sell", rnd.uniform(5, 80)) for i in range(300)]
    pool = {"drawdown_pct": 20.0, "trades": analyse_trades(healthy)}
    if mint.endswith("GHOST"):
        return dict(good, mint_authority="SoMeDeVwAlLeT"), rug, pool
    if mint.endswith("OWL"):
        return None, None, None
    if mint.endswith("BOTTY"):
        rows = [("BOT1", "buy" if i % 2 == 0 else "sell", 100.0) for i in range(150)]
        rows += [(f"X{i % 120}", "buy", 10.0) for i in range(150)]
        return good, rug, {"drawdown_pct": 15.0, "trades": analyse_trades(rows)}
    if mint.endswith("SPIKE"):
        return good, rug, {"drawdown_pct": 83.0, "trades": analyse_trades(healthy)}
    if mint.endswith("IBIS"):
        return good, dict(rug, insiders=5, creator_in_top=True), pool
    return good, rug, pool


# ======================= paper trades =======================
def recent_paper_mints(hours=PAPER_COOLDOWN_H):
    out = set()
    now = datetime.now(timezone.utc)
    for r in load_csv(fp(PAPER_FILE)):
        try:
            t = datetime.fromisoformat(r["logged_at"])
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if (now - t).total_seconds() / 3600 < hours:
                out.add(r["address"])
        except Exception:
            out.add(r.get("address"))
    return out


def log_paper_trade(p, mint, first_price, cost):
    rows = load_csv(fp(PAPER_FILE))
    price = to_float(p.get("priceUsd"))
    fpz = to_float(first_price) or price
    drift = 100 * (price - fpz) / fpz if price and fpz else ""
    rows.append({"logged_at": now_iso(), "symbol": p["baseToken"]["symbol"], "address": mint,
                 "entry_price_usd": p.get("priceUsd") or "", "entry_mcap": p.get("marketCap") or "",
                 "first_seen_price": fpz or "", "drift_pct": f"{drift:.1f}" if drift != "" else "",
                 "est_cost_pct": f"{cost['round_trip_pct']:.2f}" if cost else "",
                 "liq_usd": liquidity_of(p) or "", "size_usd": PAPER_SIZE_USD, "status": "open"})
    save_csv(fp(PAPER_FILE), PAPER_COLS, rows)


def update_paper(rows, prices, now):
    print(f"\n{'SYMBOL':<11}{'AGE':<7}{'ENTRY':<13}{'NOW':<13}{'GROSS':<9}{'NET of costs'}")
    for r in rows:
        mint = r["address"]
        entry = to_float(r["entry_price_usd"])
        age_h = hours_since(r["logged_at"], now) if r.get("logged_at") else 0
        if mint not in prices:
            print(f"{r['symbol'][:10]:<11}{age_h:>4.0f}h  price lookup failed this time (will retry)")
            continue
        cur = exit_price(prices[mint])
        if entry and cur is not None:
            gross = 100 * (cur - entry) / entry
            cost = to_float(r.get("est_cost_pct")) or 2.0
            net = gross - cost if cur > 0 else -100.0
            note = "so far" if age_h < 24 else "final-ish (24h+)"
            if cur == 0.0:
                note = "pool dead or liquidity pulled - counted as total loss"
            r.update(checked_at=now.isoformat(timespec="minutes"), price_now_usd=cur, change_pct=f"{gross:.1f}",
                     net_change_pct=f"{net:.1f}", note=note, status="closed-ish" if age_h >= 24 else "open")
            print(f"{r['symbol'][:10]:<11}{age_h:>4.0f}h  {entry:<13.8g}{cur:<13.8g}{gross:+7.1f}%  {net:+7.1f}%")
        else:
            print(f"{r['symbol'][:10]:<11}{age_h:>4.0f}h  no usable price")


# ======================= 3. shadow log =======================
def categories_text(reasons):
    return "|".join(categories(reasons))


DEEP_VERDICTS = {"WATCH", "WATCH_LOGGED", "BENCH", "REJECT", "UNVERIFIED"}


def shadow_log(results, weather, jup):
    path = fp(SHADOW_FILE)
    rows = load_csv(path)
    idx = {r["mint"]: r for r in rows}
    now = now_iso()
    new = 0
    for r in results:
        p, mint = r["p"], r["mint"]
        if mint in idx:
            row = idx[mint]
            row["last_seen"] = now
            row["seen_count"] = str(int(row.get("seen_count") or 1) + 1)
            # first-seen verdict stays frozen (no look-ahead); a LATER deep-check verdict is recorded beside it
            if r["verdict"] in DEEP_VERDICTS and row.get("verdict") not in DEEP_VERDICTS and not row.get("final_verdict"):
                row["final_verdict"], row["final_at"] = r["verdict"], now
            continue
        s, b = r["scores"], p["baseToken"]
        age = age_hours(p)
        row = {"mint": mint, "symbol": b.get("symbol"), "name": b.get("name"), "first_seen": now,
               "last_seen": now, "seen_count": "1", "weather": weather["regime"], "source": p.get("_source", ""),
               "liq_usd": liquidity_of(p) if liquidity_of(p) is not None else "", "liq_src": p.get("_liq_src", ""),
               "mcap": p.get("marketCap") or "", "age_h": f"{age:.1f}" if age is not None else "",
               "entry_price": p.get("priceUsd") or "", "verdict": r["verdict"],
               "categories": categories_text(r["fails"]), "reasons": "; ".join(r["fails"]),
               "warnings": "; ".join(r["warns"]), "narrative": s["narrative"], "meme": s["meme"],
               "community": s["community"], "timing": s["timing"], "value": s["value"], "total": r["total"],
               "organic": (jup.get(mint) or {}).get("organic") or "",
               "est_cost_pct": f"{r['cost']['round_trip_pct']:.2f}" if r.get("cost") else "",
               "p1h": "", "p6h": "", "p24h": "", "p72h": "", "rules_version": _rules_fingerprint()}
        rows.append(row)
        idx[mint] = row
        new += 1
    save_csv(path, SHADOW_COLS, rows)
    return new, len(rows)


def shadow_needs(rows, now):
    need = []
    for r in rows:
        entry = to_float(r.get("entry_price"))
        age = hours_since(r["first_seen"], now)
        for col, h, latest in HORIZONS:
            if r.get(col, "") == "" and age >= h and entry:
                need.append(r["mint"])
                break
    return need


def hours_since(iso, now):
    t = datetime.fromisoformat(iso)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 3600


def update_shadow(rows, prices, now):
    """Fills 1h/6h/24h/72h snapshots. Once a coin is DEAD, every later snapshot is DEAD too (a rug does not
       come back, and v1.4.1 let it vanish as NA). Returns (filled, missed, no_entry)."""
    filled = missed = no_entry = 0
    for r in rows:
        entry = to_float(r.get("entry_price"))
        age = hours_since(r["first_seen"], now)
        dead = False
        for col, h, latest in HORIZONS:
            if r.get(col, "") == "DEAD":
                dead = True
            if r.get(col, "") != "" or age < h:
                continue
            if not entry:
                r[col] = "NA"
                no_entry += 1
                continue
            if dead:
                r[col] = "DEAD"
                filled += 1
                continue
            if age > latest:
                r[col] = "NA"          # too late to be an honest reading
                missed += 1
                continue
            if r["mint"] not in prices:
                continue               # lookup failed - leave blank and retry next run
            info = prices[r["mint"]]
            px = exit_price(info)
            if px is None:
                continue
            r[col] = "DEAD" if px == 0.0 else repr(px)
            if info and info.get("liq") is not None:
                r[LIQ_COL[col]] = f"{info['liq']:.0f}"
            dead = px == 0.0
            filled += 1
    return filled, missed, no_entry


def snap_value(s):
    if s in (None, "", "NA"):
        return None
    if s == "DEAD":
        return 0.0
    return to_float(s)


def recheck():
    ensure_files()
    paper = load_csv(fp(PAPER_FILE))
    shadow = load_csv(fp(SHADOW_FILE))
    now = datetime.now(timezone.utc)
    live_paper = [r for r in paper if not (r.get("price_now_usd") and r.get("logged_at")
                                         and hours_since(r["logged_at"], now) > 72)]
    addrs = list(dict.fromkeys([r["address"] for r in live_paper][-200:] + shadow_needs(shadow, now)))
    if not addrs:
        print("Nothing to re-price yet. Run a scan first.")
        return
    prices = fetch_prices(addrs)
    if live_paper:
        update_paper(live_paper, prices, now)
        save_csv(fp(PAPER_FILE), PAPER_COLS, paper)
    if shadow:
        filled, missed, no_entry = update_shadow(shadow, prices, now)
        save_csv(fp(SHADOW_FILE), SHADOW_COLS, shadow)
        print(f"\nShadow log: filled {filled} price snapshot(s); {missed} horizon(s) marked NA "
              f"(the recheck came too late to be honest); {no_entry} NA because the coin had no entry price.")
    print("Run --report once you have 100+ coins with 24h outcomes.")


# ======================= 4. gate report =======================
def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x, y):
    if len(x) < 3 or len(x) != len(y):
        return None
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return None if vx == 0 or vy == 0 else cov / (vx * vy)


def median(xs):
    s = sorted(xs)
    n = len(s)
    return None if n == 0 else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


def row_return(r, col):
    entry = to_float(r.get("entry_price"))
    v = snap_value(r.get(col))
    if not entry or v is None:
        return None
    return 100 * (v - entry) / entry


def wilson(k, n, z=1.96):
    """95% range for a rate of k out of n (Wilson score interval), in %."""
    if not n:
        return None, None
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5) / d
    return 100 * max(0.0, c - h), 100 * min(1.0, c + h)


def group_stats(rets):
    if not rets:
        return None
    n = len(rets)
    k_rug = sum(1 for x in rets if x <= -70)
    k_dbl = sum(1 for x in rets if x >= 100)
    return {"n": n, "median": median(rets), "rugged": 100 * k_rug / n, "doubled": 100 * k_dbl / n,
            "rug_ci": wilson(k_rug, n), "dbl_ci": wilson(k_dbl, n)}


SURVIVORS = "survivors (WATCH/BENCH)"
BLOCKED = ("blocked by the gate", "blocked by deep checks")
PASSED_LATER = "blocked first, passed later"


def verdict_class(v, final=None):
    """v1.4.1 bugs fixed: WATCH_LOGGED is a survivor; UNVERIFIED (checks never ran) is NOT a survivor;
       a coin blocked at first sight but WATCHed later no longer pollutes the blocked group."""
    if v in ("SKIP", "REJECT") and final in ("WATCH", "WATCH_LOGGED", "BENCH"):
        return PASSED_LATER
    return {"SKIP": "blocked by the gate", "REJECT": "blocked by deep checks",
            "UNCHECKED": "passed gate, not deep-checked",
            "WATCH": SURVIVORS, "WATCH_LOGGED": SURVIVORS, "BENCH": SURVIVORS,
            "UNVERIFIED": "not verified (checks failed)"}.get(v, v)


def row_class(r):
    return verdict_class(r.get("verdict"), r.get("final_verdict"))


def plan_cost(r):
    """Round-trip cost for the exit simulation: half at entry liquidity, half at the THINNEST liquidity seen
       at the 1h/6h/24h snapshots. Unknown -> UNKNOWN_COST_PCT (was a flattering 2%)."""
    entry = to_float(r.get("est_cost_pct"))
    liqs = [to_float(r.get(c)) for c in ("l1h", "l6h", "l24h")]
    liqs = [x for x in liqs if x and x > 0]
    exit_c = est_costs(min(liqs)) if liqs else None
    if entry is None:
        return UNKNOWN_COST_PCT
    return entry / 2 + (exit_c["round_trip_pct"] / 2 if exit_c else entry / 2)


def analyse_shadow(rows):
    """24h only (the success rules are 24h rules). v1.4.1 silently fell back to 6h/1h."""
    horizon = "p24h"
    scored = [(r, row_return(r, horizon)) for r in rows]
    scored = [(r, x) for r, x in scored if x is not None]
    out = {"horizon": horizon, "n_logged": len(rows), "n_outcomes": len(scored),
           "base": group_stats([x for _, x in scored]), "classes": {}, "rules": {}, "rho": {}, "plan": {},
           "na": {}, "weather": {}}
    cls = {}
    for r, x in scored:
        cls.setdefault(row_class(r), []).append(x)
    out["classes"] = {k: group_stats(v) for k, v in cls.items()}
    for r in rows:                                   # missing 24h readings per group (never silently dropped)
        k = row_class(r)
        d = out["na"].setdefault(k, {"na": 0, "due": 0})
        try:
            overdue = hours_since(r["first_seen"], datetime.now(timezone.utc)) > 36
        except Exception:
            overdue = False
        if r.get("p24h", "") != "" or overdue:
            d["due"] += 1
            if r.get("p24h", "") in ("NA", ""):
                d["na"] += 1
    rules = {}
    for r, x in scored:
        for c in (r.get("categories") or "").split("|"):
            if c:
                rules.setdefault(c, []).append(x)
    out["rules"] = {k: group_stats(v) for k, v in rules.items()}
    wx = {}
    for r, x in scored:
        k = row_class(r)
        side = "survivors" if k == SURVIVORS else ("blocked" if k in BLOCKED else None)
        if side:
            wx.setdefault(r.get("weather") or "UNKNOWN", {}).setdefault(side, []).append(x)
    out["weather"] = {w: {s_: group_stats(v) for s_, v in d.items()} for w, d in wx.items()}
    if len(scored) >= 30:
        ys = [x for _, x in scored]
        for k in ("narrative", "meme", "community", "timing", "value", "total"):
            xs = [to_float(r.get(k)) or 0 for r, _ in scored]
            out["rho"][k] = spearman(xs, ys)
    plan = {}
    for r in rows:
        entry = to_float(r.get("entry_price"))
        snaps = [(1, snap_value(r.get("p1h"))), (6, snap_value(r.get("p6h"))), (24, snap_value(r.get("p24h")))]
        res = simulate_exit_full(entry, snaps, plan_cost(r))
        if res is None:
            continue
        pnl, closed = res
        if snap_value(r.get("p24h")) is None and not closed:
            continue                                 # no 24h reading and the stop never fired -> unknown
        plan.setdefault(row_class(r), []).append(pnl)
    out["plan"] = {k: {"n": len(v), "median": median(v), "mean": sum(v) / len(v),
                       "positive": 100 * sum(1 for x in v if x > 0) / len(v)} for k, v in plan.items()}
    out["test"] = test_verdict(out)
    return out


def _merge(stats_list):
    """Combine group_stats of several groups (blocked by gate + blocked by deep checks)."""
    st = [g for g in stats_list if g]
    if not st:
        return None
    n = sum(g["n"] for g in st)
    k_rug = round(sum(g["rugged"] * g["n"] / 100 for g in st))
    k_dbl = round(sum(g["doubled"] * g["n"] / 100 for g in st))
    return {"n": n, "rugged": 100 * k_rug / n, "doubled": 100 * k_dbl / n,
            "rug_ci": wilson(k_rug, n), "dbl_ci": wilson(k_dbl, n)}


def test_verdict(a):
    """The three success rules from the v1.4 test plan. NOT YET until each group has MIN_GROUP coins."""
    S = a["classes"].get(SURVIVORS)
    B = _merge([a["classes"].get(k) for k in BLOCKED])
    P = a["plan"].get(SURVIVORS)
    out = []
    if not S or not B or S["n"] < MIN_GROUP or B["n"] < MIN_GROUP:
        out.append(("NOT YET", "Survivors lose 70%+ less often than blocked coins",
                    f"need {MIN_GROUP}+ in each group (survivors {S['n'] if S else 0}, blocked {B['n'] if B else 0})"))
    else:
        txt = (f"survivors {S['rugged']:.0f}% [{S['rug_ci'][0]:.0f}-{S['rug_ci'][1]:.0f}] vs "
               f"blocked {B['rugged']:.0f}% [{B['rug_ci'][0]:.0f}-{B['rug_ci'][1]:.0f}]")
        if S["rugged"] >= B["rugged"]:
            out.append(("FAIL", "Survivors lose 70%+ less often than blocked coins", txt))
        elif S["rug_ci"][1] < B["rug_ci"][0]:
            out.append(("PASS", "Survivors lose 70%+ less often than blocked coins", txt))
        else:
            out.append(("LEANING", "Survivors lose 70%+ less often than blocked coins",
                        txt + " - ranges overlap, could still be luck"))
    if not P or P["n"] < MIN_GROUP:
        out.append(("NOT YET", "Survivors' median exit-plan result is positive after costs",
                    f"need {MIN_GROUP}+ survivors with a result (have {P['n'] if P else 0})"))
    else:
        out.append(("PASS" if P["median"] > 0 else "FAIL", "Survivors' median exit-plan result is positive after costs",
                    f"median {P['median']:+.0f}%, {P['positive']:.0f}% of {P['n']} trades positive"))
    if not S or not B or S["n"] < MIN_GROUP or B["n"] < MIN_GROUP:
        out.append(("NOT YET", "The gate isn't blocking more winners than survivors have", "same sample need"))
    else:
        ok = B["doubled"] <= S["doubled"] + 5
        out.append(("PASS" if ok else "WATCH", "The gate isn't blocking more winners than survivors have",
                    f"doubled: blocked {B['doubled']:.0f}% vs survivors {S['doubled']:.0f}%"))
    return out


def blind_spot_summary(rows):
    blind = [r for r in rows if "liquidity unknown" in (r.get("categories") or "")]
    return len(blind), len(rows)


def report(include_all=False):
    every = load_csv(fp(SHADOW_FILE))
    if not every:
        print("No shadow_log.csv yet. Run some scans first - every scanned coin gets logged.")
        return
    ver = _rules_fingerprint()
    rows = every if include_all else [r for r in every if r.get("rules_version") == ver]
    print("=" * 60)
    print("  GATE SCORECARD  (did the rules help, or just feel safe?)")
    print("=" * 60)
    print(f"Rules version {ver}." + (" Showing ALL versions mixed (--all) - not a valid test."
                                     if include_all else
                                     f" Counting only rows from this version; {len(every) - len(rows)} older "
                                     f"row(s) kept as a pilot (see them with --report --all)."))
    if not rows:
        print("\nNo rows from this rules version yet. The test count starts with your next scan.")
        return
    a = analyse_shadow(rows)
    nb, nt = blind_spot_summary(rows)
    print(f"Coins logged: {a['n_logged']}   with a 24h outcome: {a['n_outcomes']}   "
          f"blind (liquidity unknown): {nb} of {nt} ({100 * nb / nt:.0f}%)")

    print("\nTEST VERDICT (24h, rules frozen - change any rule and the count restarts by itself)")
    for status, rule, why in a["test"]:
        print(f"  [{status:<7}] {rule}\n            {why}")
    if not a["base"]:
        print("\nNo 24h outcomes yet. Keep --recheck running hourly.")
        return
    b = a["base"]
    print(f"\nEverything scanned (24h): median {b['median']:+.0f}%, {b['rugged']:.0f}% lost 70%+ "
          f"[{b['rug_ci'][0]:.0f}-{b['rug_ci'][1]:.0f}], {b['doubled']:.0f}% doubled.   (DEAD = -100%)")
    print("\nBy outcome of the gate (24h; [95% range]; NA = 24h reading missed):")
    for k, g in sorted(a["classes"].items()):
        na = a["na"].get(k, {"na": 0, "due": 0})
        nas = f"NA {na['na']}/{na['due']}" if na["due"] else "NA -"
        print(f"  {k:<32} n={g['n']:<4} median {g['median']:+6.0f}%   lost70+ {g['rugged']:>3.0f}% "
              f"[{g['rug_ci'][0]:.0f}-{g['rug_ci'][1]:.0f}]   doubled {g['doubled']:>3.0f}%   {nas}")
    if a["plan"]:
        print("\nExit plan (stop -30%, half off at 2x, out at 24h, net of costs; snapshot-based, so real stops"
              " can fill worse):")
        for k, g in sorted(a["plan"].items()):
            print(f"  {k:<32} n={g['n']:<4} median {g['median']:+6.0f}%   mean {g['mean']:+6.0f}%   "
                  f"positive {g['positive']:.0f}%")
    if a["weather"]:
        print("\nBy market weather (is the market taking the scanner's credit?):")
        for w, d in sorted(a["weather"].items()):
            sv, bl = d.get("survivors"), d.get("blocked")
            f_ = lambda g: f"n={g['n']:<3} lost70+ {g['rugged']:>3.0f}%" if g else "n=0"
            print(f"  {w:<9} survivors {f_(sv):<22} blocked {f_(bl)}")
    print("\nEXPLORATORY - rule by rule (do NOT change rules from this alone; test a change as a new version):")
    for k, g in sorted(a["rules"].items(), key=lambda kv: -kv[1]["n"]):
        if g["n"] < 10:
            verdict = "too few to judge"
        elif g["rugged"] >= 2 * max(g["doubled"], 5):
            verdict = "blocking mostly rugs"
        elif g["doubled"] > g["rugged"]:
            verdict = "blocking more winners than rugs?"
        else:
            verdict = "mixed"
        print(f"  {k:<26} n={g['n']:<4} lost70+ {g['rugged']:>3.0f}%  doubled {g['doubled']:>3.0f}%   {verdict}")
    if a["rho"]:
        print("\nEXPLORATORY - do the concept scores predict anything? (Spearman vs 24h return)")
        cut = 1.96 / max(1, a["n_outcomes"] - 1) ** 0.5
        for k, v in a["rho"].items():
            tag = "" if v is None else ("  <- beyond chance level" if abs(v) >= cut else "  (within chance)")
            print(f"  {k:<10} {('n/a' if v is None else f'{v:+.2f}')}{tag}")
        print(f"  Chance level at this sample is about +/-{cut:.2f}, and 6 scores are tested at once, so expect")
        print("  one to look meaningful by luck. Never reweight on one report.")
    print("\nCaveats: returns start at the first-seen price; real fills are worse, especially in small pools.")


# ======================= calm report =======================
CALM_LINES = [
    "Cash is a position. You don't owe the market a trade.",
    "Missing a pump costs you nothing. Joining a rug costs real money.",
    "Eat something and drink some water before any decision. Tired brains chase.",
    "Write it in the journal first. Then decide.",
    "The coins you skipped today can't hurt you tomorrow.",
    "Boring and steady beats exciting and broke.",
]

WEATHER_TEXT = {
    "GREEN": "Green skies. More people are trading, so there's more room for real buyers. Rules are normal.",
    "NEUTRAL": "Calm and steady. Nothing unusual from the big coins. Rules are normal.",
    "RED": ("Red skies. When the big coins fall, real traders go quiet and bots fill the gap, "
            "so today's rules are STRICTER."),
    "DEEP_RED": ("Deep red. The big coins are falling hard and real trading dries up. Bots and dumps "
                 "dominate. Today is a stand-down day: look, learn, log, don't trade."),
    "UNKNOWN": "Couldn't read the big coins, so I'm being a little extra careful today.",
}


def print_calm_report(data):
    results, weather, watch = data["results"], data["weather"], data["watch"]
    print("\n" + "=" * 56)
    print("  THE CALM PART")
    print("=" * 56)
    avoided = [r for r in results if r["verdict"] in ("SKIP", "REJECT")]
    blind = [r for r in avoided if "liquidity unknown" in categories_text(r["fails"])]
    print(f"Coins scanned: {len(results)}")
    print(f"Traps you did NOT walk into: {len(avoided) - len(blind)}")
    cats = Counter()
    for r in avoided:
        for c in categories(r["fails"])[:1]:
            cats[c] += 1
    for c, n in cats.most_common():
        print(f"   - {n} x {c}")
    if blind:
        best = max(blind, key=lambda r: r["total"])
        print(f"Blind spots (no feed could see liquidity): {len(blind)}. These are data gaps, not verdicts. "
              f"Highest scorer: {best['p']['baseToken']['symbol']} ({best['total']}) - still untradeable until it can be seen.")
    print(f"Worth a calm look today: {watch}")
    if weather["regime"] == "DEEP_RED":
        print("\nStand-down day. There is nothing here you need to chase.")
    elif watch == 0:
        print("\nNothing earned a place today, and that's a good result. Doing nothing is a skill.")
    print("\n" + CALM_LINES[datetime.now().toordinal() % len(CALM_LINES)])


# ======================= the scan engine =======================
def run_scan(demo=False, demo_regime="NEUTRAL"):
    STATE["demo"] = demo
    ensure_files()
    t0 = time.monotonic()
    timings = {}
    weather = market_weather(demo, demo_regime)
    rules = WEATHER_RULES[weather["regime"]]
    floor = BASE_MIN_LIQUIDITY * rules["liq_mult"]
    pairs, profiles = fetch_demo() if demo else fetch_live()
    if not pairs:
        return None

    timings["feeds"] = time.monotonic() - t0
    t1 = time.monotonic()
    jup = fetch_enrichment(pairs, demo)
    liq_stats = resolve_liquidity(pairs, jup,
                                  fetchers={} if demo else None)
    timings["liquidity"] = time.monotonic() - t1
    groups = duplicate_groups(pairs)
    first = {r["mint"]: r for r in load_csv(fp(SHADOW_FILE))}
    on_paper = recent_paper_mints()

    results = []
    for p in pairs:
        mint = p["baseToken"]["address"]
        ctx = {"peers": clone_peers(p, groups), "first_price": (first.get(mint) or {}).get("entry_price")}
        passed, fails, warns = safety_gate(p, floor, ctx)
        scores, total = score_concept(p, profiles.get(mint))
        results.append({"p": p, "mint": mint, "gate": passed, "fails": fails, "warns": warns,
                        "scores": scores, "total": total, "verdict": "SKIP" if not passed else "PENDING",
                        "rec": "", "cost": est_costs(liquidity_of(p)), "first_price": ctx["first_price"]})
    results.sort(key=lambda r: (not r["gate"], -r["total"]))

    cands = [r for r in results if r["gate"] and r["total"] >= rules["min_score"]][:SPOT_CHECK_TOP_N]
    data = {"weather": weather, "rules": rules, "floor": floor, "results": results, "watch": 0,
            "liq_stats": liq_stats, "n_cands": len(cands), "n_gate": sum(r["gate"] for r in results),
            "updated": datetime.now(timezone.utc), "new_logged": 0, "demo": demo}
    print_header(data)
    t2 = time.monotonic()
    cache = {} if demo else load_cache()
    cache_hits = sum(1 for r in cands if cache_fresh(cache.get(r["mint"]) or {}))
    outcomes = {}
    ex = ThreadPoolExecutor(max_workers=CHECK_WORKERS)
    futs = {ex.submit(spot_check, r["p"], demo, cache): r["mint"] for r in cands}
    budget = max(2.0, MAX_RUN_SECONDS - (time.monotonic() - t0))
    done, not_done = fut_wait(futs, timeout=budget)
    for f in done:
        try:
            outcomes[futs[f]] = f.result()
        except Exception as e:
            outcomes[futs[f]] = ("UNVERIFIED", [f"deep check crashed: {e}"], [], None)
    ex.shutdown(wait=False, cancel_futures=True)
    for m, o in outcomes.items():
        if o[3]:
            cache[m] = o[3]
    if not demo:
        save_cache(cache)
    timings["deep_checks"] = time.monotonic() - t2
    data["cache_hits"], data["timed_out"] = cache_hits, len(not_done)
    for r in cands:                      # processed in score order, so paper-trade logging stays deterministic
        if r["mint"] not in outcomes:
            r["verdict"] = "UNCHECKED"
            r["rec"] = "Deep check skipped: the run hit its time budget. It will be tried again next run."
            continue
        v, fails, warns, _ = outcomes[r["mint"]]
        r["verdict"], r["fails"], r["warns"] = v, fails, warns + r["warns"]
        if v == "WATCH":
            if r["mint"] in on_paper:
                r["verdict"] = "WATCH_LOGGED"
            elif data["watch"] >= rules["max_watch"]:
                r["verdict"] = "BENCH"
            else:
                log_paper_trade(r["p"], r["mint"], r["first_price"], r["cost"])
                data["watch"] += 1
                data.setdefault("new_watch", []).append(r)
        r["rec"] = recommendation(r["verdict"], r["p"], fails, r["warns"], r["cost"])
    sent = 0
    for r in data.get("new_watch", []):
        if not demo and tg_send(watch_message(r, weather)):
            sent += 1
    data["tg_sent"] = sent
    for r in results:
        if r["verdict"] == "PENDING":
            r["verdict"] = "UNCHECKED"
            r["rec"] = f"Passed the gate, but under today's score bar ({rules['min_score']}) or past the spot-check cut."
        elif r["verdict"] == "SKIP":
            r["rec"] = "Skip. " + "; ".join(r["fails"])

    order = {"WATCH": 0, "WATCH_LOGGED": 0, "BENCH": 1, "UNVERIFIED": 2, "UNCHECKED": 3, "REJECT": 4, "SKIP": 5}
    results.sort(key=lambda r: (order[r["verdict"]], -r["total"]))
    t3 = time.monotonic()
    data["new_logged"], data["shadow_total"] = shadow_log(results, weather, jup)
    write_scan_log(results, weather)
    timings["logging"] = time.monotonic() - t3
    timings["total"] = time.monotonic() - t0
    data["timings"] = timings
    data["api"] = {"calls": STATS["calls"], "rate_limited": STATS["rate_limited"]}
    data["health"] = write_health(data)
    return data


# ======================= Telegram alerts =======================
def tg_config():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def tg_send(text, opener=None):
    """Sends one plain-text message. Never raises: an alert must not break a scan.
       Returns True if Telegram accepted it. The token is never printed."""
    token, chat = tg_config()
    if not token or not chat:
        return False
    body = json.dumps({"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"{TG_API}/bot{token}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=15) as r:
            return bool(json.load(r).get("ok"))
    except Exception as e:
        msg = str(e).replace(token, "***")
        print(f"  (Telegram alert not sent: {msg})")
        return False


def watch_message(r, weather):
    p, mint = r["p"], r["mint"]
    b = p["baseToken"]
    liq, mcap = liquidity_of(p), to_float(p.get("marketCap") or p.get("fdv"))
    cost = r.get("cost")
    lines = [f"NEXUS WATCH: {b.get('symbol', '?')} ({b.get('name', '')})".strip(),
             f"Score {r['total']} | weather {weather['regime']}",
             f"Price ${p.get('priceUsd', '?')} | liquidity {fmt_usd(liq)} | mcap {fmt_usd(mcap)}"]
    if cost:
        lines.append(f"Est. round-trip cost ~{cost['round_trip_pct']:.1f}% at ${PAPER_SIZE_USD}")
    if r.get("warns"):
        lines.append("Cautions: " + "; ".join(r["warns"][:4]))
    lines += ["Plan: stop -30%, sell half at 2x, out by 24h.",
              f"Mint: {mint}",
              f"Chart: https://dexscreener.com/solana/{p.get('pairAddress') or mint}",
              f"RugCheck: https://rugcheck.xyz/tokens/{mint}",
              "PAPER TRADE ONLY. WATCH is not SAFE. Check the mint before touching anything."]
    return "\n".join(lines)


def tg_setup():
    """Prints the chat id(s) of anyone who has messaged your bot, so you can set TELEGRAM_CHAT_ID."""
    token, _ = tg_config()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN first (the token @BotFather gave you).")
        return
    try:
        with urllib.request.urlopen(f"{TG_API}/bot{token}/getUpdates", timeout=15) as r:
            data = json.load(r)
    except Exception as e:
        print("Could not reach Telegram:", str(e).replace(token, "***"))
        return
    chats = {}
    for u in data.get("result") or []:
        c = ((u.get("message") or u.get("channel_post") or {}).get("chat")) or {}
        if c.get("id") is not None:
            chats[c["id"]] = c.get("username") or c.get("title") or c.get("first_name") or ""
    if not chats:
        print("No messages yet. Open your bot in Telegram, press Start, send 'hi', then run this again.")
    for cid, who in chats.items():
        print(f"TELEGRAM_CHAT_ID = {cid}   ({who})")


def write_health(data):
    """One row per scan in scan_health.csv, so broken data is spotted in hours, not days."""
    ls = data.get("liq_stats") or {}
    total = ls.get("total") or 0
    blind = ls.get("unknown_after") or 0
    blind_pct = 100 * blind / total if total else 0
    unver = sum(1 for r in data["results"] if r["verdict"] == "UNVERIFIED")
    alerts = []
    if blind_pct > HEALTH_BLIND_ALERT:
        alerts.append(f"blind {blind_pct:.0f}%")
    if data["api"]["rate_limited"] >= 5:
        alerts.append(f"{data['api']['rate_limited']} rate limits")
    if data.get("timed_out"):
        alerts.append(f"{data['timed_out']} deep checks timed out")
    if data["n_cands"] and unver == data["n_cands"]:
        alerts.append("every deep check UNVERIFIED (RPC/RugCheck down?)")
    row = {"at": now_iso(), "rules_version": _rules_fingerprint(), "coins": total, "blind": blind,
           "blind_pct": f"{blind_pct:.0f}", "deep_checked": data["n_cands"], "unverified": unver,
           "api_calls": data["api"]["calls"], "rate_limited": data["api"]["rate_limited"],
           "timed_out": data.get("timed_out", 0), "seconds": f"{data['timings'].get('total', 0):.0f}",
           "alert": "; ".join(alerts)}
    path = fp(HEALTH_FILE)
    rows = load_csv(path)[-2000:] + [row]
    save_csv(path, list(row), rows)
    if alerts:
        print(f"\n!! HEALTH ALERT: {'; '.join(alerts)}. Results from this run are less trustworthy.")
    return row


def print_header(data):
    w, rules, floor, ls = data["weather"], data["rules"], data["floor"], data["liq_stats"]
    print("=" * 56)
    print(f"  TIMMY'S CONCEPT SCORER v{VERSION} - NEXUS DEEP SCAN" + ("   [DEMO]" if data["demo"] else ""))
    print("=" * 56)
    moves = ", ".join(f"{k} {v:+.1f}%" for k, v in w["changes"].items() if v is not None) or "no data"
    avg = f"{w['avg']:+.1f}%" if w["avg"] is not None else "n/a"
    print(f"Market weather: {w['regime'].replace('_', ' ')}  ({moves}; average {avg} over 24h)")
    print(WEATHER_TEXT[w["regime"]])
    print(f"Today's rules: liquidity floor ${floor:,.0f}, score bar {rules['min_score']}, "
          f"max {rules['max_watch']} paper trade(s).")
    by = ", ".join(f"{n} via {s}" for s, n in ls["resolved_by"].items()) or "none rescued"
    print(f"Liquidity visibility: {ls['unknown_before']} of {ls['total']} unknown in the main feed -> "
          f"{ls['unknown_after']} still unknown after fallbacks ({by})."
          + (f" {ls['disagreements']} source disagreement(s) resolved to the lower number." if ls["disagreements"] else ""))
    print(f"\n{ls['total']} coins scanned, {data['n_gate']} passed the gate, {data['n_cands']} get the full spot "
          f"check (this can take a minute - the free APIs need pauses)...")


def print_scan(data):
    results = data["results"]
    print(f"\n{'SYMBOL':<10}{'VERDICT':<13}{'SCORE':<7}{'N M C T V':<11}{'LIQ':<8}what to know")
    for r in results:
        s = r["scores"]
        letters = " ".join(str(s[k]) for k in ("narrative", "meme", "community", "timing", "value"))
        print(f"{(r['p']['baseToken']['symbol'] or '?')[:9]:<10}{r['verdict']:<13}{r['total']:<7}{letters:<11}"
              f"{fmt_usd(liquidity_of(r['p'])):<8}{r['rec'][:100]}")
    print_calm_report(data)
    top = next((r for r in results if r["verdict"] == "WATCH"), None)
    if top:
        print(f"\nBest survivor: {top['p']['baseToken']['symbol']} (score {top['total']}). Mint: {top['mint']}")
        print(f"Paper trade logged to {fp(PAPER_FILE)}. Run with --recheck to see how it did.")
    print("WATCH is not SAFE. Paper trade first, and only ever risk money you can lose.")
    print(f"Shadow log: {data['new_logged']} new coin(s) added ({data['shadow_total']} total). "
          f"After a few days, run --report.")
    t = data.get("timings") or {}
    if t:
        print(f"Run time {t.get('total', 0):.0f}s (feeds {t.get('feeds', 0):.0f}s, liquidity {t.get('liquidity', 0):.0f}s, "
              f"deep checks {t.get('deep_checks', 0):.0f}s, logging {t.get('logging', 0):.0f}s). "
              f"API calls {data['api']['calls']}, rate-limited {data['api']['rate_limited']}, "
              f"cache hits {data.get('cache_hits', 0)}"
              + (f", {data['timed_out']} deep check(s) cut by the time budget" if data.get("timed_out") else "") + ".")


def write_scan_log(results, weather):
    path = fp(LOG_FILE)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["checked_at", "weather", "symbol", "address", "source", "liq_src", "verdict", "reasons",
                        "warnings", "narrative", "meme", "community", "timing", "value", "total"])
        now = now_iso()
        for r in results:
            s = r["scores"]
            w.writerow([now, weather["regime"], r["p"]["baseToken"]["symbol"], r["mint"],
                        r["p"].get("_source", ""), r["p"].get("_liq_src", ""), r["verdict"],
                        "; ".join(r["fails"]), "; ".join(r["warns"]),
                        s["narrative"], s["meme"], s["community"], s["timing"], s["value"], r["total"]])


# ======================= offline self-test =======================
def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS  " if cond else "FAIL  ") + name)
        ok = ok and cond

    # exit simulation
    check("stop hit at 2nd snapshot", abs(simulate_exit(1.0, [(1, 0.9), (6, 0.6), (24, 0.5)], 2) - (-42)) < 1e-9)
    check("half sold at 2x then closes at 24h",
          abs(simulate_exit(1.0, [(1, 1.0), (6, 2.2), (24, 1.0)], 2) - (0.5 * 120 + 0 - 3)) < 1e-9)
    check("dead = -100 minus costs", abs(simulate_exit(1.0, [(24, 0.0)], 2) - (-102)) < 1e-9)
    check("no data -> None", simulate_exit(1.0, [(1, None)], 2) is None)

    # spearman
    check("spearman perfect +", abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1) < 1e-9)
    check("spearman perfect -", abs(spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1) < 1e-9)
    check("spearman handles ties", spearman([1, 1, 2, 3], [1, 2, 2, 3]) is not None)

    # exit price semantics
    check("None info = dead", exit_price(None) == 0.0)
    check("pulled liquidity = dead", exit_price({"price": 1.0, "liq": 50}) == 0.0)
    check("healthy price passes", exit_price({"price": 1.0, "liq": 9000}) == 1.0)

    # clone detection
    pairs, _ = fetch_demo()
    g = duplicate_groups(pairs)
    pep = [p for p in pairs if p["baseToken"]["symbol"] == "PEPPER"]
    weak = min(pep, key=lambda p: liquidity_of(p))
    strong = max(pep, key=lambda p: liquidity_of(p))
    ok_w, f_w, _ = safety_gate(weak, 15_000, {"peers": clone_peers(weak, g)})
    ok_s, f_s, w_s = safety_gate(strong, 15_000, {"peers": clone_peers(strong, g)})
    check("weaker clone rejected", (not ok_w) and any("clone" in x for x in f_w))
    check("original only warned", ok_s and any("share the name" in x for x in w_s))

    # resolver with mocked fetchers
    pairs, _ = fetch_demo()
    jup = demo_jupiter([p["baseToken"]["address"] for p in pairs])
    st = resolve_liquidity(pairs, jup, fetchers={})
    byname = {p["baseToken"]["symbol"]: p for p in pairs}
    check("Jupiter rescues ROOK", liquidity_of(byname["ROOK"]) == 47_000)
    check("MOTH stays blind", liquidity_of(byname["MOTH"]) is None)
    check("disagreement -> lower used", liquidity_of(byname["CALM"]) == 12_000)
    check("stats count blind correctly", st["unknown_after"] == 1 and st["unknown_before"] == 2)
    mock_calls = []
    pairs, _ = fetch_demo()
    st2 = resolve_liquidity(pairs, {}, fetchers={"mock": lambda m: (mock_calls.append(m) or {m[0]: {"liquidity": 33_000}})})
    check("fallback tier is only asked about unknown coins", len(mock_calls[0]) == 2)
    check("fallback tier fills what it returns", st2["resolved_by"]["mock"] == 1)

    # trade analysis: identical sizes
    rows = [(f"W{i}", "buy", 25.0) for i in range(60)] + [(f"V{i}", "sell", 10.0 + i) for i in range(40)]
    check("uniform-size fingerprint detected", analyse_trades(rows)["uniform_share"] >= 0.55)

    # shadow window logic
    now = datetime.now(timezone.utc)

    def mk(hours_ago, entry="1.0"):
        t = (now - __import__("datetime").timedelta(hours=hours_ago)).isoformat(timespec="minutes")
        return {"mint": f"M{hours_ago}", "first_seen": t, "entry_price": entry, "p1h": "", "p6h": "", "p24h": ""}
    rows = [mk(1.5), mk(7), mk(25), mk(60)]
    prices = {r["mint"]: {"price": 2.0, "liq": 9000} for r in rows}
    update_shadow(rows, prices, now)
    check("1.5h-old fills p1h only", rows[0]["p1h"] != "" and rows[0]["p6h"] == "")
    check("7h-old: p1h too late -> NA, p6h filled", rows[1]["p1h"] == "NA" and rows[1]["p6h"] != "NA" and rows[1]["p6h"] != "")
    check("25h-old: p24h filled", rows[2]["p24h"] not in ("", "NA"))
    check("60h-old: everything NA (no fake readings)", rows[3]["p24h"] == "NA")
    rows2 = [mk(1.5)]
    update_shadow(rows2, {}, now)
    check("failed lookup stays blank for retry", rows2[0]["p1h"] == "")
    dead_rows = [mk(1.2)]
    update_shadow(dead_rows, {dead_rows[0]["mint"]: None}, now)
    check("lookup ok but no pool -> DEAD", dead_rows[0]["p1h"] == "DEAD")

    # report plumbing
    syn = []
    for i in range(40):
        syn.append({"entry_price": "1", "p24h": "DEAD" if i % 2 else "1.5", "verdict": "SKIP" if i % 2 else "WATCH",
                    "categories": "thin liquidity" if i % 2 else "", "narrative": i % 5, "meme": 1, "community": i % 4,
                    "timing": 2, "value": 3, "total": 40 + i % 30, "est_cost_pct": "2", "p1h": "", "p6h": ""})
    a = analyse_shadow(syn)
    check("report: class stats present", set(a["classes"]) == {"blocked by the gate", "survivors (WATCH/BENCH)"})
    check("report: gate-blocked rows were all rugs", a["classes"]["blocked by the gate"]["rugged"] == 100)
    check("report: rho computed with n>=30", a["rho"].get("community") is not None)

    # demo end to end (writes into a temp dir, no network)
    import tempfile
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            data = run_scan(demo=True)
            names = {r["p"]["baseToken"]["symbol"]: r for r in data["results"]}
            check("demo: GHOST rejected by deep check (mint authority)", spot_check(names["GHOST"]["p"], True)[0] == "REJECT")
            check("demo: IBIS rejected (insiders)", names["IBIS"]["verdict"] == "REJECT")
            check("demo: MOTH skipped as blind", names["MOTH"]["verdict"] == "SKIP")
            check("demo: shadow log has every coin once", len(load_csv(fp(SHADOW_FILE))) == len(data["results"]))
            run_scan(demo=True)
            sh = load_csv(fp(SHADOW_FILE))
            check("demo: second run dedupes shadow rows", len(sh) == len(data["results"]) and sh[0]["seen_count"] == "2")
            pp = load_csv(fp(PAPER_FILE))
            check("demo: no duplicate paper trades", len(pp) == len({r["address"] for r in pp}))
        finally:
            os.chdir(old)
            STATE["demo"] = False

    # ---- v1.4.1 efficiency tests ----
    clock = {"t": 0.0}
    slept = []
    lim = Limiter(2.0, clock=lambda: clock["t"], sleep=lambda d: slept.append(d))
    lim.wait(); lim.wait(); lim.wait()
    check("limiter: spaces calls by the interval", slept == [2.0, 4.0])
    clock["t"] = 100.0
    slept.clear(); lim.wait()
    check("limiter: no wait when calls are already spaced", slept == [])
    lim.backoff()
    check("limiter: backs off after a 429", lim.interval == 4.0 and lim.hits == 1)
    now_dt = datetime.now(timezone.utc)
    check("cache: fresh entry", cache_fresh({"at": now_dt.isoformat()}))
    check("cache: stale entry", not cache_fresh({"at": (now_dt - __import__("datetime").timedelta(hours=CACHE_TTL_H + 1)).isoformat()}))
    calls = {"rpc": 0, "rug": 0, "pool": 0}

    def fake(name, value):
        def f(_):
            calls[name] += 1
            return value
        return f
    bad_rpc = {"mint_authority": "DEV", "freeze_authority": None, "top10_pct": 30, "top10_wallets_pct": 10}
    good_rpc = dict(bad_rpc, mint_authority=None)
    rug_ok = {"risks": [], "lp_locked_pct": 100, "mint_authority": None, "freeze_authority": None, "rugged": False,
              "insiders": 0, "creator_in_top": False, "creator_rug_flag": False}
    pool_ok = {"drawdown_pct": 10.0, "trades": analyse_trades([(f"W{i}", "buy", 5.0 + i) for i in range(60)])}
    tp = {"baseToken": {"address": "MINTX"}, "pairAddress": "POOLX"}
    v = spot_check(tp, checks={"rpc": fake("rpc", bad_rpc), "rug": fake("rug", rug_ok), "pool": fake("pool", pool_ok)})
    check("fail-fast: early REJECT skips the slow pool calls", v[0] == "REJECT" and calls["pool"] == 0)
    check("fail-fast: returns a cache entry", v[3] is not None and v[3]["rpc"]["mint_authority"] == "DEV")
    v = spot_check(tp, checks={"rpc": fake("rpc", good_rpc), "rug": fake("rug", rug_ok), "pool": fake("pool", pool_ok)})
    check("clean coin still gets the full pool check", v[0] == "WATCH" and calls["pool"] == 1)
    before = dict(calls)
    cache = {"MINTX": {"at": now_dt.isoformat(), "rpc": good_rpc, "rug": json.loads(json.dumps(rug_ok))}}
    v = spot_check(tp, cache=cache, checks={"rpc": fake("rpc", good_rpc), "rug": fake("rug", rug_ok), "pool": fake("pool", pool_ok)})
    check("cache hit: no RPC/RugCheck calls, same verdict", v[0] == "WATCH" and calls["rpc"] == before["rpc"]
          and calls["rug"] == before["rug"] and v[3] is None)

    import tempfile
    old_dir, old_budget, old_spot = os.getcwd(), MAX_RUN_SECONDS, globals()["spot_check"]
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            globals()["MAX_RUN_SECONDS"] = 0

            def slow(p, demo=False, cache=None, checks=None):
                time.sleep(4)
                return ("WATCH", [], [], None)
            globals()["spot_check"] = slow
            t_start = time.monotonic()
            data = run_scan(demo=True)
            took = time.monotonic() - t_start
            cut = [r for r in data["results"] if "time budget" in r["rec"]]
            check("time budget: run stops waiting and marks coins UNCHECKED", data["timed_out"] > 0 and cut and took < 4)
            check("timings recorded", set(data["timings"]) >= {"feeds", "liquidity", "deep_checks", "logging", "total"})
        finally:
            globals()["MAX_RUN_SECONDS"], globals()["spot_check"] = old_budget, old_spot
            os.chdir(old_dir)
            STATE["demo"] = False
    # ---- v1.4.2 tests (the 4-agent review fixes) ----
    check("v142: WATCH_LOGGED is a survivor", verdict_class("WATCH_LOGGED") == SURVIVORS)
    check("v142: UNVERIFIED is not a survivor", verdict_class("UNVERIFIED") != SURVIVORS)
    check("v142: blocked first, WATCH later -> own group", verdict_class("SKIP", "WATCH") == PASSED_LATER)
    t10, w10 = concentration([(1.0, True)] * 20, 100.0)
    check("v142: 20 holders x 1% of supply -> top-10 = 10% (v1.4.1 said 50%)", abs(w10 - 10) < 1e-9 and abs(t10 - 10) < 1e-9)
    t10, w10 = concentration([(60.0, False)] + [(2.0, True)] * 19, 100.0)
    check("v142: pool/curve account excluded from wallet top-10", abs(w10 - 20) < 1e-9 and abs(t10 - 78) < 1e-9)
    check("v142: no supply -> unreadable", concentration([(1.0, True)], 0) == (None, None))
    f = token2022_flags([{"extension": "permanentDelegate", "state": {"delegate": "DEV"}},
                         {"extension": "transferFeeConfig", "state": {"newerTransferFee": {"transferFeeBasisPoints": 1500},
                                                                      "olderTransferFee": {"transferFeeBasisPoints": 0},
                                                                      "transferFeeConfigAuthority": "DEV"}}])
    check("v142: Token-2022 flags read", "permanent_delegate" in f and f["transfer_fee_bps"] == 1500 and "fee_changeable" in f)
    ok_rpc = {"mint_authority": None, "freeze_authority": None, "top10_wallets_pct": 12, "t22": {}}
    rug0 = {"risks": [], "lp_locked_pct": 100, "rugged": False, "insiders": 0, "creator_in_top": False,
            "creator_rug_flag": False}
    pool0 = {"drawdown_pct": 10.0, "trades": analyse_trades([(f"W{i}", "buy", 5.0 + i) for i in range(60)])}
    check("v142: clean coin -> WATCH", judge(ok_rpc, rug0, pool0, {"ok": True, "loss_pct": 3})[0] == "WATCH")
    check("v142: permanent delegate -> REJECT", judge(dict(ok_rpc, t22=f), rug0, pool0)[0] == "REJECT")
    check("v142: no sell route -> REJECT", judge(ok_rpc, rug0, pool0, {"ok": False, "detail": "no route"})[0] == "REJECT")
    check("v142: sell loses 20% -> REJECT", judge(ok_rpc, rug0, pool0, {"ok": True, "loss_pct": 20})[0] == "REJECT")
    check("v142: unreadable holders -> UNVERIFIED", judge(dict(ok_rpc, top10_wallets_pct=None), rug0, pool0)[0] == "UNVERIFIED")
    found = _best_pairs([{"baseToken": {"address": "SOL"}, "quoteToken": {"address": "COIN"}, "priceUsd": "150",
                          "priceNative": "3000", "liquidity": {"usd": 9000}}], {"COIN"})
    check("v142: coin found as the QUOTE token, price derived", abs(found["COIN"]["price"] - 0.05) < 1e-12)
    calls1 = []

    def fake_single(a):
        calls1.append(a)
        return [{"baseToken": {"address": a}, "priceUsd": "1", "liquidity": {"usd": 5000}}] if a == "LATE" else []
    old_get = globals()["get_json"]
    try:
        globals()["get_json"] = lambda url, headers=None, retry_429=True: {"pairs": []}
        got = fetch_prices(["LATE", "GONE"], single=fake_single)
    finally:
        globals()["get_json"] = old_get
    check("v142: missing from batch -> own lookup before DEAD", got["LATE"]["price"] == 1.0 and got["GONE"] is None
          and calls1 == ["LATE", "GONE"])
    now2 = datetime.now(timezone.utc)
    t = (now2 - __import__("datetime").timedelta(hours=30)).isoformat(timespec="minutes")
    rr = [{"mint": "D", "first_seen": t, "entry_price": "1", "p1h": "DEAD", "p6h": "", "p24h": "", "p72h": ""}]
    update_shadow(rr, {}, now2)
    check("v142: DEAD carries forward (6h, 24h dead even with no lookup)", rr[0]["p6h"] == "DEAD" and rr[0]["p24h"] == "DEAD")
    st3 = resolve_liquidity([{"baseToken": {"address": "Z"}, "liquidity": {}}], {"Z": {"liquidity": 0}}, fetchers={})
    check("v142: $0 liquidity is known (thin), not blind", st3["unknown_after"] == 0)
    calls2 = []

    def flaky(m):
        calls2.append(1)
        raise RuntimeError("boom")
    old_get = globals()["get_json"]
    try:
        globals()["get_json"] = lambda url, headers=None, retry_429=True: flaky(url)
        fetch_gecko_tokens([f"M{i}" for i in range(65)])
    finally:
        globals()["get_json"] = old_get
    check("v142: a failed batch doesn't stop the feed (3 batches tried)", len(calls2) == 3)
    check("v142: stop fired at 6h is kept even without 24h",
          simulate_exit_full(1.0, [(1, 1.0), (6, 0.0), (24, None)], 2) == (-102.0, True))
    check("v142: unknown cost -> penalty", plan_cost({"est_cost_pct": ""}) == UNKNOWN_COST_PCT)
    check("v142: thinner exit pool costs more", plan_cost({"est_cost_pct": "2", "l24h": "2000"}) > 2)
    check("v142: wilson range sane", wilson(6, 20)[0] < 30 < wilson(6, 20)[1])
    syn2 = []
    for i in range(60):
        surv = i % 2 == 0
        syn2.append({"entry_price": "1", "p1h": "1.1", "p6h": "1.2", "p24h": ("1.5" if surv else "DEAD"),
                     "verdict": "WATCH" if surv else "SKIP", "categories": "", "est_cost_pct": "2",
                     "narrative": 1, "meme": 1, "community": 1, "timing": 1, "value": 1, "total": 50})
    tv = {rule: st for st, rule, _ in analyse_shadow(syn2)["test"]}
    check("v142: test verdict PASS on a clear synthetic case",
          tv["Survivors lose 70%+ less often than blocked coins"] == "PASS"
          and tv["Survivors' median exit-plan result is positive after costs"] == "PASS")
    tv = {rule: st for st, rule, _ in analyse_shadow(syn2[:10])["test"]}
    check("v142: NOT YET under 20 per group", tv["Survivors lose 70%+ less often than blocked coins"] == "NOT YET")
    rv = _rules_fingerprint()
    old_floor = globals()["BASE_MIN_LIQUIDITY"]
    globals()["BASE_MIN_LIQUIDITY"] = old_floor + 1
    check("v142: changing a rule changes the rules version", _rules_fingerprint() != rv)
    globals()["BASE_MIN_LIQUIDITY"] = old_floor
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            data = run_scan(demo=True)
            sh = load_csv(fp(SHADOW_FILE))
            check("v142: rows stamped with rules_version", all(r["rules_version"] == rv for r in sh))
            check("v142: scan_health row written", len(load_csv(fp(HEALTH_FILE))) == 1)
        finally:
            os.chdir(old_dir)
            STATE["demo"] = False
    # ---- Telegram alert tests (no network) ----
    import io as _io
    import contextlib
    old_env = {k: os.environ.get(k) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
    try:
        for k in old_env:
            os.environ.pop(k, None)
        check("tg: no secrets -> nothing sent, no crash", tg_send("x", opener=lambda *a, **k: 1 / 0) is False)
        os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"] = "123:SECRET", "42"
        seen = {}

        class Resp(_io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(req, timeout=None):
            seen["url"], seen["body"] = req.full_url, json.loads(req.data)
            return Resp(b'{"ok": true}')
        check("tg: sends to the right chat", tg_send("hello", opener=fake_open) and seen["body"]["chat_id"] == "42"
              and seen["url"].endswith("/sendMessage"))

        def boom(req, timeout=None):
            raise urllib.error.URLError("bot123:SECRET unreachable")
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = tg_send("x", opener=boom)
        check("tg: failure doesn't crash and hides the token", res is False and "SECRET" not in buf.getvalue())
        demo_p = fetch_demo()[0][0]
        msg = watch_message({"p": demo_p, "mint": demo_p["baseToken"]["address"], "total": 77,
                             "warns": ["only 40% of liquidity locked"], "cost": est_costs(60_000)},
                            {"regime": "GREEN"})
        check("tg: message has symbol, mint, links and paper warning",
              "DRAIN" in msg and "DEMODRAIN" in msg and "dexscreener.com/solana/POOLDRAIN" in msg
              and "rugcheck.xyz/tokens/DEMODRAIN" in msg and "PAPER TRADE ONLY" in msg)
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            data = run_scan(demo=True)
            check("tg: demo run never sends alerts", data["tg_sent"] == 0 and len(data.get("new_watch", [])) >= 1)
        finally:
            os.chdir(old_dir)
            STATE["demo"] = False
    print("\nALL PASS" if ok else "\nSOME TESTS FAILED")
    return ok


# ======================= main =======================
def main():
    args = sys.argv[1:]
    STATE["demo"] = "--demo" in args
    if "--telegram-setup" in args:
        tg_setup()
        return
    if "--telegram-test" in args:
        ok = tg_send("Nexus Scanner: test alert. If you can read this, WATCH alerts will reach you.")
        print("Test message sent." if ok else "Not sent. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
              "(run --telegram-setup), and that you pressed Start in your bot.")
        return
    if "--selftest" in args:
        sys.exit(0 if selftest() else 1)
    if "--recheck" in args:
        recheck()
        return
    if "--report" in args:
        report(include_all="--all" in args)
        return
    regime = "NEUTRAL"
    for a in args:
        if a.startswith("--weather="):
            regime = a.split("=", 1)[1].upper()
    data = run_scan(STATE["demo"], regime)
    if data is None:
        print("No pairs found. Try again in a minute.")
        return
    print_scan(data)


if __name__ == "__main__":
    main()
