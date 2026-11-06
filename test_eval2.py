"""Offline tests for the eval-2 collection change (v1.5.3). No network. Run: python -m unittest test_eval2 -v"""
import csv, gzip, hashlib, json, os
from datetime import datetime, timedelta, timezone

import nexus_v15 as nx
import nexus_eval as ev
from test_nexus_v15 import Base, pair, candles_up, T0, HERE

FIX = json.load(open(os.path.join(HERE, "fixtures", "real_candles_eval2.json")))


def gt(cs):
    return lambda url: {"data": {"attributes": {"ohlcv_list": [list(c) for c in cs]}}}


def labels(sid=None):
    return [r for r in nx.load_rows(nx.LABELS) if sid is None or r["sighting_id"] == sid]


class TestProtocolFrozen(Base):
    def test_protocol_file_matches_pinned_hash(self):
        with open(os.path.join(HERE, nx.PROTOCOL_FILE), "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), nx.PROTOCOL_SHA256)

    def test_thresholds_unchanged(self):
        self.assertEqual((nx.MIN_AGE_H, nx.MIN_LIQ_USD, nx.HORIZONS[60], nx.RUG_DROP, nx.ENTRY_DELAY_MIN),
                         (3.0, 15_000, (40, -25), 0.90, 2))


class TestTraceability(Base):
    def test_sighting_and_label_rows_carry_trace_fields(self):
        p = pair("aaa", price="0.5")
        p["quoteToken"] = {"symbol": "SOL", "address": "So11111111111111111111111111111111111111112"}
        self.run_scan([p])
        s = nx.load_rows(nx.SIGHTINGS)[0]
        self.assertEqual((s["quote_symbol"], s["quote_address"][:4], s["protocol"]), ("SOL", "So11", "eval-2"))
        for r in labels():
            self.assertEqual(r["px0"], "0.5")
            self.assertEqual(r["protocol"], "eval-2")
            self.assertEqual(r["due_at"], nx.iso(nx.due_time(T0, int(r["horizon_min"]))))

    def test_quote_blank_when_pinned_pool_differs(self):
        p = pair("aaa", pool="poolB"); p["quoteToken"] = {"symbol": "SOL", "address": "x"}
        self.assertEqual(nx.quote_of(p, "poolA"), ("", ""))

    def test_horizons_labelled_only_when_due_and_every_attempt_logged(self):
        self.run_scan([pair("aaa")])
        g = gt(candles_up(T0, step=0.0005))
        nx.label_pending(T0 + timedelta(minutes=71), getter=g, dead_lookup=lambda r, d, t: False)
        st = {r["horizon_min"]: r["status"] for r in labels()}
        self.assertEqual(st, {"5": "labelled", "15": "labelled", "30": "labelled", "60": "pending", "240": "pending"})
        nx.label_pending(T0 + timedelta(minutes=72), getter=g, dead_lookup=lambda r, d, t: False)
        r60 = [r for r in labels() if r["horizon_min"] == "60"][0]
        self.assertEqual(r60["status"], "labelled")
        self.assertTrue(os.path.exists(nx.path(r60["candle_file"])))      # the exact candles behind the label
        with gzip.open(nx.path(r60["candle_file"]), "rt") as f:
            self.assertEqual(json.loads(f.readline())["sighting_id"], r60["sighting_id"])
        att = nx.load_rows(nx.ATTEMPTS)
        self.assertEqual([a["horizon_min"] for a in att if a["outcome"] == "labelled"], ["5", "15", "30", "60"])
        self.assertTrue(all(a["candle_file"] and a["due_at"] for a in att))

    def test_failed_lookup_is_logged_and_retried(self):
        self.run_scan([pair("aaa")])
        def boom(url):
            raise OSError("HTTP 429 from GeckoTerminal")
        nx.label_pending(T0 + timedelta(minutes=80), getter=boom, dead_lookup=lambda r, d, t: False)
        att = nx.load_rows(nx.ATTEMPTS)
        self.assertEqual({a["outcome"] for a in att}, {"failed"})
        self.assertIn("429", att[0]["detail"])
        self.assertTrue(all(r["status"] == "pending" for r in labels()))
        nx.label_pending(T0 + timedelta(minutes=140), getter=gt(candles_up(T0, step=0.0005)),
                         dead_lookup=lambda r, d, t: False)
        self.assertEqual([r["attempts"] for r in labels() if r["horizon_min"] == "60"], ["2"])
        self.assertEqual(len([a for a in nx.load_rows(nx.ATTEMPTS) if a["horizon_min"] == "60"]), 2)

    def test_old_rows_keep_old_timing(self):
        self.run_scan([pair("aaa")])
        rows = nx.load_rows(nx.LABELS)
        for r in rows:
            r["due_at"] = r["protocol"] = r["px0"] = ""            # a row written before eval-2
        nx.write_rows(nx.LABELS, nx.LABEL_COLS, rows)
        nx.label_pending(T0 + timedelta(minutes=100), getter=gt(candles_up(T0)), dead_lookup=lambda r, d, t: False)
        self.assertTrue(all(r["status"] == "pending" for r in labels()))
        self.assertFalse(os.path.exists(nx.path(nx.ATTEMPTS)))      # old rows are not part of eval-2's log


class TestNoValidEntry(Base):
    def real(self, sym):
        f = FIX[sym]
        t0 = datetime.fromisoformat(f["seen_at"])
        cs = [(int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4])) for c in f["ohlcv_list"]]
        return f, t0, cs

    def test_moonvember_real_collapse_before_entry(self):
        f, t0, cs = self.real("MOONVEMBER")
        code, detail = nx.entry_check(cs, t0.timestamp(), float(f["price_usd"]))
        self.assertEqual(code, "no_valid_entry", detail)

    def test_vetotrump_real_normal_entry_unchanged(self):
        f, t0, cs = self.real("VETOTRUMP")
        self.assertEqual(nx.entry_check(cs, t0.timestamp(), float(f["price_usd"]))[0], "ok")
        r = nx.label_from_candles(cs, t0.timestamp(), 60, 40, -25, float(f["rt_cost_pct"]))
        self.assertEqual((r["reason"], round(r["net"], 2)), ("stop", -29.21))      # same as the traced example

    def test_reference_mismatch_skips_check(self):
        cs = [(int(T0.timestamp()) + 60 * i, 1e-9, 1e-9, 1e-9, 1e-9) for i in range(-5, 70)]
        self.assertEqual(nx.entry_check(cs, T0.timestamp(), 1.0)[0], "ref_mismatch")

    def test_pipeline_records_no_valid_entry_for_all_horizons(self):
        f, t0, cs = self.real("MOONVEMBER")
        p = pair("moon", price=f["price_usd"], now=t0, age_h=0.5)
        self.run_scan([p], now=t0)
        nx.label_pending(t0 + timedelta(hours=5), getter=gt(cs), dead_lookup=lambda r, d, t: False)
        self.assertEqual({r["status"] for r in labels()}, {"no_valid_entry"})
        self.assertTrue(all(r["net_pct"] == "" and r["exit_reason"] == "collapse_before_entry" for r in labels()))
        self.assertEqual({a["outcome"] for a in nx.load_rows(nx.ATTEMPTS)}, {"no_valid_entry"})


class TestEvalReport(Base):
    def setUp(self):
        super().setUp()
        nx.ensure_files()

    def write(self, sightings, labs, scans=1):
        nx.write_rows(nx.SIGHTINGS, nx.SIGHT_COLS, sightings)
        nx.write_rows(nx.LABELS, nx.LABEL_COLS, labs)

    def tok(self, scan, sym, age, liq, net, status="labelled", regime="NEUTRAL"):
        sid = f"{scan}-{sym}"
        young = age < 3
        s = {"sighting_id": sid, "scan_id": scan, "symbol": sym, "mint": sym, "pool": "p" + sym, "age_h": str(age),
             "liq_usd": str(liq), "weather": regime, "b0_liquid": "1", "label_this": "1", "protocol": "eval-2",
             "decision": "REJECT" if young else "NOT_CHECKED",
             "reasons": "younger than 3h (H1 maturity rule)" if young else "deep-check budget used"}
        l = {"sighting_id": sid, "horizon_min": "60", "status": status, "net_pct": "" if net is None else str(net),
             "protocol": "eval-2"}
        return s, l

    def test_reuse_cap_funnel_and_scan_unit(self):
        rows = [self.tok("s1", "Y1", 1, 30000, -30), self.tok("s1", "Y2", 1, 29000, -10),
                self.tok("s1", "Y3", 1, 28000, -5), self.tok("s1", "M1", 10, 31000, 5),
                self.tok("s2", "Y4", 1, 20000, 10), self.tok("s2", "M2", 10, 21000, 0),
                self.tok("s2", "Y5", 0.5, 20000, None, status="no_valid_entry"),
                self.tok("s3", "Y6", 1, 20000, -1), self.tok("s3", "M3", 10, 90000, 0)]   # M3 outside 0.5-2x
        self.write([r[0] for r in rows], [r[1] for r in rows])
        r = ev.build(nx.DATA_DIR)
        f = r["funnel"]
        self.assertEqual(f["  young"], 6)
        self.assertEqual(f["young with a comparator (cap 2)"], 4)               # Y1,Y2 on M1; Y4 + Y5 on M2
        self.assertEqual(f["young without a comparator"], 2)                    # Y3 (M1 used twice), Y6 (no eligible)
        self.assertEqual(f["  pairs: young had no valid entry (counted, not scored)"], 1)
        self.assertEqual(f["complete pairs (both 60m outcomes labelled)"], 3)
        self.assertEqual(r["reuse"], {"s1-M1": ["Y1 (s1)", "Y2 (s1)"], "s2-M2": ["Y4 (s2)", "Y5 (s2)"]})
        why = {p["young"]: p["why_unmatched"] for p in r["pairs"]}
        self.assertEqual((why["Y3"], why["Y6"]), ("comparators used twice", "no eligible comparator"))
        e = r["effect"]
        self.assertEqual(e["scan_level_mean_diff"], round(((-35 + -15) / 2 + 10) / 2, 2))   # scan means -25 and +10
        self.assertEqual(e["pairs_young_worse"], "2/3")
        self.assertEqual(r["no_valid_entry"]["young"], "1/6")
        self.assertIn("collecting: 3/50 complete pairs, 2/20 scans", r["milestone"])

    def test_shortfall_after_40_scans(self):
        rows = [self.tok(f"s{i:02d}", f"Y{i}", 1, 20000, -5) for i in range(40)]
        self.write([r[0] for r in rows], [r[1] for r in rows])
        self.assertIn("SHORTFALL after 40 scans: 50 pairs and 20 scans short", ev.build(nx.DATA_DIR)["milestone"])

    def test_old_protocol_rows_excluded(self):
        s, l = self.tok("s1", "Y1", 1, 30000, -30)
        s["protocol"] = l["protocol"] = ""
        self.write([s], [l])
        self.assertEqual(ev.build(nx.DATA_DIR)["funnel"]["sightings"], 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
