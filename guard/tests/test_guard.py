import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from intentguard_guard import guard, intents_stub as I, fixtures as F
from intentguard_guard.contract_sim import ContractSim, ContractError


def setup():
    c = ContractSim("o")
    c.register_agent("o", "bot", 100 * 10**6, 250 * 10**6)
    c.add_agent_key("o", "bot", "pk")
    d = tempfile.mkdtemp()
    return c, {"contract": c, "treasury_usd": 1000.0, "now": F.NOW, "kill_file": os.path.join(d, "KILL")}, d


def prop(usd, tok="wrap.near", pool=F.NEAR_POOL, rep=None, wallet=None, skew=0.0):
    return {"id": "t", "agent": "bot", "token_in": "usdc.near", "token_out": tok, "amount_in": usd, "amount_usd": usd,
            "quote": I.quote(usd, pool["reserve_in"], pool["reserve_out"], pool["fee"], skew), "pool": pool,
            "token_report": rep, "signal_wallet": wallet}


class T(unittest.TestCase):
    def test_safe_allowed(self):
        c, ctx, _ = setup()
        self.assertTrue(guard.evaluate(prop(50, wallet=F.GOOD_WALLET), ctx)["allow"])

    def test_safe_meme_allowed(self):
        c, ctx, _ = setup()
        v = guard.evaluate(prop(20, "goodmeme.pump", F.MEME_POOL, F.SAFE_MEME), ctx)
        self.assertTrue(v["allow"], v["reasons"])

    def test_over_cap(self):
        c, ctx, _ = setup()
        v = guard.evaluate(prop(150), ctx)
        self.assertFalse(v["allow"]); self.assertTrue(any("per-tx cap" in r for r in v["reasons"]))

    def test_daily_cap(self):
        c, ctx, _ = setup()
        # v0.2: unsigned settles are rejected (ERR_NO_VERDICT), so attach guard-signed verdicts
        from intentguard_guard.verdict import GuardSigner
        s = GuardSigner.generate(); c.set_guard_key("o", s.public_key)
        for n in (1, 2):
            c.settle("pk", 100 * 10**6, "a", "b", "h", 0, s.sign(c.contract, "bot", "h", 100 * 10**6, "a", "b", now_ns=0, nonce=n))
        v = guard.evaluate(prop(60), ctx)
        self.assertTrue(any("daily cap" in r for r in v["reasons"]))

    def test_contract_kill_switch(self):
        c, ctx, _ = setup()
        c.set_kill_switch("o", True)
        self.assertIn("contract: kill switch ON", guard.evaluate(prop(10), ctx)["reasons"])

    def test_kill_file(self):
        c, ctx, d = setup()
        open(ctx["kill_file"], "w").close()
        v = guard.evaluate(prop(10), ctx)
        self.assertFalse(v["allow"]); self.assertTrue(any("KILL" in r for r in v["reasons"]))

    def test_rug_blocked(self):
        c, ctx, _ = setup()
        v = guard.evaluate(prop(20, "rugmeme.pump", F.RUG_POOL, F.RUG_MEME), ctx)
        self.assertFalse(v["checks"]["launch"]["pass"])

    def test_missing_report_fail_closed(self):
        c, ctx, _ = setup()
        self.assertFalse(guard.evaluate(prop(20, "unknown.pump", F.MEME_POOL, None), ctx)["allow"])

    def test_bad_quote(self):
        c, ctx, _ = setup()
        self.assertFalse(guard.evaluate(prop(50, skew=-0.05), ctx)["checks"]["price"]["pass"])
        self.assertFalse(guard.evaluate(prop(50, skew=+0.05), ctx)["checks"]["price"]["pass"])

    def test_v4_sqrt_price_path(self):
        pool = {"sqrt_price_x96": 2**96, "liquidity": 10**22, "eth_usd": 3000, "fee": 0.0}
        self.assertAlmostEqual(guard.fair_out(5.0, pool), 5.0)
        self.assertGreater(guard.check_price({"amount_in": 5.0, "pool": pool, "quote": {"amount_out": 5.0}}, guard.DEFAULT_CFG)[1]["liquidity_usd"], 12000)

    def test_bad_wallet(self):
        c, ctx, _ = setup()
        self.assertFalse(guard.evaluate(prop(30, wallet=F.BAD_WALLET), ctx)["checks"]["reputation"]["pass"])

    def test_malformed_fail_closed(self):
        c, ctx, _ = setup()
        v = guard.evaluate({"agent": "bot"}, ctx)
        self.assertFalse(v["allow"]); self.assertTrue(any("guard_error" in r for r in v["reasons"]))

    def test_contract_sim_rejects_bypass(self):
        c, ctx, _ = setup()
        with self.assertRaises(ContractError):
            c.settle("pk", 101 * 10**6, "a", "b", "h", 0)
        with self.assertRaises(ContractError):
            c.settle("other", 1, "a", "b", "h", 0)


if __name__ == "__main__":
    unittest.main()
