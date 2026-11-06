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
        self.assertTrue(any(m.startswith(f"Nexus v{nx.VERSION} scan 20:00 UTC: 2 tokens") for m in self.sent))
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
        self.assertTrue(nx.rules_version().startswith(nx.VERSION + "-"))


class TestSafetyCanary(Base):
    def test_canary_runs_when_market_blocks_everything_and_changes_no_decision(self):
        pairs = [pair("big", liq=90_000), pair("mid", liq=40_000), pair("small", liq=20_000)]
        self.run_scan(pairs, weather="DEEP_RED")
        rows = nx.load_rows(nx.SIGHTINGS)
        self.assertTrue(all(r["decision"] == "REJECT" for r in rows))
        self.assertTrue(all(r["deep_checked"] == "0" for r in rows))
        scan = nx.load_rows(nx.SCANS)[-1]
        self.assertEqual((scan["canary_n"], scan["canary_unverified"], scan["canary_onchain_err"]), ("2", "0", "0"))
        self.assertEqual(scan["rules"], nx.rules_version())

    def test_canary_counts_onchain_failures(self):
        def broken(_p):
            c = passing_checks(_p)
            c["rpc"] = lambda m: (_ for _ in ()).throw(RuntimeError("rpc down"))
            return c
        deps = {"gather": lambda: ([pair("big", liq=90_000)], {}), "weather": lambda: "RED", "deep_checks": broken,
                "candles_getter": lambda url: {"data": {"attributes": {"ohlcv_list": []}}},
                "dead_lookup": lambda r, d, t: False}
        nx.run(now=T0, deps=deps, sender=self.sender)
        scan = nx.load_rows(nx.SCANS)[-1]
        self.assertEqual((scan["canary_n"], scan["canary_unverified"], scan["canary_onchain_err"]), ("1", "1", "1"))

    def test_no_canary_when_normal_deep_checks_ran(self):
        self.run_scan([pair("good", liq=60_000, age_h=8)])
        self.assertEqual(nx.load_rows(nx.SCANS)[-1]["canary_n"], "0")

    def test_old_scans_file_gets_new_columns_without_misalignment(self):
        os.makedirs(nx.DATA_DIR, exist_ok=True)
        old_cols = nx.SCAN_COLS[:-3]
        with open(os.path.join(nx.DATA_DIR, nx.SCANS), "w") as f:
            f.write(",".join(old_cols) + "\n" + ",".join(["old"] + [""] * (len(old_cols) - 1)) + "\n")
        self.run_scan([pair("big", liq=90_000)], weather="DEEP_RED")
        rows = nx.load_rows(nx.SCANS)
        self.assertEqual(rows[0]["scan_id"], "old")
        self.assertEqual(rows[1]["canary_n"], "1")
        self.assertTrue(all(None not in r for r in rows))


# ---------------------------------------------------------------- Round 1 (5 Nov 2026): defects D1-D8
def fake_rpc(accts, owners, prog="11111111111111111111111111111111", parsed_override=None, progs_override=None):
    """Real-shaped Solana RPC responses (jsonParsed token accounts; owner accounts with dataSlice)."""
    def rpc(method, params=None, **k):
        if method == "getAccountInfo":
            return {"context": {"slot": 1}, "value": {"owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "data": {"parsed": {"info": {"mintAuthority": None, "freezeAuthority": None, "decimals": 6},
                                        "type": "mint"}, "program": "spl-token"}}}
        if method == "getTokenSupply":
            return {"context": {"slot": 1}, "value": {"amount": "100000000", "decimals": 6, "uiAmountString": "100"}}
        if method == "getTokenLargestAccounts":
            return {"context": {"slot": 1}, "value": [{"address": a, "uiAmountString": str(v), "decimals": 6}
                                                       for a, v in accts]}
        if method == "getMultipleAccounts" and params[1]["encoding"] == "jsonParsed":
            if parsed_override is not None:
                return {"context": {"slot": 1}, "value": parsed_override}
            return {"context": {"slot": 1}, "value": [None if o is None else
                    {"data": {"parsed": {"info": {"owner": o}, "type": "account"}}} for o in owners]}
        if progs_override is not None:
            return {"context": {"slot": 1}, "value": None if progs_override == "null" else progs_override}
        return {"context": {"slot": 1}, "value": [{"owner": prog, "lamports": 1} for _ in params[0]]}
    return rpc


class TestRound1Defects(Base):
    def test_sample_size_is_reproducible_from_data(self):
        import nexus_review as rv
        self.run_scan([pair("a", liq=60_000)])
        self.run_scan([pair("b", liq=60_000)], now=T0 + timedelta(minutes=60))
        out = rv.sample_size([nx.DATA_DIR])
        self.assertIn("n = (z[1 - alpha] + z[power])^2", rv.sample_size.__doc__)
        self.assertIn("eligible tokens per day: 24.0", out)                    # 1 new eligible token per hourly scan
        self.assertIn("power 80%", out)

    def setUp(self):
        super().setUp()
        self.old_rpc = legacy.rpc

    def tearDown(self):
        legacy.rpc = self.old_rpc
        super().tearDown()

    def test_D1_missing_owner_data_is_unknown_not_zero_concentration(self):
        legacy.rpc = fake_rpc([(f"A{i}", 9) for i in range(10)], [None] * 10)
        d = legacy.check_rpc("MINT")
        self.assertFalse(d["holders_read"])
        self.assertIsNone(d["top10_wallets_pct"])

    def test_D1_empty_owner_lookup_and_partial_owner_data_are_unknown(self):
        legacy.rpc = fake_rpc([(f"A{i}", 9) for i in range(10)], [], parsed_override=[])
        self.assertFalse(legacy.check_rpc("MINT")["holders_read"])
        legacy.rpc = fake_rpc([(f"A{i}", 9) for i in range(3)], ["w1", None, "w3"])
        self.assertFalse(legacy.check_rpc("MINT")["holders_read"])

    def test_D1_unknown_holders_make_the_coin_unverified_never_a_candidate(self):
        legacy.rpc = fake_rpc([(f"A{i}", 9) for i in range(10)], [None] * 10)
        verdict, _, _ = legacy.judge(legacy.check_rpc("MINT"), {"risks": [], "lp_locked_pct": 100}, {"drawdown_pct": 5})
        self.assertEqual(verdict, "UNVERIFIED")

    def test_D2_accounts_of_one_wallet_are_added_together(self):
        accts = [("W1", 5), ("W2", 5)] + [(f"O{i}", 4) for i in range(10)]
        owners = ["W", "W"] + [f"o{i}" for i in range(10)]
        legacy.rpc = fake_rpc(accts, owners)
        self.assertAlmostEqual(legacy.check_rpc("MINT")["top10_wallets_pct"], 46.0)

    def test_D3_one_candle_cannot_settle_a_short_window(self):
        s = int(T0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
        for h in (5, 15):
            self.assertIsNone(nx.label_from_candles([(s, 1, 1.05, .99, 1)], T0.timestamp(), h, 20, -12, 2))

    def test_D3_thin_trading_with_no_trades_near_the_window_end_is_unknown(self):
        s = int(T0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
        thin = [(s, 1, 1.01, .99, 1), (s + 60, 1, 1.01, .99, 1.01)]          # nothing in the last 13 minutes
        self.assertIsNone(nx.label_from_candles(thin, T0.timestamp(), 15, 20, -12, 2))
        dense = [(s + 60 * i, 1, 1.01, .99, 1.0) for i in range(15)]
        self.assertEqual(nx.label_from_candles(dense, T0.timestamp(), 15, 20, -12, 2)["reason"], "time")

    def test_D4_entry_candle_low_does_not_trigger_the_stop(self):
        s = int(T0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
        cs = [(s, 1.0, 1.0, 0.85, 1.0)] + [(s + 60 * i, 1, 1.01 + .02 * i, .99, 1.0 + .02 * i) for i in range(1, 15)]
        res = nx.label_from_candles(cs, T0.timestamp(), 15, 20, -12, 2)
        self.assertEqual(res["reason"], "take_profit")

    def _pending_label(self, h):
        nx.ensure_files()
        nx.append_rows(nx.LABELS, nx.LABEL_COLS, [{"sighting_id": "s", "mint": "m", "pool": "p", "t0": nx.iso(T0),
                       "horizon_min": h, "status": "pending", "cost_pct": "2", "attempts": "0"}])

    def test_D5_death_seen_after_the_window_is_unknown_not_minus_100(self):
        self._pending_label(5)
        nx.save_json(nx.DEAD_FILE, {"p": {"first_low": nx.iso(T0 + timedelta(hours=9))}})
        nx.label_pending(T0 + timedelta(hours=10), getter=lambda u: {"data": {"attributes": {"ohlcv_list": []}}},
                         dead_lookup=lambda r, d, now: True)
        r = nx.load_rows(nx.LABELS)[0]
        self.assertEqual((r["status"], r["net_pct"]), ("unknown", ""))

    def test_D5_death_inside_the_window_is_still_minus_100(self):
        self._pending_label(240)
        nx.save_json(nx.DEAD_FILE, {"p": {"first_low": nx.iso(T0 + timedelta(hours=1))}})
        nx.label_pending(T0 + timedelta(hours=10), getter=lambda u: {"data": {"attributes": {"ohlcv_list": []}}},
                         dead_lookup=lambda r, d, now: True)
        r = nx.load_rows(nx.LABELS)[0]
        self.assertEqual((r["status"], r["net_pct"], r["exit_reason"]), ("labelled", "-100.0", "rug_confirmed"))

    def test_D1_stage2_missing_owner_program_lookup_is_unknown_not_zero(self):
        """Owners readable, but the second lookup (who owns each owner) returns nothing / nulls / too few."""
        for progs in ([], [None], "null"):
            legacy.rpc = fake_rpc([("A0", 90)], ["holder"], progs_override=progs)
            d = legacy.check_rpc("MINT")
            self.assertFalse(d["holders_read"], progs)
            self.assertIsNone(d["top10_wallets_pct"], progs)
        legacy.rpc = fake_rpc([("A0", 90)], ["holder"])                         # readable: 90% is reported
        self.assertAlmostEqual(legacy.check_rpc("MINT")["top10_wallets_pct"], 90.0)

    def _flat(self, n=61):
        s = int(T0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
        return s, [(s + 60 * i, 1.0, 1.01, 0.99, 1.0) for i in range(n)]

    def test_D8_bad_price_prints_are_unreliable_not_wins(self):
        s, flat = self._flat()
        cases = {"wick_high": {10: (s + 600, 1.0, 50.0, 0.99, 1.0)},
                 "wick_low": {10: (s + 600, 1.0, 1.01, 0.01, 1.0)},
                 "jump_transient": {10: (s + 600, 1.0, 30.0, 1.0, 30.0)},          # up 30x, back next minute
                 "invalid": {10: (s + 600, 1.0, 1.01, 0.0, 1.0)}}
        for code, patch in cases.items():
            cs = [patch.get(i, c) for i, c in enumerate(flat)]
            self.assertEqual(nx.label_from_candles(cs, T0.timestamp(), 60, 40, -25, 2).get("unreliable"), code, code)
        up = flat[:10] + [(s + 60 * i, 20.0, 20.2, 19.8, 20.0) for i in range(10, 61)]          # stays 20x higher
        self.assertEqual(nx.label_from_candles(up, T0.timestamp(), 60, 40, -25, 2)["unreliable"], "jump_up")
        down_glitch = flat[:10] + [(s + 600, 1.0, 1.0, 0.05, 0.05)] + flat[11:]                  # 20x down, back
        self.assertEqual(nx.label_from_candles(down_glitch, T0.timestamp(), 60, 40, -25, 2)["unreliable"],
                         "jump_transient")

    def test_D8_persistent_crash_is_a_valid_rug_and_rules_are_frozen(self):
        s, flat = self._flat()
        crash = flat[:10] + [(s + 600, 1.0, 1.0, 0.05, 0.05)] + [(s + 60 * i, .05, .05, .05, .05) for i in range(11, 61)]
        self.assertEqual(nx.label_from_candles(crash, T0.timestamp(), 60, 40, -25, 2)["reason"], "rug")
        self.assertEqual((nx.PRICE_CHECK_VERSION, nx.PRICE_WICK_MAX, nx.PRICE_JUMP_MAX, nx.PRICE_REVERT),
                         ("price-1", 5.0, 10.0, 2.0))
        self.assertEqual(nx.MEASUREMENT_VERSION, "label-1.5.3+price-1")

    def test_D8_no_checks_mode_scores_raw_prices_for_sensitivity(self):
        s, flat = self._flat()
        cs = [(s + 600, 1.0, 50.0, 0.99, 1.0) if i == 10 else c for i, c in enumerate(flat)]
        self.assertEqual(nx.label_from_candles(cs, T0.timestamp(), 60, 40, -25, 2, checks=None)["reason"], "take_profit")

    def test_D8_unreliable_label_is_recorded_and_never_counted(self):
        self._pending_label(60)
        s = int(T0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
        rows = [[s + 60 * i, 1, 1.01, .99, 1, 5] for i in range(61)]
        rows[5] = [s + 300, 1, 60, .99, 1, 5]
        nx.label_pending(T0 + timedelta(hours=5), getter=lambda u: {"data": {"attributes": {"ohlcv_list": rows}}})
        r = nx.load_rows(nx.LABELS)[0]
        self.assertEqual((r["status"], r["net_pct"], r["exit_reason"]), ("unreliable", "", "unreliable:wick_high"))
        import nexus_review as rv
        g = rv.group_stats([r])
        self.assertEqual((g["n"], g["unknown"]), (0, 1))
        import glob, gzip, json
        files = glob.glob(nx.path(os.path.join("candles", "*.jsonl.gz")))
        self.assertEqual(len(files), 1)                                         # raw candles archived
        with gzip.open(files[0], "rt") as fh:
            self.assertEqual(len(json.loads(fh.readline())["candles"]), 61)

    def test_sensitivity_and_exclusion_tables_cover_every_group(self):
        self._pending_label(60)
        s = int(T0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
        rows = [[s + 60 * i, 1, 1.01, .99, 1, 5] for i in range(61)]
        rows[5] = [s + 300, 1, 60, .99, 1, 5]
        nx.label_pending(T0 + timedelta(hours=5), getter=lambda u: {"data": {"attributes": {"ohlcv_list": rows}}})
        import nexus_review as rv
        out = rv.sensitivity([nx.DATA_DIR])
        for setting in ("strict 3x / 5x", "FROZEN 5x / 10x", "loose 10x / 20x", "no price checks"):
            self.assertIn(setting, out)
        wk = rv.weekly([nx.DATA_DIR], T0 + timedelta(hours=6))
        self.assertIn("Excluded as UNRELIABLE at 60 minutes, by reason", wk)

    def test_api_shapes_real_geckoterminal_rows_and_empty_pool_reply(self):
        rows = [[1800000120, "1.0", "1.1", "0.9", "1.05", "1234.5"]]            # 6 fields, numbers as strings
        got = nx.fetch_candles("P", 1800000000, getter=lambda u: {"data": {"attributes": {"ohlcv_list": rows}}})
        self.assertEqual(got, [(1800000120, 1.0, 1.1, 0.9, 1.05)])
        self.assertEqual(nx.fetch_candles("P", 0, getter=lambda u: {"errors": [{"status": "404"}]}), [])
        self.assertIsNone(nx.pool_liquidity("P", getter=lambda u: {"schemaVersion": "1.0.0", "pairs": None}))

    def test_interrupted_write_by_old_writer_is_removed_logged_and_next_row_is_clean(self):
        nx.ensure_files()
        with open(nx.path(nx.SCANS), "a") as f:
            f.write("20261105T000000,2026-11-05T00:00:00+00:00,2026-11-")       # cut off part-way
        nx.append_rows(nx.SCANS, nx.SCAN_COLS, [{"scan_id": "next", "n_tokens": 5}])
        self.assertEqual([r["scan_id"] for r in nx.load_rows(nx.SCANS)], ["next"])
        self.assertIn("removed torn line: 20261105T000000", open(nx.path(nx.TORN_LOG)).read())

    def test_append_interrupted_before_swap_leaves_the_file_untouched(self):
        nx.ensure_files()
        nx.append_rows(nx.SCANS, nx.SCAN_COLS, [{"scan_id": "a", "n_tokens": 1}])
        before = open(nx.path(nx.SCANS)).read()
        real = os.replace
        try:
            os.replace = lambda *a: (_ for _ in ()).throw(KeyboardInterrupt())
            with self.assertRaises(KeyboardInterrupt):
                nx.append_rows(nx.SCANS, nx.SCAN_COLS, [{"scan_id": "b", "n_tokens": 1}])
        finally:
            os.replace = real
        self.assertEqual(open(nx.path(nx.SCANS)).read(), before)

    def test_rows_written_before_a_column_existed_read_as_blank_not_dropped(self):
        nx.ensure_files()
        with open(nx.path(nx.SCANS), "a") as f:
            f.write("old_short_row,2026-11-05T00:00:00+00:00\n")
        self.assertEqual(nx.load_rows(nx.SCANS)[0]["code_commit"], "")

    def test_scan_records_the_code_commit(self):
        os.environ["NEXUS_CODE_COMMIT"] = "abc123def4567890"
        try:
            self.run_scan([pair("good")])
        finally:
            del os.environ["NEXUS_CODE_COMMIT"]
        self.assertEqual(nx.load_rows(nx.SCANS)[-1]["code_commit"], "abc123def456")

    def test_D6_failed_scan_exits_non_zero(self):
        old = nx.run
        try:
            nx.run = lambda: {"errors": "feeds failed: timeout", "n_tokens": 0}
            with self.assertRaises(SystemExit) as e:
                import sys
                argv, sys.argv = sys.argv, ["nexus_v15.py"]
                try:
                    nx.main()
                finally:
                    sys.argv = argv
            self.assertEqual(e.exception.code, 1)
        finally:
            nx.run = old

    def _session(self, scan_cmd, save_cmd="true"):
        env = dict(os.environ, NEXUS_SCAN_CMD=scan_cmd, NEXUS_SAVE_CMD=save_cmd, NEXUS_SYNC_CMD="true",
                   NEXUS_SLEEP_CMD="true", NEXUS_REVIEW_CMD="true")
        return subprocess.run(["bash", os.path.join(HERE, "scripts", "run_session.sh"), "2"], env=env, cwd=self.tmp,
                              capture_output=True, text=True)

    def test_D6_workflow_session_turns_red_on_scan_or_save_failure_and_still_runs_every_scan(self):
        ok = self._session("true")
        self.assertEqual(ok.returncode, 0)
        bad_scan = self._session("false")
        self.assertEqual(bad_scan.returncode, 1)
        self.assertIn("scan 2 failed", bad_scan.stdout)                       # second scan still attempted
        self.assertEqual(self._session("true", save_cmd="false").returncode, 1)

    def _orig(self, **kw):
        nx.ensure_files()
        row = {"sighting_id": "s", "mint": "m", "pool": "p", "t0": nx.iso(T0), "horizon_min": 15,
               "status": "labelled", "entry_px": "1.05", "exit_px": "1", "net_pct": "-6.76", "gross_pct": "-4.76",
               "exit_reason": "time", "cost_pct": "2", "attempts": "1"}
        row.update(kw)
        nx.append_rows(nx.LABELS, nx.LABEL_COLS, [row])
        return open(nx.path(nx.LABELS)).read()

    def _git_repo(self):
        repo = tempfile.mkdtemp()
        g = lambda *a: subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      capture_output=True, text=True, check=True).stdout.strip()
        g("init", "-q")
        open(os.path.join(repo, "code.py"), "w").write("v1")
        g("add", "."); g("commit", "-qm", "code")
        code = g("rev-parse", "HEAD")
        os.makedirs(os.path.join(repo, "data_v15"))
        open(os.path.join(repo, "data_v15", "scans.csv"), "w").write("x")
        g("add", "."); g("commit", "-qm", "data")
        return repo, g, code

    def test_session_records_the_code_commit_not_the_latest_data_commit(self):
        repo, g, code = self._git_repo()
        out = os.path.join(repo, "seen.txt")
        scan = os.path.join(repo, "scan.sh")
        open(scan, "w").write(f'echo "$NEXUS_CODE_COMMIT" >> {out}\n')
        env = dict(os.environ, NEXUS_SCAN_CMD=f"bash {scan}", NEXUS_SAVE_CMD="true",
                   NEXUS_SYNC_CMD="true", NEXUS_SLEEP_CMD="true", NEXUS_REVIEW_CMD="true")
        p = subprocess.run(["bash", os.path.join(HERE, "scripts", "run_session.sh"), "2"], cwd=repo, env=env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(open(out).read().split(), [code, code])
        shutil.rmtree(repo, ignore_errors=True)

    def test_session_stops_cleanly_when_code_changes_mid_session(self):
        repo, g, code = self._git_repo()
        out = os.path.join(repo, "seen.txt")
        # the "sync" of scan 2 brings in a code change, as git reset --hard origin/main would
        sync, scan = os.path.join(repo, "sync.sh"), os.path.join(repo, "scan.sh")
        open(sync, "w").write(f"[ -f {out} ] && {{ echo v2 > code.py; git -c user.name=t -c user.email=t@t commit -qam new; }}; true\n")
        open(scan, "w").write(f"echo scan >> {out}\n")
        env = dict(os.environ, NEXUS_SCAN_CMD=f"bash {scan}", NEXUS_SAVE_CMD="true",
                   NEXUS_SYNC_CMD=f"bash {sync}", NEXUS_SLEEP_CMD="true", NEXUS_REVIEW_CMD="true")
        p = subprocess.run(["bash", os.path.join(HERE, "scripts", "run_session.sh"), "3"], cwd=repo, env=env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(open(out).read().split(), ["scan"])                    # scans 2-3 not run on untested code
        self.assertIn("Code on main changed", p.stdout)
        shutil.rmtree(repo, ignore_errors=True)

    # ---------------------------------------------------------------- v1.5.2 (6 Nov 2026)
    def test_v152_shallow_checkout_records_code_commit_not_data_commit(self):
        repo, g, code = self._git_repo()                                        # origin: code commit, then data
        clone = tempfile.mkdtemp()
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + repo, clone], check=True)
        out = os.path.join(clone, "seen.txt")
        scan = os.path.join(clone, "scan.sh")
        open(scan, "w").write(f'echo "$NEXUS_CODE_COMMIT" >> {out}\n')
        env = dict(os.environ, NEXUS_SCAN_CMD=f"bash {scan}", NEXUS_SAVE_CMD="true", NEXUS_SYNC_CMD="true",
                   NEXUS_SLEEP_CMD="true", NEXUS_REVIEW_CMD="true")
        p = subprocess.run(["bash", os.path.join(HERE, "scripts", "run_session.sh"), "1"], cwd=clone, env=env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(open(out).read().split(), [code])                     # not the newer data commit
        shutil.rmtree(repo, ignore_errors=True); shutil.rmtree(clone, ignore_errors=True)

    def test_v152_workflow_fetches_full_history_and_publishes_test_log(self):
        y = open(os.path.join(HERE, ".github", "workflows", "nexus-v15-paper.yml")).read()
        for must in ("fetch-depth: 0", 'NEXUS_TESTS_LOG="$RUNNER_TEMP/tests.log"', 'grep -qx "exit code 0"',
                     "timeout-minutes: 345"):
            self.assertIn(must, y, must)

    def _paced_session(self, last_started_min_ago, n=1):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "data_v15"))
        t = datetime.now(timezone.utc) - timedelta(minutes=last_started_min_ago)
        with open(os.path.join(d, "data_v15", "scans.csv"), "w") as fh:
            fh.write("scan_id,started_at\nx," + t.isoformat() + "\n")
        slept, scan = os.path.join(d, "slept.txt"), os.path.join(d, "scan.sh")
        open(scan, "w").write("python3 -c \"import datetime;print('y,'+datetime.datetime.now(datetime.timezone.utc)"
                              ".isoformat())\" >> data_v15/scans.csv\n")
        sl = os.path.join(d, "sleep.sh")
        open(sl, "w").write(f'echo "$1" >> {slept}\n')
        env = dict(os.environ, NEXUS_SCAN_CMD=f"bash {scan}", NEXUS_SAVE_CMD="true", NEXUS_SYNC_CMD="true",
                   NEXUS_SLEEP_CMD=f"bash {sl}", NEXUS_REVIEW_CMD="true", NEXUS_INTERVAL_S="3600")
        p = subprocess.run(["bash", os.path.join(HERE, "scripts", "run_session.sh"), str(n)], cwd=d, env=env,
                           capture_output=True, text=True)
        waits = [int(x) for x in open(slept).read().split()] if os.path.exists(slept) else []
        shutil.rmtree(d, ignore_errors=True)
        return p, waits

    def test_v152_session_start_waits_for_the_hour_instead_of_scanning_back_to_back(self):
        p, waits = self._paced_session(5)                                      # previous session scanned 5 min ago
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(waits), 1)
        self.assertTrue(3240 <= waits[0] <= 3300, waits)                       # about 55 min

    def test_v152_no_wait_after_a_long_gap_and_hourly_spacing_is_start_to_start(self):
        p, waits = self._paced_session(120, n=2)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(waits), 1)                                        # scan 1 at once, scan 2 waits
        self.assertTrue(3540 <= waits[0] <= 3600, waits)                       # a full hour from scan 1's start

    def test_v152_thin_window_settles_as_unknown_once_finished_not_after_72h(self):
        self._pending_label(15)
        s = int(T0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
        thin = [[s, 1, 1.01, .99, 1, 5], [s + 60, 1, 1.01, .99, 1, 5],      # nothing near the window end...
                [s + 20 * 60, 1, 1.01, .99, 1, 5]]                             # ...but trades after it: data complete
        get = lambda u: {"data": {"attributes": {"ohlcv_list": thin}}}
        nx.label_pending(T0 + timedelta(minutes=40), getter=get, dead_lookup=lambda r, d, n: False)
        self.assertEqual(nx.load_rows(nx.LABELS)[0]["status"], "pending")     # window + 30 min not yet passed
        nx.label_pending(T0 + timedelta(hours=5), getter=get, dead_lookup=lambda r, d, n: False)
        r = nx.load_rows(nx.LABELS)[0]
        self.assertEqual((r["status"], r["net_pct"]), ("unknown", ""))
        self.assertIn("thin trading", r["note"])
        import nexus_review as rv
        self.assertIn("| Labels overdue (> 6h past due) | 0 |", rv.daily([nx.DATA_DIR], T0 + timedelta(hours=12))[0])

    def test_v152_empty_api_reply_is_not_settled_early_but_is_settled_before_overdue(self):
        self._pending_label(240)
        empty = lambda u: {"data": {"attributes": {"ohlcv_list": []}}}
        nx.label_pending(T0 + timedelta(minutes=242 + 60), getter=empty, dead_lookup=lambda r, d, n: False)
        self.assertEqual(nx.load_rows(nx.LABELS)[0]["status"], "pending")     # could be a lagging API: wait
        nx.label_pending(T0 + timedelta(minutes=242 + 4 * 60 + 5), getter=empty, dead_lookup=lambda r, d, n: False)
        self.assertEqual(nx.load_rows(nx.LABELS)[0]["status"], "unknown")     # before the 6h overdue line
        self.assertLess(242 + 4 * 60 + 5, 247 + 6 * 60)

    def test_review14_flags_back_to_back_scans(self):
        import nexus_review as rv
        self.run_scan([pair("a")], now=T0)
        self.run_scan([pair("b")], now=T0 + timedelta(minutes=60))
        self.run_scan([pair("c")], now=T0 + timedelta(minutes=65))            # 5 min after the previous scan
        out, worst = rv.daily([nx.DATA_DIR], T0 + timedelta(minutes=70))
        self.assertIn("| Shortest gap between scans (last 24h) | 5 min (at 21:00 UTC) | ALERT |", out)
        self.assertEqual(worst, "ALERT")

    def test_review14_flags_scans_tagged_with_a_data_only_commit(self):
        import nexus_review as rv
        repo, g, code = self._git_repo()                                       # code commit, then data commit
        data_commit = g("rev-parse", "HEAD")
        d = os.path.join(repo, "data_v15")
        os.remove(os.path.join(d, "scans.csv"))
        old = nx.DATA_DIR
        try:
            nx.DATA_DIR = d
            nx.ensure_files()
            nx.append_rows(nx.SCANS, nx.SCAN_COLS, [
                {"scan_id": "1", "started_at": nx.iso(T0), "version": nx.VERSION, "rules": "r", "code_commit": code},
                {"scan_id": "2", "started_at": nx.iso(T0 + timedelta(minutes=60)), "version": nx.VERSION, "rules": "r",
                 "code_commit": data_commit}])
            out, _ = rv.daily([d], T0 + timedelta(minutes=70))
        finally:
            nx.DATA_DIR = old
        self.assertIn("| Scans tagged with a data-only or missing code commit | 1 of 2 | ALERT |", out)
        shutil.rmtree(repo, ignore_errors=True)

    def test_v152_bounds_report_counts_dead_and_unreliable_as_losses(self):
        nx.ensure_files()
        base = {"mint": "m", "pool": "p", "t0": nx.iso(T0), "horizon_min": 60, "cost_pct": "2", "attempts": "1",
                "b0_liquid": "1", "legacy_gate": "0", "h1_mature": "0", "decision": "REJECT"}
        nx.append_rows(nx.LABELS, nx.LABEL_COLS, [
            dict(base, sighting_id="a", status="labelled", net_pct="10.0"),
            dict(base, sighting_id="b", status="unknown", note="pool dead, first seen x after the window"),
            dict(base, sighting_id="c", status="unreliable", exit_reason="unreliable:jump_up"),
            dict(base, sighting_id="d", status="unknown", note="thin trading")])
        import nexus_review as rv
        line = [l for l in rv.bounds([nx.DATA_DIR]).splitlines() if l.startswith("| B0 liquid baseline | 60 |")][0]
        self.assertEqual(line, "| B0 liquid baseline | 60 | 1 | 2 | 1 | +10.0% | -63.3% | -72.5% | +10.0% |")

    def test_v152_session_writes_reports_and_test_log_and_tolerates_review_failure(self):
        d = tempfile.mkdtemp()
        log = os.path.join(d, "tests.log")
        open(log, "w").write("Tests for commit abc\nOK\nexit code 0\n")
        env = dict(os.environ, NEXUS_SCAN_CMD="true", NEXUS_SAVE_CMD="true", NEXUS_SYNC_CMD="true",
                   NEXUS_SLEEP_CMD="true", NEXUS_REVIEW_CMD="false", NEXUS_TESTS_LOG=log)
        p = subprocess.run(["bash", os.path.join(HERE, "scripts", "run_session.sh"), "1"], cwd=d, env=env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)                 # report failure never fails scans
        self.assertIn("review reports could not be written", p.stdout)
        self.assertIn("exit code 0", open(os.path.join(d, "data_v15", "reports", "tests_latest.txt")).read())
        shutil.rmtree(d, ignore_errors=True)

    def test_relabel_keeps_originals_and_records_every_change(self):
        before = self._orig()
        s = int(T0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
        msg = nx.relabel_corrected(T0 + timedelta(days=1),
                                   getter=lambda u: {"data": {"attributes": {"ohlcv_list": [[s, 1, 1.05, .99, 1, 1]]}}})
        self.assertEqual(open(nx.path(nx.LABELS)).read(), before)
        ch = nx.load_rows(os.path.join("corrected", "changes_v151.csv"))[0]
        self.assertEqual((ch["old_status"], ch["new_status"], ch["old_entry_px"], ch["new_entry_px"]),
                         ("labelled", "unknown", "1.05", ""))
        self.assertEqual(ch["measurement_version"], nx.MEASUREMENT_VERSION)
        self.assertIn("1 changed", msg)

    def test_relabel_logs_changes_to_prices_and_exit_reason_even_when_return_is_equal(self):
        s = int(T0.timestamp()) + nx.ENTRY_DELAY_MIN * 60
        cs = [[s + 60 * i, 1, 1.0, 1.0, 1.0, 1] for i in range(16)]
        res = nx.label_from_candles([tuple(c[:5]) for c in cs], T0.timestamp(), 15, 20, -12, 2)
        self._orig(entry_px="0.99", exit_px="0.99", exit_reason="stop", net_pct=f"{res['net']:.2f}",
                   gross_pct=f"{res['gross']:.2f}")
        nx.relabel_corrected(T0 + timedelta(days=1), getter=lambda u: {"data": {"attributes": {"ohlcv_list": cs}}})
        ch = nx.load_rows(os.path.join("corrected", "changes_v151.csv"))[0]
        self.assertEqual(ch["changed_fields"], "entry_px|exit_px|exit_reason")
        self.assertEqual((ch["old_exit_reason"], ch["new_exit_reason"]), ("stop", "time"))

    def test_relabel_fetch_failure_clears_stale_values_and_keeps_them_in_the_audit(self):
        self._orig()
        nx.relabel_corrected(T0 + timedelta(days=1), getter=lambda u: (_ for _ in ()).throw(OSError("timeout")))
        new = nx.load_rows(os.path.join("corrected", "labels_v151.csv"))[0]
        self.assertEqual([new[k] for k in nx.MONEY_FIELDS], [""] * 5)
        self.assertEqual((new["status"], new["measurement_version"]), ("unknown", nx.MEASUREMENT_VERSION))
        ch = nx.load_rows(os.path.join("corrected", "changes_v151.csv"))[0]
        self.assertEqual((ch["old_net_pct"], ch["old_entry_px"], ch["old_exit_reason"]), ("-6.76", "1.05", "time"))

    def test_D11_workflow_guards_chain_alerts_and_limits(self):
        y = open(os.path.join(HERE, ".github", "workflows", "nexus-v15-paper.yml")).read()
        for must in ("actions: write", "contents: write", "bash scripts/chain.sh guard", "bash scripts/chain.sh next",
                     "steps.tests.outcome == 'success'", "github.ref_name == 'main'", "timeout-minutes: 345",
                     "if: failure() || cancelled()", "api.telegram.org", "cancel-in-progress: false",
                     "REPO_PRIVATE: ${{ github.event.repository.private }}", "NEXUS_CODE_COMMIT: ${{ github.sha }}",
                     "bash scripts/run_session.sh"):
            self.assertIn(must, y, must)
        self.assertNotIn("V15-dev", y.split("jobs:")[0])                       # V15-dev kept, never triggered

    def _chain(self, cmd, runs, private="false", dispatch_rc=0, max_day="6", run_id="100", fail_list=""):
        """runs: one list of runs, or a list of lists = successive answers to 'gh run list' (last one repeats)."""
        bindir = tempfile.mkdtemp()
        log = os.path.join(bindir, "dispatched.log")
        seq_dir = os.path.join(bindir, "seq")
        os.makedirs(seq_dir)
        for i, rs in enumerate(runs if runs and isinstance(runs[0], list) else [runs]):
            open(os.path.join(seq_dir, f"{i}.json"), "w").write(json.dumps(rs))
        with open(os.path.join(bindir, "gh"), "w") as f:
            f.write("""#!/usr/bin/env bash
if [ "$1 $2" = "run list" ]; then
  [ -n "$FAKE_FAIL_LIST" ] && exit 1
  c=$(cat "$FAKE_SEQ/count" 2>/dev/null || echo 0); echo $((c+1)) > "$FAKE_SEQ/count"
  last=$(ls "$FAKE_SEQ"/*.json | wc -l); i=$c; [ "$i" -ge "$last" ] && i=$((last-1))
  q=""; while [ $# -gt 0 ]; do [ "$1" = "--jq" ] && q="$2"; shift; done
  jq -c "$q" < "$FAKE_SEQ/$i.json"; exit 0; fi
if [ "$1 $2" = "workflow run" ]; then echo "$@" >> "$FAKE_LOG"; exit "$FAKE_RC"; fi
exit 9
""")
        os.chmod(os.path.join(bindir, "gh"), 0o755)
        env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"], FAKE_SEQ=seq_dir,
                   FAKE_LOG=log, FAKE_RC=str(dispatch_rc), REPO_PRIVATE=private, GITHUB_RUN_ID=run_id,
                   MAX_SESSIONS_PER_DAY=max_day, GUARD_RECHECKS="3", GUARD_WAIT_S="0", FAKE_FAIL_LIST=fail_list)
        p = subprocess.run(["bash", os.path.join(HERE, "scripts", "chain.sh"), cmd], env=env, capture_output=True, text=True)
        n = len(open(log).read().splitlines()) if os.path.exists(log) else 0
        shutil.rmtree(bindir, ignore_errors=True)
        return p.returncode, n, p.stdout

    def _run(self, i, status, created=None):
        return {"databaseId": i, "status": status,
                "createdAt": created or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def test_chain_dispatches_exactly_once_when_nothing_else_is_active(self):
        rc, n, _ = self._chain("next", [self._run(100, "in_progress")])
        self.assertEqual((rc, n), (0, 1))

    def test_chain_never_duplicates_when_a_session_is_queued_or_running(self):
        for st in ("queued", "in_progress", "waiting", "pending"):
            rc, n, _ = self._chain("next", [self._run(100, "in_progress"), self._run(101, st)])
            self.assertEqual((rc, n), (0, 0), st)

    def test_chain_refuses_private_repo_daily_cap_and_reports_dispatch_failure(self):
        self.assertEqual(self._chain("next", [self._run(100, "in_progress")], private="true")[:2], (4, 0))
        self.assertEqual(self._chain("next", [self._run(100, "in_progress")], private="")[:2], (4, 0))
        today = [self._run(i, "completed") for i in range(90, 96)] + [self._run(100, "in_progress")]
        self.assertEqual(self._chain("next", today)[:2], (5, 0))
        self.assertEqual(self._chain("next", [self._run(100, "in_progress")], dispatch_rc=1)[0], 1)

    def test_guard_never_counts_its_own_run(self):
        self.assertEqual(self._chain("guard", [self._run(100, "in_progress")])[0], 0)
        self.assertEqual(self._chain("guard", [self._run(100, "in_progress"), self._run(101, "queued")])[0], 0)

    def test_guard_waits_out_a_just_finished_run_instead_of_breaking_the_chain(self):
        stale = [self._run(100, "in_progress"), self._run(99, "in_progress")]     # list lags behind reality
        done = [self._run(100, "in_progress"), self._run(99, "completed")]
        self.assertEqual(self._chain("guard", [stale, stale, done])[0], 0)

    def test_guard_skips_only_when_another_run_stays_in_progress(self):
        other = [self._run(100, "in_progress"), self._run(99, "in_progress")]
        rc, _, out = self._chain("guard", [other])
        self.assertEqual(rc, 3)
        self.assertIn("check 3 of 3", out)

    def test_guard_fails_open_when_run_id_missing_or_listing_fails(self):
        both = [self._run(100, "in_progress"), self._run(99, "in_progress")]
        self.assertEqual(self._chain("guard", both, run_id="")[0], 0)
        self.assertEqual(self._chain("guard", both, fail_list="1")[0], 0)

    def test_D7_legacy_workflow_is_retired_no_schedule_no_secrets(self):
        raw = open(os.path.join(HERE, ".github", "workflows", "nexus-scan.yml")).read()
        y = "\n".join(line.split("#")[0] for line in raw.splitlines())          # code only, not comments
        self.assertIn("RETIRED", raw)
        self.assertNotIn("schedule", y)
        self.assertNotIn("secrets.", y)
        self.assertNotIn("git add", y)


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


class TestReview(Base):
    """The monitoring scorecard must be deterministic and must never count unknown outcomes."""

    def make_history(self):
        import random
        rng = random.Random(3)
        def candles(url):
            before = int(url.split("before_timestamp=")[1].split("&")[0])
            start = before - (nx.ENTRY_DELAY_MIN + 250) * 60
            r = random.Random(before)
            drift = r.choice([0.002, -0.004, 0.0, -0.02])
            cs, px = [], 1.0
            for i in range(250):
                px *= 1 + drift + r.uniform(-0.003, 0.003)
                cs.append([start + 60 * i, px, px * 1.002, px * 0.998, px, 1])
            return {"data": {"attributes": {"ohlcv_list": cs}}}
        for h in range(0, 72, 3):
            now = T0 + timedelta(hours=h)
            pairs = [pair(f"m{h}_{i}", liq=rng.choice([20_000, 60_000, 5_000]), age_h=rng.choice([1, 5, 30]))
                     for i in range(4)]
            self.run_scan(pairs, now=now, getter=candles)
        nx.label_pending(T0 + timedelta(hours=80), getter=candles, dead_lookup=lambda r, d, t: False)

    def test_scorecard_deterministic_and_counts(self):
        import nexus_review as rv
        self.make_history()
        now = T0 + timedelta(hours=80)
        a, b = rv.weekly([nx.DATA_DIR], now), rv.weekly([nx.DATA_DIR], now)
        self.assertEqual(a, b)
        self.assertIn("B0 liquid baseline", a)
        labels = nx.load_rows(nx.LABELS)
        n60 = sum(1 for r in labels if r["horizon_min"] == "60" and r["b0_liquid"] == "1" and r["status"] == "labelled")
        self.assertIn(f"| B0 liquid baseline | {n60} |", a)
        d, worst = rv.daily([nx.DATA_DIR], now)
        self.assertIn(worst, ("OK", "WARN", "ALERT"))

    def test_unknown_never_counted_as_loss(self):
        import nexus_review as rv
        rows = [{"status": "unknown", "net_pct": "", "t0": "2026-10-31T00:00:00+00:00"}] * 5 + \
               [{"status": "labelled", "net_pct": "10", "t0": "2026-10-31T00:00:00+00:00"}]
        g = rv.group_stats(rows)
        self.assertEqual((g["n"], g["unknown"], g["wins"]), (1, 5, 1))

    def test_empty_data_does_not_crash(self):
        import nexus_review as rv
        nx.ensure_files()
        self.assertIn("ALERT", rv.daily([nx.DATA_DIR], T0)[0])
        self.assertIn("COLLECTING", rv.weekly([nx.DATA_DIR], T0))


class TestSaveAfterStaleStart(unittest.TestCase):
    """Overnight 31 Oct/1 Nov: run 2 started from an old commit; every save conflicted and was lost.
    sync_data.sh before each scan must make the save succeed."""

    def test_stale_runner_saves_after_sync(self):
        tmp = tempfile.mkdtemp()
        try:
            sh = lambda cwd, *a: subprocess.run(a, cwd=cwd, capture_output=True, text=True)
            remote = os.path.join(tmp, "remote.git")
            sh(tmp, "git", "init", "-q", "--bare", "-b", "dev", remote)
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            sh(tmp, "git", "clone", "-q", remote, a)
            for c in (a,):
                sh(c, "git", "config", "user.email", "t@t"); sh(c, "git", "config", "user.name", "t")
                sh(c, "git", "checkout", "-q", "-b", "dev")
            os.makedirs(os.path.join(a, "data_v15"))
            with open(os.path.join(a, "data_v15", "scans.csv"), "w") as fh:
                fh.write("scan_id\n1\n")
            sh(a, "git", "add", "."); sh(a, "git", "commit", "-qm", "base"); sh(a, "git", "push", "-q", "origin", "dev")
            sh(tmp, "git", "clone", "-q", "-b", "dev", remote, b)                      # runner B starts here (stale soon)
            with open(os.path.join(a, "data_v15", "scans.csv"), "a") as fh:            # runner A saves newer data
                fh.write("2\n")
            sh(a, "git", "commit", "-qam", "newer"); sh(a, "git", "push", "-q", "origin", "dev")
            env = {**os.environ, "GITHUB_REF_NAME": "dev", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            r = subprocess.run(["bash", os.path.join(HERE, "scripts", "sync_data.sh")], cwd=b, env=env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(b, "data_v15", "scans.csv"), "a") as fh:            # B's scan appends
                fh.write("3\n")
            r = subprocess.run(["bash", os.path.join(HERE, "scripts", "save_logs.sh"), "scan", "data_v15"],
                               cwd=b, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            sh(a, "git", "pull", "-q", "origin", "dev")
            with open(os.path.join(a, "data_v15", "scans.csv")) as fh:
                self.assertEqual(fh.read(), "scan_id\n1\n2\n3\n")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestSecrets(Base):
    """1 Nov: a bare Helius key saved as SOLANA_RPC_URL broke every on-chain check, and part of the key
    was written to the public log inside an error message."""

    def setUp(self):
        super().setUp()
        self.env = {k: os.environ.get(k) for k in ("SOLANA_RPC_URL", "TELEGRAM_BOT_TOKEN")}
        self.rpc = legacy.RPC_URL

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        legacy.RPC_URL = self.rpc
        super().tearDown()

    def test_bare_key_becomes_helius_url(self):
        os.environ["SOLANA_RPC_URL"] = "7900aaaa-bbbb-cccc-dddd-eeeeffff0000"
        self.assertEqual(nx.fix_rpc_url(), nx.HELIUS_RPC + "7900aaaa-bbbb-cccc-dddd-eeeeffff0000")

    def test_full_url_left_alone(self):
        os.environ["SOLANA_RPC_URL"] = "https://example-rpc.test/?api-key=SECRET123"
        legacy.RPC_URL = os.environ["SOLANA_RPC_URL"]
        self.assertEqual(nx.fix_rpc_url(), "https://example-rpc.test/?api-key=SECRET123")

    def test_secrets_never_reach_logs(self):
        key = "7900aaaa-bbbb-cccc-dddd-eeeeffff0000"
        os.environ["SOLANA_RPC_URL"] = key
        os.environ["TELEGRAM_BOT_TOKEN"] = "123456:ABCDEF-token"
        msg = nx.redact(f"unknown url type: '{key}' and https://x/?api-key=OTHERKEY9 and 123456:ABCDEF-token")
        for leak in (key, key[:20], "OTHERKEY9", "ABCDEF-token"):
            self.assertNotIn(leak, msg)

    def test_rpc_failure_text_in_saved_log_is_redacted(self):
        key = "7900aaaa-bbbb-cccc-dddd-eeeeffff0000"
        os.environ["SOLANA_RPC_URL"] = key
        def checks(_p):
            c = passing_checks(_p)
            c["rpc"] = lambda m: (_ for _ in ()).throw(ValueError(f"unknown url type: '{key}'"))
            return c
        nx.run(now=T0, sender=self.sender, deps={"gather": lambda: ([pair("good")], {}), "weather": lambda: "NEUTRAL",
                                                 "deep_checks": checks, "dead_lookup": lambda r, d, t: False})
        with open(os.path.join(nx.DATA_DIR, "sightings.csv")) as fh:
            saved = fh.read()
        self.assertNotIn(key[:8], saved)
        self.assertTrue(all(key[:8] not in m for m in self.sent))
