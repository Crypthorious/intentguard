"""Signed-verdict tests: Python signer <-> ContractSim (mirrors contract/src/lib.rs) and the guard's signing rule."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from intentguard_guard import guard, verdict as V, intents_stub as I, fixtures as F
from intentguard_guard.contract_sim import ContractSim, ContractError

NOW = 1_000_000_000_000


def setup():
    s = V.GuardSigner.from_seed(bytes([7]) * 32)
    c = ContractSim("o", guard_public_key=s.public_key, contract="guard.testnet")
    c.register_agent("o", "bot1", 100 * 10**6, 250 * 10**6)
    c.add_agent_key("o", "bot1", "pk")
    return s, c


def sign(s, amount=10, tout="wnear", h="h", nonce=1, now=NOW, ttl=60 * 10**9):
    return s.sign("guard.testnet", "bot1", h, amount, "usdc", tout, now_ns=now, ttl_ns=ttl, nonce=nonce)


class T(unittest.TestCase):
    def test_canonical_message_matches_rust_vector(self):
        # same vector as verdict_message_is_canonical in contract/src/lib.rs
        self.assertEqual(V.verdict_message("guard.testnet", "bot1", "abc", 50_000_000, "usdc.near", "wrap.near", 1_700, 9),
                         b"intentguard-verdict-v1\nguard.testnet\nbot1\nabc\n50000000\nusdc.near\nwrap.near\n1700\n9")

    def test_public_key_matches_rust_test_key(self):
        # seed [7;32] is guard_sk() in the Rust tests; both sides must derive the same NEAR public key
        s = V.GuardSigner.from_seed(bytes([7]) * 32)
        self.assertEqual(V.near_pk_to_bytes(s.public_key), s.public_bytes)
        self.assertEqual(V.b58decode(V.b58encode(b"\0\0abc")), b"\0\0abc")

    def test_valid_verdict_settles(self):
        s, c = setup()
        r = c.settle("pk", 10, "usdc", "wnear", "h", NOW, sign(s))
        self.assertEqual(r["remaining_daily"], 250 * 10**6 - 10)

    def test_no_verdict(self):
        s, c = setup()
        with self.assertRaisesRegex(ContractError, "ERR_NO_VERDICT"):
            c.settle("pk", 10, "usdc", "wnear", "h", NOW)

    def test_replay(self):
        s, c = setup()
        v = sign(s, nonce=42)
        c.settle("pk", 10, "usdc", "wnear", "h", NOW, v)
        with self.assertRaisesRegex(ContractError, "ERR_REPLAY"):
            c.settle("pk", 10, "usdc", "wnear", "h", NOW, v)

    def test_tampered_amount_token_hash(self):
        s, c = setup()
        v = sign(s)
        for args in ((99, "usdc", "wnear", "h"), (10, "usdc", "attacker.near", "h"), (10, "usdc", "wnear", "other")):
            with self.assertRaisesRegex(ContractError, "ERR_BAD_SIG"):
                c.settle("pk", *args, NOW, v)

    def test_forged_by_other_key(self):
        s, c = setup()
        with self.assertRaisesRegex(ContractError, "ERR_BAD_SIG"):
            c.settle("pk", 10, "usdc", "wnear", "h", NOW, sign(V.GuardSigner.generate()))

    def test_expired_and_too_long(self):
        s, c = setup()
        with self.assertRaisesRegex(ContractError, "ERR_VERDICT_EXPIRED"):
            c.settle("pk", 10, "usdc", "wnear", "h", NOW + 61 * 10**9, sign(s))
        with self.assertRaisesRegex(ContractError, "ERR_VERDICT_TTL_TOO_LONG"):
            c.settle("pk", 10, "usdc", "wnear", "h", NOW, sign(s, ttl=V.MAX_VERDICT_TTL_NS + 1))

    def test_no_guard_key_fails_closed(self):
        s, _ = setup()
        c = ContractSim("o", contract="guard.testnet")
        c.register_agent("o", "bot1", 100, 250); c.add_agent_key("o", "bot1", "pk")
        with self.assertRaisesRegex(ContractError, "ERR_GUARD_KEY_NOT_SET"):
            c.settle("pk", 10, "usdc", "wnear", "h", NOW, sign(s))

    def test_guard_signs_allow_only(self):
        s, c = setup()
        d = tempfile.mkdtemp()
        ctx = {"contract": c, "treasury_usd": 1000.0, "now": F.NOW, "kill_file": os.path.join(d, "KILL"),
               "signer": s, "contract_id": c.contract, "verdict_now_ns": NOW}
        pool = F.NEAR_POOL
        p = {"id": "t", "agent": "bot1", "token_in": "usdc.near", "token_out": "wrap.near", "amount_in": 50, "amount_usd": 50,
             "quote": I.quote(50, pool["reserve_in"], pool["reserve_out"], pool["fee"]), "pool": pool}
        ok = guard.evaluate(p, ctx)
        self.assertTrue(ok["allow"]); self.assertIn("signed_verdict", ok)
        r = c.settle("pk", ok["amount_raw"], "usdc.near", "wrap.near", ok["intent_hash"], NOW, ok["signed_verdict"])
        self.assertEqual(r["amount"], 50 * 10**6)
        bad = guard.evaluate(dict(p, amount_in=150, amount_usd=150, quote=I.quote(150, pool["reserve_in"], pool["reserve_out"], pool["fee"])), ctx)
        self.assertFalse(bad["allow"]); self.assertNotIn("signed_verdict", bad)

    def test_key_file_roundtrip(self):
        d = tempfile.mkdtemp()
        s = V.GuardSigner.generate(); s.save_key_file(os.path.join(d, "k.json"))
        s2 = V.GuardSigner.from_key_file(os.path.join(d, "k.json"))
        self.assertEqual(s.public_key, s2.public_key)
        self.assertEqual(oct(os.stat(os.path.join(d, "k.json")).st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
