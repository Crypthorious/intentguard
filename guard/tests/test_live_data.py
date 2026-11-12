"""Offline tests for the real-data path (network calls are mocked) and the MCP wrapper's protocol layer."""
import io, json, os, subprocess, sys, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from intentguard_guard import live_data as L, guard

POOL = {"pool_kind": "SIMPLE_POOL", "token_account_ids": [L.USDC, L.WNEAR], "amounts": ["937031637371", "272805737110052266979183375203"], "total_fee": 30}


class T(unittest.TestCase):
    def test_ref_pool_parse(self):
        with mock.patch.object(L, "view", return_value=POOL):
            p = L.ref_pool(4512, L.USDC, L.WNEAR, 6, 24)
        self.assertAlmostEqual(p["reserve_in"], 937031.637371); self.assertAlmostEqual(p["reserve_out"], 272805.737110052, 3)
        self.assertEqual(p["fee"], 0.003); self.assertGreater(p["liquidity_usd"], 1e6)
        # a real quote 0.12% better than the pool's constant-product output passes the 2% price gate
        fair = guard.fair_out(50, p)
        self.assertEqual(guard.check_price({"amount_in": 50, "pool": p, "quote": {"amount_out": fair * 1.0012}}, guard.DEFAULT_CFG)[0], [])

    def test_ref_pool_rejects_wrong_pool(self):
        with mock.patch.object(L, "view", return_value=dict(POOL, token_account_ids=["a.near", "b.near"])):
            with self.assertRaises(RuntimeError):
                L.ref_pool(1, L.USDC, L.WNEAR, 6, 24)

    def test_demo_falls_back_to_fixtures_and_says_so(self):
        env = dict(os.environ, INTENTGUARD_DATA="fixtures")
        env.pop("INTENTGUARD_NETWORK", None)
        r = subprocess.run([sys.executable, os.path.join(HERE, "..", "demo.py")], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("DATA: fixtures (forced by INTENTGUARD_DATA=fixtures)", r.stdout)
        self.assertIn("RESULT: 13/13 scenarios as expected", r.stdout)
        self.assertIn("ERR_NO_VERDICT", r.stdout)

    def test_mcp_initialize_and_list(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        r = subprocess.run([sys.executable, os.path.join(HERE, "..", "..", "mcp", "rugwall_mcp.py")], input="\n".join(map(json.dumps, msgs)) + "\n",
                           capture_output=True, text=True, timeout=30)
        out = [json.loads(l) for l in r.stdout.splitlines()]
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "rugwall")
        self.assertEqual({t["name"] for t in out[1]["result"]["tools"]}, {"rugwall_check_swap", "rugwall_policy"})


if __name__ == "__main__":
    unittest.main()
