"""Offline tests for nexus_runner.py (Runner Track). Fake candles and fake API answers only: no network.
Run: python -m unittest test_nexus_runner -v
"""
import csv
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import nexus_runner as nr

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
S = T0.timestamp()
STEP = 300


def cd(i, o, h, l, c):
    """Candle i: starts at the candle that contains the entry time (signal + 2 min) plus i*5 min."""
    start = int(S + 120) - (int(S + 120) % STEP)
    return [start + i * STEP, o, h, l, c, 100]


def flat(i, p=1.0):
    return cd(i, p, p, p, p)


def pair(mint="MINT1", mcap=30_000, liq=9_000, h1=10.0, m5buys=30, m5sells=10, created_min=40, pool=None):
    return {"chainId": "solana", "dexId": "pumpswap", "pairAddress": pool or ("POOL" + mint),
            "baseToken": {"address": mint, "symbol": mint[:4]}, "priceUsd": "0.00003", "marketCap": mcap,
            "fdv": mcap, "liquidity": {"usd": liq},
            "txns": {"m5": {"buys": m5buys, "sells": m5sells}, "h1": {"buys": 200, "sells": 150}},
            "volume": {"m5": 2000, "h1": 12000, "h6": 40000}, "priceChange": {"m5": 5, "h1": h1, "h6": 50},
            "pairCreatedAt": (S - created_min * 60) * 1000, "info": {"socials": [{"type": "x"}], "websites": [1]},
            "boosts": {"active": 0}, "_source": "dexscreener"}


PASS = {"verdict": "WATCH", "fails": [], "unknown": [], "warns": [],
        "feat": {"top10_wallets_pct": 18.0, "total_holders": 400.0, "creator_pct": 2.0, "sell_loss_pct": 4.0}}


class Simulate(unittest.TestCase):
    def sim(self, cs, hz=24, cost=5.0, liq=None):
        return nr.simulate(cs, S, hz, cost, liq, 1.0, 30_000)

    def test_stop_before_2x(self):
        r = self.sim([flat(0), cd(1, 1, 1.1, 0.55, 0.6)])
        self.assertEqual(r["exit_reason"], "stop")
        self.assertAlmostEqual(r["gross_pct"], -40)
        self.assertAlmostEqual(r["net_pct"], -45)

    def test_stop_wins_when_same_candle_hits_both(self):
        r = self.sim([flat(0), cd(1, 1, 2.5, 0.5, 1)])
        self.assertEqual(r["exit_reason"], "stop")
        self.assertFalse(r["hit_2x"])

    def test_half_at_2x_then_trail(self):
        cs = [flat(0), cd(1, 1, 2, 1, 2), cd(2, 2, 10, 2, 10), cd(3, 10, 10, 5, 5)]
        r = self.sim(cs)
        self.assertEqual(r["exit_reason"], "trail_stop")
        # half banked at +100%, other half sold at 10 * 0.6 = 6 -> +500% on half
        self.assertAlmostEqual(r["gross_pct"], 50 + 250)
        self.assertTrue(r["hit_2x"] and r["hit_5x"] and r["hit_10x"])
        self.assertAlmostEqual(r["peak_x"], 10)

    def test_after_2x_trail_sits_40pct_below_peak(self):
        cs = [flat(0), cd(1, 1, 2, 1, 1.5), cd(2, 1.5, 1.5, 0.9, 0.9)]
        r = self.sim(cs)
        self.assertEqual(r["exit_reason"], "trail_stop")
        self.assertAlmostEqual(r["gross_pct"], 50 + 10)  # half +100%, half sold at 2 * 0.6 = 1.2 (+20%)

    def test_gap_below_stop_exits_at_open(self):
        r = self.sim([flat(0), cd(1, 0.3, 0.3, 0.25, 0.3)])
        self.assertEqual(r["exit_reason"], "gap_below_stop")
        self.assertAlmostEqual(r["gross_pct"], -70)

    def test_rug_exits_at_low(self):
        r = self.sim([flat(0), cd(1, 1, 1, 0.02, 0.02), flat(2, 0.02)])
        self.assertEqual(r["exit_reason"], "rug")
        self.assertAlmostEqual(r["gross_pct"], -98)
        self.assertAlmostEqual(r["net_pct"], -100)       # never below -100

    def test_time_exit_last_close(self):
        cs = [flat(0)] + [flat(i, 1.3) for i in range(1, 280)]
        r = self.sim(cs, hz=24)
        self.assertEqual(r["exit_reason"], "time")
        self.assertAlmostEqual(r["gross_pct"], 30, places=5)

    def test_candles_after_horizon_ignored(self):
        cs = [flat(0), flat(1, 1.1)] + [cd(400, 1, 50, 1, 50)]
        r = self.sim(cs, hz=24, liq=20_000)
        self.assertFalse(r["hit_2x"])

    def test_no_entry_when_no_trade_near_entry(self):
        r = self.sim([flat(5), flat(6)])
        self.assertEqual(r["status"], "no_entry")
        self.assertIsNone(r["net_pct"])

    def test_bad_print_is_unreliable_not_a_win(self):
        r = self.sim([flat(0), cd(1, 1, 100, 1, 1), flat(2)])
        self.assertEqual(r["status"], "unreliable")
        self.assertIsNone(r["net_pct"])

    def test_transient_jump_is_unreliable(self):
        r = self.sim([flat(0), flat(1, 1), cd(2, 1, 12, 1, 12), flat(3, 1.1)])
        self.assertEqual(r["status"], "unreliable")

    def test_real_sustained_jump_counts(self):
        cs = [flat(0), flat(1), cd(2, 1, 12, 1, 12), flat(3, 12), flat(4, 12)]
        r = self.sim(cs, liq=50_000)
        self.assertEqual(r["status"], "labelled")
        self.assertTrue(r["hit_10x"])

    def test_dead_pool_rest_is_worthless(self):
        r = self.sim([flat(0), flat(1, 1.2)], liq=100)
        self.assertEqual(r["exit_reason"], "dead_pool")
        self.assertAlmostEqual(r["gross_pct"], -100)

    def test_quiet_chart_without_liquidity_is_unknown(self):
        r = self.sim([flat(0), flat(1, 1.2)], liq=None)
        self.assertEqual(r["status"], "unknown")

    def test_entry_is_candle_high(self):
        r = self.sim([cd(0, 1, 1.5, 1, 1.2), cd(1, 1.2, 3, 1.2, 3)], liq=20_000)
        self.assertAlmostEqual(r["entry_px"], 1.5)
        self.assertTrue(r["hit_2x"])

    def test_window_peak_seen_after_exit(self):
        r = self.sim([flat(0), cd(1, 1, 1, 0.5, 0.5), cd(2, 0.5, 8, 0.5, 8), flat(3, 8)], liq=20_000)
        self.assertEqual(r["exit_reason"], "stop")
        self.assertAlmostEqual(r["window_peak_x"], 8)

    def test_max_mcap(self):
        r = self.sim([flat(0), cd(1, 1, 3, 1, 3), flat(2, 3)], liq=20_000)
        self.assertAlmostEqual(r["max_mcap_usd"], 90_000)


class Selection(unittest.TestCase):
    def test_eligible_bounds(self):
        self.assertTrue(nr.eligible(pair())[0])
        self.assertFalse(nr.eligible(pair(mcap=9_000))[0])
        self.assertFalse(nr.eligible(pair(mcap=150_000))[0])
        self.assertFalse(nr.eligible(pair(liq=4_000))[0])
        p = pair(); p["chainId"] = "base"
        self.assertFalse(nr.eligible(p)[0])
        p = pair(); p["pairAddress"] = None
        self.assertFalse(nr.eligible(p)[0])

    def test_no_age_rule(self):
        self.assertTrue(nr.eligible(pair(created_min=1))[0])

    def test_decide(self):
        self.assertEqual(nr.decide(["x"], PASS)[0], "REJECT")
        self.assertEqual(nr.decide([], None)[0], "NOT_CHECKED")
        self.assertEqual(nr.decide([], dict(PASS, fails=["mint authority"]))[0], "REJECT")
        self.assertEqual(nr.decide([], dict(PASS, unknown=["RugCheck unavailable"]))[0], "UNVERIFIED")
        self.assertEqual(nr.decide([], PASS)[0], "PICK")

    def test_honeypot_hint_rejects(self):
        p = pair(); p["txns"]["h1"] = {"buys": 50, "sells": 0}
        self.assertTrue(nr.cheap_fails(p))

    def test_features(self):
        f = nr.features(pair(h1=-55), T0, {"MINT1": {}})
        self.assertEqual(f["entry_type"], "dip")
        self.assertAlmostEqual(f["buy_ratio_m5"], 0.75)
        self.assertAlmostEqual(f["vol_speed"], 2.0)
        self.assertAlmostEqual(f["age_min"], 40)
        self.assertTrue(f["has_profile"])
        self.assertEqual(nr.features(pair(h1=150), T0)["entry_type"], "chase")
        self.assertEqual(nr.features(pair(h1=10), T0)["entry_type"], "neutral")

    def _deep(self, rpc=None, rug=None, sell=None, pool=None, fail=()):
        good_rpc = {"mint_authority": None, "freeze_authority": None, "decimals": 6, "t22": {},
                    "top10_wallets_pct": 18.0, "holders_read": True}
        good_rug = {"risks": [], "lp_locked_pct": 100, "mint_authority": None, "freeze_authority": None,
                    "rugged": False, "insiders": 0, "creator_in_top": False, "creator_rug_flag": False,
                    "total_holders": 400, "creator_pct": 2.0, "score": 10}
        good_pool = {"drawdown_pct": 70.0, "trades": {"n": 50, "unique": 40, "distinct_ratio": 0.8,
                     "top_wallet_share": 5, "bot_wallets": [], "bot_share": 0, "uniform_share": 0.05}}
        vals = {"rpc": rpc or good_rpc, "rug": rug or good_rug, "sell": sell or {"ok": True, "loss_pct": 4.0},
                "pool": pool or good_pool}

        def mk(k):
            def f(*a):
                if k in fail:
                    raise RuntimeError("api down")
                return vals[k]
            return f
        return nr.deep_check(pair(), {k: mk(k) for k in vals})

    def test_deep_dip_far_below_peak_is_not_a_reject(self):
        d = self._deep()
        self.assertEqual(nr.decide([], d)[0], "PICK")
        self.assertTrue(any("48h peak" in w for w in d["warns"]))
        self.assertAlmostEqual(d["feat"]["drawdown_48h_pct"], 70.0)

    def test_deep_other_fails_still_reject(self):
        d = self._deep(rpc={"mint_authority": "DEV", "freeze_authority": None, "decimals": 6, "t22": {},
                            "top10_wallets_pct": 18.0, "holders_read": True})
        self.assertEqual(nr.decide([], d)[0], "REJECT")

    def test_deep_rugcheck_down_is_unverified(self):
        self.assertEqual(nr.decide([], self._deep(fail=("rug",)))[0], "UNVERIFIED")

    def test_deep_sell_loss_rejects(self):
        self.assertEqual(nr.decide([], self._deep(sell={"ok": True, "loss_pct": 30.0}))[0], "REJECT")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        nr.DATA_DIR = self.dir
        self.sent = []

    def tearDown(self):
        shutil.rmtree(self.dir)

    def sender(self, text):
        self.sent.append(text)
        return True

    def deps(self, pairs, deep=lambda p: PASS):
        return {"discover": lambda: (pairs, {}, []), "deep": deep,
                "track": lambda st, t: (0, []), "label": lambda st, t: ([], [])}

    def rows(self, name):
        with open(os.path.join(self.dir, name), newline="") as fh:
            return list(csv.DictReader(fh))

    def test_scan_records_picks_rejects_and_ignores_ineligible(self):
        pairs = [pair("GOOD"), pair("BAD"), pair("BIG", mcap=900_000)]
        deep = lambda p: PASS if p["baseToken"]["address"] == "GOOD" else dict(PASS, fails=["mint authority"])
        nr.run(T0, self.deps(pairs, deep), self.sender)
        s = {r["mint"]: r for r in self.rows(nr.SIGHTINGS)}
        self.assertEqual(set(s), {"GOOD", "BAD"})
        self.assertEqual(s["GOOD"]["decision"], "PICK")
        self.assertEqual(s["BAD"]["decision"], "REJECT")
        self.assertAlmostEqual(float(s["GOOD"]["holders_per_min"]), 10.0)
        self.assertTrue(any(t.startswith("RUNNER PICK") for t in self.sent))
        with open(os.path.join(self.dir, nr.STATE)) as fh:
            st = json.load(fh)
        self.assertIn("GOOD", st["open"])

    def test_one_entry_per_coin(self):
        nr.run(T0, self.deps([pair("GOOD")]), self.sender)
        nr.run(T0 + timedelta(minutes=10), self.deps([pair("GOOD")]), self.sender)
        self.assertEqual(len(self.rows(nr.SIGHTINGS)), 1)

    def test_deep_budget(self):
        pairs = [pair(f"M{i:02d}") for i in range(nr.DEEP_CHECKS_PER_SCAN + 3)]
        nr.run(T0, self.deps(pairs), self.sender)
        dec = [r["decision"] for r in self.rows(nr.SIGHTINGS)]
        self.assertEqual(dec.count("NOT_CHECKED"), 3)

    def test_pick_alert_cap(self):
        pairs = [pair(f"M{i:02d}") for i in range(6)]
        nr.run(T0, self.deps(pairs), self.sender)
        self.assertEqual(sum(1 for t in self.sent if t.startswith("RUNNER PICK")), nr.MAX_PICK_ALERTS_PER_SCAN)

    def test_crashing_safety_check_is_unverified(self):
        def boom(p):
            raise ValueError("bug")
        nr.run(T0, self.deps([pair("X1")], boom), self.sender)
        self.assertEqual(self.rows(nr.SIGHTINGS)[0]["decision"], "UNVERIFIED")

    def test_labels_written_once_from_candles(self):
        nr.run(T0, self.deps([pair("GOOD")]), self.sender)
        cs = [flat(0)] + [cd(1, 1, 2, 1, 2)] + [flat(i, 3) for i in range(2, 300)]
        calls = []

        def getter(url):
            calls.append(url)
            return {"data": {"attributes": {"ohlcv_list": [[c[0], *[x * 3e-5 for x in c[1:5]], 1] for c in cs]}}}
        st = nr.load_state()
        later = T0 + timedelta(hours=25)
        rows, errs = nr.label_due(st, later, getter, lambda pool: 20_000)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "labelled")
        self.assertTrue(rows[0]["hit_2x"])
        rows2, _ = nr.label_due(st, later + timedelta(hours=1), getter, lambda pool: 20_000)
        self.assertEqual(rows2, [])                      # 24h result is never rewritten
        self.assertIn("token=base", calls[0])

    def test_label_retries_then_gives_up(self):
        nr.run(T0, self.deps([pair("GOOD")]), self.sender)

        def down(url):
            raise OSError("api down")
        st = nr.load_state()
        rows, errs = nr.label_due(st, T0 + timedelta(hours=25), down)
        self.assertEqual(rows, [])
        self.assertTrue(errs)
        rows, _ = nr.label_due(st, T0 + timedelta(hours=24 + 73), down)
        self.assertTrue(any(r["status"] == "unknown" for r in rows))

    def test_track_open_milestones_once(self):
        nr.run(T0, self.deps([pair("GOOD")]), self.sender)
        st = nr.load_state()

        def getter(px):
            return lambda url: [dict(pair("GOOD"), priceUsd=str(px))]
        nr.track_open(st, T0 + timedelta(minutes=10), getter(3e-5 * 5.5), self.sender)
        nr.track_open(st, T0 + timedelta(minutes=20), getter(3e-5 * 5.6), self.sender)
        kinds = [r["kind"] for r in self.rows(nr.ALERTS)]
        self.assertEqual(kinds.count("2x"), 1)
        self.assertEqual(kinds.count("5x"), 1)
        nr.track_open(st, T0 + timedelta(minutes=30), getter(3e-5 * 3.0), self.sender)   # 5.6x -> 3x = -46%
        self.assertIn("trail", [r["kind"] for r in self.rows(nr.ALERTS)])

    def test_fetch_candles_pages_back(self):
        pages = [[[S + 1000 * 300 + i * 300, 1, 1, 1, 1, 1] for i in range(1000)],
                 [[S - 3000 + i * 300, 1, 1, 1, 1, 1] for i in range(500)]]
        it = iter(pages)
        cs = nr.fetch_candles("P", S, S + 2000 * 300, lambda url: {"data": {"attributes": {"ohlcv_list": next(it)}}})
        self.assertEqual(len(cs), 1500)
        self.assertEqual(cs, sorted(cs, key=lambda c: c[0]))

    def test_report_says_too_early(self):
        nr.ensure_files()
        text, n, _ = nr.report(T0)
        self.assertIn("TOO EARLY", text)
        self.assertEqual(n, 0)


class Safety(unittest.TestCase):
    def test_no_wallet_or_trading_code(self):
        with open(nr.__file__) as fh:
            src = fh.read().lower()
        for word in ("sendtransaction", "keypair", "private_key", "secret_key", "signtransaction", "/swap/v1/swap"):
            self.assertNotIn(word, src)

    def test_rules_version_stable(self):
        self.assertEqual(nr.rules_version(), nr.rules_version())
        self.assertTrue(nr.rules_version().startswith("runner-0.1:"))


if __name__ == "__main__":
    unittest.main()
