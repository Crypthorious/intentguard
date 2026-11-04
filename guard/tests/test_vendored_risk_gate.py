import json, os, sys, tempfile, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "intentguard_guard", "vendor"))
import risk_gate as rg

BASE = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "intentguard_guard", "vendor", "risk_gate_config.json")))


def mk():
    d = tempfile.mkdtemp()
    c = json.loads(json.dumps(BASE))
    c["kill_file"] = os.path.join(d, "KILL")
    c["live"]["approved_file"] = os.path.join(d, "LIVE_APPROVED")
    c["audit_log"] = os.path.join(d, "audit.jsonl")
    c["live"]["ledger"] = os.path.join(d, "live.jsonl")
    return c, d


def order(**kw):
    o = {"book": "breakout", "symbol": "SOLUSDT", "side": "long", "entry": 100.0, "stop": 97.0, "tp": 110.0,
         "notional": 15.0, "equity": 100.0, "mode": "shadow", "ts": "2026-10-20T12:00:00Z"}
    o.update(kw)
    return o


def mkt(**kw):
    m = {"bid": 99.99, "ask": 100.01, "mark": 100.0, "turnover24h": 5e8, "oi_usd": 1e8, "funding": 0.0001, "fetched": time.time()}
    m.update(kw)
    return m


EMPTY = {"open_positions": [], "realized_today": 0, "week_drawdown_usd": 0, "consecutive_losses": 0,
         "last_loss_ts": None, "trades_today": 0, "stopped_today": [], "closed_trades": 0}


def st(**kw):
    s = dict(EMPTY); s.update(kw); return s


class T(unittest.TestCase):
    def setUp(self):
        self.c, self.d = mk()

    def run_(self, o=None, s=None, m="default", pc=50):
        return rg.check(o or order(), s or st(), self.c, market=mkt() if m == "default" else m, paper_closed=pc)

    def has(self, v, key):
        return any(r.startswith(key) for r in v["reasons"])

    def test_baseline_allow(self):
        v = self.run_(); self.assertTrue(v["allow"], v)

    def test_kill_file(self):
        open(self.c["kill_file"], "w").close()
        v = self.run_(); self.assertFalse(v["allow"]); self.assertTrue(self.has(v, "KILL"))

    def test_live_requires_approved_file(self):
        v = self.run_(order(mode="live")); self.assertTrue(self.has(v, "live_not_approved"))
        open(self.c["live"]["approved_file"], "w").close()
        v = self.run_(order(mode="live")); self.assertTrue(v["allow"], v)

    def test_live_requires_30_paper_trades(self):
        open(self.c["live"]["approved_file"], "w").close()
        v = self.run_(order(mode="live"), pc=29); self.assertTrue(self.has(v, "live_paper_track"))

    def test_live_book_and_symbol_allowlist(self):
        open(self.c["live"]["approved_file"], "w").close()
        self.assertTrue(self.has(self.run_(order(mode="live", book="fade")), "live_book_not_allowed"))
        self.assertTrue(self.has(self.run_(order(mode="live", symbol="CLUSDT", entry=100)), "live_symbol_not_allowed"))

    def test_max_notional(self):
        self.assertTrue(self.has(self.run_(order(notional=25)), "max_notional"))
        self.assertTrue(self.has(self.run_(order(notional=5)), "min_notional"))

    def test_max_leverage(self):
        v = self.run_(order(notional=15, equity=10)); self.assertTrue(self.has(v, "max_leverage"))
        self.assertTrue(self.has(self.run_(order(leverage=2.0)), "max_leverage"))

    def test_stop_required(self):
        self.assertTrue(self.has(self.run_(order(stop=None)), "stop_missing"))
        self.assertTrue(self.has(self.run_(order(stop=101)), "stop_missing"))
        self.assertTrue(self.has(self.run_(order(side="short", stop=99, tp=90)), "stop_missing"))

    def test_max_loss_per_trade(self):
        v = self.run_(order(stop=90, tp=130)); self.assertTrue(self.has(v, "max_loss_per_trade"), v)
        self.assertGreater(v["metrics"]["max_loss_usd"], 1.0)

    def test_min_reward_risk(self):
        v = self.run_(order(tp=103)); self.assertTrue(self.has(v, "min_reward_risk"), v)
        v = self.run_(order(tp=None, book="fade")); self.assertTrue(self.has(v, "reward_risk"))
        v = self.run_(order(tp=None)); self.assertTrue(v["allow"], v)   # breakout assumed 2R
        self.c["min_reward_risk"] = 2.5
        self.assertTrue(self.has(self.run_(order(tp=None)), "min_reward_risk"))

    def test_max_open_positions(self):
        s = st(open_positions=[{"symbol": "CLUSDT", "side": "long", "notional": 10}, {"symbol": "MUUSDT", "side": "short", "notional": 10}])
        self.assertTrue(self.has(self.run_(s=s), "max_open_positions"))
        s = st(open_positions=[{"symbol": "SOLUSDT", "side": "long", "notional": 10}])
        self.assertTrue(self.has(self.run_(s=s), "already_open"))

    def test_correlated_exposure(self):
        s = st(open_positions=[{"symbol": "BTCUSDT", "side": "long", "notional": 20}])
        v = self.run_(s=s); self.assertTrue(self.has(v, "correlated_notional"), v)
        s = st(open_positions=[{"symbol": "BTCUSDT", "side": "short", "notional": 20}])
        self.assertTrue(self.run_(s=s)["allow"])           # opposite direction is fine
        s = st(open_positions=[{"symbol": "CLUSDT", "side": "long", "notional": 20}])
        self.assertTrue(self.run_(s=s)["allow"])           # oil is not BTC-beta
        self.c["max_correlated_same_dir_positions"] = 1; self.c["max_correlated_same_dir_notional_usd"] = 100
        s = st(open_positions=[{"symbol": "ETHUSDT", "side": "long", "notional": 5}])
        self.assertTrue(self.has(self.run_(s=s), "correlated_positions"))

    def test_daily_loss_stop(self):
        # min($10, 5% of $100) = $5
        self.assertTrue(self.has(self.run_(s=st(realized_today=-5.0)), "daily_loss_stop"))
        self.assertTrue(self.run_(s=st(realized_today=-4.9))["allow"])
        self.assertTrue(self.has(self.run_(order(equity=1000, notional=15), s=st(realized_today=-10.0)), "daily_loss_stop"))

    def test_weekly_drawdown(self):
        self.assertTrue(self.has(self.run_(s=st(week_drawdown_usd=15.0)), "weekly_drawdown_stop"))
        self.assertTrue(self.run_(s=st(week_drawdown_usd=14.0))["allow"])

    def test_consecutive_loss_cooldown(self):
        s = st(consecutive_losses=3, last_loss_ts="2026-10-20T06:00:00Z")
        self.assertTrue(self.has(self.run_(s=s), "loss_cooldown"))
        s = st(consecutive_losses=3, last_loss_ts="2026-10-19T06:00:00Z")
        self.assertTrue(self.run_(s=s)["allow"])
        s = st(consecutive_losses=2, last_loss_ts="2026-10-20T06:00:00Z")
        self.assertTrue(self.run_(s=s)["allow"])

    def test_reentry_after_stop(self):
        self.assertTrue(self.has(self.run_(s=st(stopped_today=["SOLUSDT"])), "reentry_after_stop"))

    def test_max_trades_per_day(self):
        self.assertTrue(self.has(self.run_(s=st(trades_today=4)), "max_trades_per_day"))

    def test_market_checks(self):
        self.assertTrue(self.has(self.run_(m=None), "market_data_unavailable"))
        self.assertTrue(self.has(self.run_(m=mkt(bid=99.8, ask=100.2)), "spread"))
        self.assertTrue(self.has(self.run_(m=mkt(turnover24h=1e6)), "liquidity"))
        self.assertTrue(self.has(self.run_(m=mkt(oi_usd=1e6)), "open_interest"))
        self.assertTrue(self.has(self.run_(m=mkt(funding=-0.002)), "funding"))
        self.assertTrue(self.has(self.run_(m=mkt(fetched=time.time() - 999)), "market_data_stale"))
        self.assertTrue(self.has(self.run_(m=mkt(bid=104.99, ask=105.01, mark=105)), "price_deviation"))
        self.assertTrue(self.run_(m="skip")["allow"])

    def test_fail_closed(self):
        self.assertFalse(self.run_(order(entry=None))["allow"])
        self.assertFalse(self.run_(order(side="buy"))["allow"])
        v = rg.check(order(), None, self.c, market=mkt(), paper_closed=50)   # broken state -> deny, no raise
        self.assertFalse(v["allow"]); self.assertTrue(self.has(v, "gate_error"))

    def test_book_state_replay(self):
        evs = [
            {"ts": "2026-10-19T10:00:00Z", "type": "open", "symbol": "A", "side": "long", "notional": 50},
            {"ts": "2026-10-19T12:00:00Z", "type": "close", "symbol": "A", "pnl": -2.0, "reason": "stop"},
            {"ts": "2026-10-20T01:00:00Z", "type": "open", "symbol": "B", "side": "short", "notional": 40},
            {"ts": "2026-10-20T02:00:00Z", "type": "close", "symbol": "B", "pnl": -1.0, "reason": "stop"},
            {"ts": "2026-10-20T03:00:00Z", "type": "open", "symbol": "C", "side": "long", "notional": 40},
        ]
        s = rg.book_state(evs, at="2026-10-20T04:00:00Z")
        self.assertEqual(s["realized_today"], -1.0); self.assertEqual(s["consecutive_losses"], 2)
        self.assertEqual(s["stopped_today"], ["B"]); self.assertEqual(s["trades_today"], 2)
        self.assertEqual([p["symbol"] for p in s["open_positions"]], ["C"]); self.assertAlmostEqual(s["week_drawdown_usd"], 3.0)
        s = rg.book_state(evs, at="2026-10-20T04:00:00Z", scale_notional=20)
        self.assertAlmostEqual(s["realized_today"], -0.5); self.assertAlmostEqual(s["open_positions"][0]["notional"], 20)
        s = rg.book_state(evs, at="2026-10-20T02:30:00Z")   # strictly before `at`
        self.assertEqual(s["open_positions"], [])

    def test_check_order_writes_audit(self):
        v = rg.check_order(order(), cfg=self.c, state=st(), market=mkt())
        self.assertIn("order", v)
        recs = rg.read_jsonl(self.c["audit_log"]); self.assertEqual(len(recs), 1)
        # live mode with no approval file -> deny and audited
        v = rg.check_order(order(mode="live"), cfg=self.c, state=st(), market=mkt())
        self.assertFalse(v["allow"]); self.assertEqual(len(rg.read_jsonl(self.c["audit_log"])), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
