import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from intentguard_guard import oneclick as O

SAMPLE = {"quote": {"amountIn": "1000000000000000000000000", "amountInUsd": "4.38", "amountOut": "4364138",
                    "amountOutFormatted": "4.364138", "amountOutUsd": "4.363649", "minAmountOut": "4320496"},
          "quoteRequest": {"dry": True}, "correlationId": "x"}


class T(unittest.TestCase):
    def test_request_is_dry(self):
        b = O.build_dry_request("nep141:wrap.near", "nep141:usdc", 10**24)
        self.assertIs(b["dry"], True); self.assertEqual(b["amount"], str(10**24))

    def test_parse_and_deviation(self):
        pq = O.parse_quote(SAMPLE)
        self.assertAlmostEqual(pq["amount_out"], 4.364138); self.assertFalse(pq["simulated"])
        self.assertTrue(-1 < O.oracle_deviation_pct(pq) < 0)

    def test_refuses_non_dry(self):
        with self.assertRaises(ValueError):
            O.parse_quote({**SAMPLE, "quoteRequest": {"dry": False}})


if __name__ == "__main__":
    unittest.main()
