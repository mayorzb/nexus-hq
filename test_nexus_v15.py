"""Offline tests for Nexus v1.5. No network. Run: python -m unittest test_nexus_v15 -v
Each confirmed defect (F01-F07, N1-N3) has a test. Where the old v1.4.2 behaviour can be shown, the test
first shows the old defect, then shows v1.5 behaving correctly."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import concept_scorer_v1_4 as legacy
import nexus_v15 as nx

T0 = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
HERE = os.path.dirname(os.path.abspath(__file__))


def sha(f):
    with open(f, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()


def pair(mint, liq=40_000, age_h=10.0, pool=None, price="1.0", ch1=1.0, sym=None, now=T0):
    return {"chainId": "solana", "_source": "dexscreener", "pairAddress": pool or f"pool_{mint}",
            "baseToken": {"address": mint, "symbol": sym or mint.upper(), "name": mint},
            "liquidity": {"usd": liq} if liq is not None else {}, "marketCap": 500_000, "priceUsd": price,
            "txns": {"h1": {"buys": 10, "sells": 8}}, "priceChange": {"h1": ch1, "h24": 5},
            "volume": {"h24": 100_000}, "pairCreatedAt": (now.timestamp() - age_h * 3600) * 1000, "info": {}}


def passing_checks(_p):
    return {"rpc": lambda m: {"mint_authority": None, "freeze_authority": None, "decimals": 6, "t22": {},
                              "top10_wallets_pct": 12.0, "holders_read": True},
            "rug": lambda m: {"risks": [], "lp_locked_pct": 100, "mint_authority": None, "freeze_authority": None,
                              "rugged": False, "insiders": 0, "creator_in_top": False, "creator_rug_flag": False},
            "sell": lambda m, d, px: {"ok": True, "loss_pct": 2.0, "detail": "ok"},
            "pool": lambda a: {"drawdown_pct": 10.0, "trades": {"n": 0}}}


def candles_up(t0, entry=1.0, step=0.004, n=260):
    """Price rising steadily from entry; 1 candle per minute starting at the paper entry minute."""
    start = int(t0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
    out = []
    for i in range(n):
        px = entry * (1 + step * i)
        out.append((start + 60 * i, px, px * 1.001, px * 0.999, px))
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_dir = nx.DATA_DIR
        nx.DATA_DIR = os.path.join(self.tmp, "data_v15")
        self.sent = []

    def tearDown(self):
        nx.DATA_DIR = self.old_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sender(self, text):
        self.sent.append(text)
        return True

    def run_scan(self, pairs, now=T0, weather="NEUTRAL", getter=None, dead=None):
        deps = {"gather": lambda: (pairs, {}), "weather": lambda: weather, "deep_checks": passing_checks,
                "candles_getter": getter or (lambda url: {"data": {"attributes": {"ohlcv_list": []}}}),
                "dead_lookup": dead or (lambda r, d, t: False)}
        return nx.run(now=now, deps=deps, sender=self.sender)


class TestDefects(Base):
    def test_F01_unverified_is_never_a_candidate(self):
        deep = ("UNVERIFIED", [], ["holder concentration unreadable"], [])
        self.assertEqual(nx.decide([], [], deep)[0], "UNVERIFIED")
        self.assertEqual(nx.decide([], ["age unknown"], ("WATCH", [], [], []))[0], "UNVERIFIED")

    def test_F02_failed_lookup_is_retried_not_a_loss(self):
        old_get = legacy.get_json
        try:   # old behaviour: a coin missing from a reply becomes price 0.0 = DEAD = -100%
            legacy.get_json = lambda url: {"pairs": []}
            prices = legacy.fetch_prices(["abc"], single=lambda a: [])
            self.assertEqual(legacy.exit_price(prices["abc"]), 0.0)
        finally:
            legacy.get_json = old_get
        self.assertIsNone(nx.pool_liquidity("p", getter=lambda url: {"pairs": []}))
        self.run_scan([pair("aaa")])
        def boom(url):
            raise OSError("network down")
        n = nx.label_pending(T0 + timedelta(hours=5), getter=boom, dead_lookup=lambda r, d, t: False)
        rows = nx.load_rows(nx.LABELS)
        self.assertEqual(n, 0)
        self.assertTrue(all(r["status"] == "pending" and r["attempts"] == "1" for r in rows))

    def test_F03_label_written_once_never_repriced(self):
        self.run_scan([pair("aaa")])
        up = lambda url: {"data": {"attributes": {"ohlcv_list": [list(c) + [1] for c in candles_up(T0)]}}}
        nx.label_pending(T0 + timedelta(hours=5), getter=up, dead_lookup=lambda r, d, t: False)
        first = {(r["sighting_id"], r["horizon_min"]): r["net_pct"] for r in nx.load_rows(nx.LABELS)}
        crash = lambda url: {"data": {"attributes": {"ohlcv_list": [[c[0], .01, .01, .01, .01, 1] for c in candles_up(T0)]}}}
        nx.label_pending(T0 + timedelta(hours=30), getter=crash, dead_lookup=lambda r, d, t: False)
        again = {(r["sighting_id"], r["horizon_min"]): r["net_pct"] for r in nx.load_rows(nx.LABELS)}
        self.assertEqual(first, again)
        self.assertTrue(all(v != "" for v in again.values()))

    def test_F04_one_total_loss_convention(self):
        self.assertAlmostEqual(-99.5 - 1.6, -101.1)          # old paper formula: gross - cost, below -100
        self.assertEqual(nx.net_return(-99.5, 1.6), -100.0)
        self.assertEqual(nx.net_return(10.0, 2.5), 7.5)
        rug = [(int(T0.timestamp()) + 120, 1, 1, 1, 1), (int(T0.timestamp()) + 180, 1, 1, 0.05, 0.05)]
        self.assertEqual(nx.label_from_candles(rug, T0.timestamp(), 60, 40, -25, 2.0)["net"], -100.0)

    def test_F05_scan_gap_is_reported(self):
        self.run_scan([pair("aaa")], now=T0)
        self.sent.clear()
        self.run_scan([pair("bbb")], now=T0 + timedelta(hours=3))
        self.assertTrue(any("scans stopped for 3.0h" in m for m in self.sent))
        self.assertEqual(nx.load_rows(nx.SCANS)[-1]["gap_min_before"], "180")

    def test_F06_verdict_recorded_as_of_each_sighting(self):
        self.run_scan([pair("aaa", age_h=1.0)], now=T0)                         # too young -> REJECT
        self.run_scan([pair("aaa", age_h=4.0)], now=T0 + timedelta(hours=3))    # mature -> CANDIDATE
        rows = [r for r in nx.load_rows(nx.SIGHTINGS) if r["mint"] == "aaa"]
        self.assertEqual([r["decision"] for r in rows], ["REJECT", "CANDIDATE"])
        labels = nx.load_rows(nx.LABELS)
        self.assertEqual({r["decision"] for r in labels}, {"REJECT", "CANDIDATE"})

    def test_F07_one_low_reading_is_not_death(self):
        dead = {}
        self.assertFalse(nx.dead_check(dead, "p", 100, T0))
        self.assertFalse(nx.dead_check(dead, "p", 50_000, T0 + timedelta(minutes=40)))   # recovered -> reset
        self.assertFalse(nx.dead_check(dead, "p", 100, T0 + timedelta(minutes=60)))
        self.assertFalse(nx.dead_check(dead, "p", 100, T0 + timedelta(minutes=70)))       # only 10 min apart
        self.assertTrue(nx.dead_check(dead, "p", 100, T0 + timedelta(minutes=95)))        # confirmed

    def test_N1_save_step_saves_other_files_when_one_is_missing(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        run = lambda *a: subprocess.run(a, cwd=repo, capture_output=True, text=True)
        run("git", "init", "-q"); run("git", "config", "user.email", "t@t"); run("git", "config", "user.name", "t")
        open(os.path.join(repo, "a.csv"), "w").write("x\n")
        run("git", "add", "a.csv"); run("git", "commit", "-qm", "init")
        open(os.path.join(repo, "a.csv"), "a").write("y\n")
        open(os.path.join(repo, "b.csv"), "w").write("z\n")
        old = run("bash", "-c", "git add -f a.csv missing.csv b.csv 2>/dev/null || true; git diff --cached --name-only")
        self.assertEqual(old.stdout.strip(), "")                                        # the old defect
        new = subprocess.run(["bash", os.path.join(HERE, "scripts", "save_logs.sh"), "test", "a.csv", "missing.csv",
                              "b.csv"], cwd=repo, capture_output=True, text=True, env={**os.environ, "NEXUS_NO_PUSH": "1"})
        self.assertEqual(new.returncode, 0, new.stdout + new.stderr)
        files = run("git", "show", "--name-only", "--format=", "HEAD").stdout.split()
        self.assertEqual(sorted(files), ["a.csv", "b.csv"])

    def test_N2_zero_liquidity_is_unknown_not_dead(self):
        self.assertEqual(legacy.exit_price({"price": 1.0, "liq": 0.0}), 0.0)               # old: 0 -> DEAD
        self.assertEqual(legacy.exit_price({"price": 1.0, "liq": None}), 1.0)              # old: None -> alive
        self.assertIsNone(nx.liquidity_known(pair("z", liq=0)))
        self.assertIsNone(nx.liquidity_known(pair("z", liq=None)))
        self.assertFalse(nx.dead_check({}, "p", None, T0))
        self.run_scan([pair("zzz", liq=0)])
        self.assertEqual(nx.load_rows(nx.SIGHTINGS)[0]["decision"], "UNVERIFIED")

    def test_N3_pool_is_pinned(self):
        self.run_scan([pair("aaa", pool="POOL_A")], now=T0)
        self.run_scan([pair("aaa", pool="POOL_B", age_h=12)], now=T0 + timedelta(hours=1))
        self.assertEqual({r["pool"] for r in nx.load_rows(nx.SIGHTINGS)}, {"POOL_A"})
        self.assertEqual({r["pool"] for r in nx.load_rows(nx.LABELS)}, {"POOL_A"})


class TestLabeller(Base):
    def t(self):
        return T0.timestamp()

    def test_take_profit(self):
        r = nx.label_from_candles(candles_up(T0, step=0.01), self.t(), 60, 40, -25, 2.0)
        self.assertEqual(r["reason"], "take_profit")
        self.assertAlmostEqual(r["gross"], 40.0, places=6)
        self.assertAlmostEqual(r["net"], 38.0, places=6)

    def test_stop_fills_at_candle_low_and_beats_take_profit_in_same_candle(self):
        s = int(self.t()) + 120
        cs = [(s, 1, 1.0, 1.0, 1.0), (s + 60, 1, 1.5, 0.6, 1.2)]
        r = nx.label_from_candles(cs, self.t(), 60, 40, -25, 2.0)
        self.assertEqual(r["reason"], "stop")
        self.assertAlmostEqual(r["gross"], -40.0)

    def test_entry_is_pessimistic_high(self):
        s = int(self.t()) + 120
        cs = [(s, 1.0, 1.1, 0.95, 1.0)] + [(s + 60 * i, 1.0, 1.0, 0.99, 1.0) for i in range(1, 6)]
        r = nx.label_from_candles(cs, self.t(), 5, 10, -8, 0.0)
        self.assertAlmostEqual(r["entry"], 1.1)
        self.assertLess(r["gross"], 0)

    def test_no_data_is_unknown(self):
        self.assertIsNone(nx.label_from_candles([], self.t(), 60, 40, -25, 2.0))
        late = [(int(self.t()) + 120 + 20 * 60, 1, 1, 1, 1)]          # first trade 20 min after planned entry
        self.assertIsNone(nx.label_from_candles(late, self.t(), 60, 40, -25, 2.0))

    def test_unknown_after_give_up_is_not_a_loss(self):
        self.run_scan([pair("aaa")])
        nx.label_pending(T0 + timedelta(hours=80), getter=lambda u: {"data": {"attributes": {"ohlcv_list": []}}},
                         dead_lookup=lambda r, d, t: False)
        rows = nx.load_rows(nx.LABELS)
        self.assertTrue(all(r["status"] == "unknown" and r["net_pct"] == "" for r in rows))


class TestLaunchChecks(Base):
    def test_risk_first_decisions(self):
        pairs = [pair("good", liq=60_000, age_h=8), pair("young", age_h=1), pair("thin", liq=5_000),
                 pair("crash", ch1=-60)]
        self.run_scan(pairs)
        d = {r["mint"]: r["decision"] for r in nx.load_rows(nx.SIGHTINGS)}
        self.assertEqual(d, {"good": "CANDIDATE", "young": "REJECT", "thin": "REJECT", "crash": "REJECT"})

    def test_market_regime_abstains(self):
        self.run_scan([pair("good")], weather="RED")
        self.assertEqual(nx.load_rows(nx.SIGHTINGS)[0]["decision"], "REJECT")
        self.assertFalse(any("PAPER CANDIDATE" in m for m in self.sent))

    def test_signal_has_required_fields_and_no_invented_probability(self):
        self.run_scan([pair("good", sym="GOOD")])
        sig = [m for m in self.sent if "PAPER CANDIDATE" in m]
        self.assertEqual(len(sig), 1)
        for field in ("GOOD", "Time: 2026-10-31T20:00:00+00:00", "Risk:", "Horizons tracked", "Probability: not validated",
                      "Why:", "Mint: good", "PAPER ONLY"):
            self.assertIn(field, sig[0])
        prob_line = [l for l in sig[0].splitlines() if l.startswith("Probability")][0]
        self.assertNotRegex(prob_line, r"\d+(\.\d+)?%")

    def test_duplicate_alerts_suppressed(self):
        self.run_scan([pair("good")], now=T0)
        self.run_scan([pair("good")], now=T0 + timedelta(hours=1))
        self.run_scan([pair("good")], now=T0 + timedelta(hours=25))
        self.assertEqual(sum("PAPER CANDIDATE" in m for m in self.sent), 2)

    def test_summary_errors_and_daily_report_sent(self):
        self.run_scan([pair("good"), pair("thin", liq=5_000)], now=T0)
        self.assertTrue(any(m.startswith("Nexus v1.5.0 scan 20:00 UTC: 2 tokens") for m in self.sent))
        self.assertTrue(any("daily paper report" in m for m in self.sent))
        self.sent.clear()
        nx.run(now=T0 + timedelta(hours=1), sender=self.sender,
               deps={"gather": lambda: (_ for _ in ()).throw(RuntimeError("feed down")), "weather": lambda: "NEUTRAL",
                     "dead_lookup": lambda r, d, t: False})
        self.assertTrue(any("ERROR: feeds failed: feed down" in m for m in self.sent))
        self.assertEqual(sum("daily paper report" in m for m in self.sent), 0)       # once per day only

    def test_baseline_and_legacy_recorded_on_same_coins(self):
        self.run_scan([pair("good"), pair("young", age_h=1)])
        rows = nx.load_rows(nx.LABELS)
        self.assertEqual({r["mint"] for r in rows}, {"good", "young"})              # both labelled as B0 cohort
        self.assertEqual(len(rows), 2 * len(nx.HORIZONS))
        self.assertTrue(all(r["legacy_gate"] in ("0", "1") for r in rows))

    def test_historical_files_preserved(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            for f in ("shadow_log.csv", "paper_trades.csv"):
                open(f, "w").write("old,data\n1,2\n")
            before = {f: sha(f) for f in ("shadow_log.csv", "paper_trades.csv")}
            self.run_scan([pair("good")])
            after = {f: sha(f) for f in before}
            self.assertEqual(before, after)
        finally:
            os.chdir(cwd)

    def test_no_trading_code_anywhere(self):
        forbidden = [r"/swap/v1/swap\b", r"sendTransaction", r"signTransaction", r"Keypair", r"private[_ ]?key",
                     r"secret[_ ]?key", r"mnemonic", r"seed phrase"]
        for f in ("nexus_v15.py", "concept_scorer_v1_4.py"):
            with open(os.path.join(HERE, f)) as fh:
                src = fh.read()
            for pat in forbidden:
                self.assertIsNone(re.search(pat, src, re.I), f"{pat} found in {f}")

    def test_rules_version_is_stable(self):
        self.assertEqual(nx.rules_version(), nx.rules_version())
        self.assertTrue(nx.rules_version().startswith("1.5.0-"))


if __name__ == "__main__":
    unittest.main()


class TestIntegrationOffline(Base):
    """Runs the REAL production path (legacy feeds, liquidity resolver, safety checks, labeller) with the
    network replaced by canned API replies. Anything not canned raises, like an outage would."""

    def test_full_pipeline_with_canned_api(self):
        now = datetime.now(timezone.utc)
        mint, pool = "MintAAAA1111", "PoolAAAA1111"
        created = (now.timestamp() - 6 * 3600) * 1000
        dex_pair = {"chainId": "solana", "pairAddress": pool, "baseToken": {"address": mint, "symbol": "AAA", "name": "Aaa"},
                    "quoteToken": {"address": "So11111111111111111111111111111111111111112"},
                    "liquidity": {"usd": 80_000}, "marketCap": 900_000, "priceUsd": "0.01", "priceNative": "0.0001",
                    "txns": {"h1": {"buys": 30, "sells": 25}}, "priceChange": {"h1": 2, "h24": 10},
                    "volume": {"h24": 200_000}, "pairCreatedAt": created}
        calls = []

        def fake_get(url, headers=None, retry_429=True):
            calls.append(url)
            if "token-profiles/latest" in url:
                return [{"chainId": "solana", "tokenAddress": mint}]
            if "new_pools" in url or "trending_pools" in url:
                return {"data": []}
            if "/latest/dex/tokens/" in url:
                return {"pairs": [dex_pair]}
            raise OSError("canned outage: " + url.split("?")[0][:60])

        def fake_rpc(method, params, retry_429=True):
            raise OSError("canned RPC outage")

        old = (legacy.get_json, legacy.rpc)
        legacy.get_json, legacy.rpc = fake_get, fake_rpc
        try:
            scan = nx.run(now=now, sender=self.sender)
        finally:
            legacy.get_json, legacy.rpc = old
        self.assertEqual(scan["n_tokens"], 1)
        self.assertEqual(scan["n_liquid"], 1)
        row = nx.load_rows(nx.SIGHTINGS)[0]
        self.assertEqual(row["decision"], "UNVERIFIED")          # outage -> unknown -> no signal, not a pass
        self.assertEqual(row["pool"], pool)
        self.assertFalse(any("PAPER CANDIDATE" in m for m in self.sent))
        self.assertEqual(len(nx.load_rows(nx.LABELS)), len(nx.HORIZONS))
        self.assertTrue(any("/latest/dex/tokens/" in c for c in calls))
