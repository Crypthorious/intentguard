#!/usr/bin/env python3
"""IntentGuard demo (FULLY SIMULATED: ContractSim mirrors contract/src/lib.rs; quotes from intents_stub).
Prints one line per scenario and exits 0 only if every scenario produced its expected verdict."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intentguard_guard import guard, intents_stub as I, fixtures as F
from intentguard_guard.contract_sim import ContractSim, ContractError

LIVE = os.environ.get("INTENTGUARD_NETWORK") == "testnet"   # opt-in: run against the deployed testnet contract
tmp = tempfile.mkdtemp()
AUDIT = os.path.join(tmp, "audit.jsonl")
if LIVE:
    from intentguard_guard.contract_testnet import ContractTestnet
    OWNER = os.environ.get("INTENTGUARD_OWNER", "intentguard-5821c5.testnet")
    c = ContractTestnet(OWNER, os.environ.get("INTENTGUARD_CONTRACT", "guard." + OWNER),
                        os.environ.get("INTENTGUARD_AGENT_KEY", "~/.near-credentials/testnet/agent-keys/bot1.json"))
    AGENT, PK = os.environ.get("INTENTGUARD_AGENT", "bot1"), c.agent_public_key()
else:
    OWNER, AGENT, PK = "human.testnet", "bot1", "ed25519:AGENTKEY"
    c = ContractSim(OWNER)
c.register_agent(OWNER, AGENT, per_tx_cap=100 * 10**6, daily_cap=250 * 10**6)   # USDC 6dp: $100/tx, $250/day
c.add_agent_key(OWNER, AGENT, PK)
ctx = {"contract": c, "treasury_usd": 1000.0, "now": F.NOW, "kill_file": os.path.join(tmp, "KILL")}


def proposal(pid, usd, token_out, pool, report=None, wallet=None, skew=0.0):
    q = I.quote(usd, pool["reserve_in"], pool["reserve_out"], pool["fee"], skew)
    return {"id": pid, "agent": AGENT, "token_in": "usdc.near", "token_out": token_out, "amount_in": usd, "amount_usd": usd,
            "quote": q, "pool": pool, "token_report": report, "signal_wallet": wallet}


def run(p, expect):
    v = guard.evaluate(p, ctx, audit_path=AUDIT)
    settled = None
    if v["allow"]:
        try:
            settled = c.settle(PK, int(p["amount_usd"] * 1e6), p["token_in"], p["token_out"], I.intent_hash(p["quote"]), int(F.NOW * 1e9))
        except ContractError as e:
            settled = f"CONTRACT REJECTED {e}"
    ok = v["verdict"] == expect
    print(f"[{'PASS' if ok else 'FAIL'}] {p['id']:<24} guard={v['verdict']:<5} expected={expect:<5} "
          f"settle={settled if settled is not None else '-'}")
    for r in v["reasons"]:
        print(f"        - {r}")
    return ok


results = []
print("== IntentGuard demo (" + (f"LIVE testnet contract {c.contract}" if LIVE else "SIMULATED contract") + " + SIMULATED NEAR Intents quotes) ==")
results.append(run(proposal("1_safe_swap_usdc_wnear", 50, "wrap.near", F.NEAR_POOL, wallet=F.GOOD_WALLET), "ALLOW"))
results.append(run(proposal("2_safe_meme_buy", 20, "goodmeme.pump", F.MEME_POOL, report=F.SAFE_MEME), "ALLOW"))
results.append(run(proposal("3_over_cap", 150, "wrap.near", F.NEAR_POOL), "DENY"))
results.append(run(proposal("4_rug_bundled_token", 20, "rugmeme.pump", F.RUG_POOL, report=F.RUG_MEME), "DENY"))
results.append(run(proposal("5_bad_quote_manipulated", 50, "wrap.near", F.NEAR_POOL, skew=-0.08), "DENY"))
results.append(run(proposal("6_copy_insider_wallet", 30, "wrap.near", F.NEAR_POOL, wallet=F.BAD_WALLET), "DENY"))
c.set_kill_switch(OWNER, True)
results.append(run(proposal("7_kill_switch_on", 10, "wrap.near", F.NEAR_POOL), "DENY"))
# 8: compromised agent bypasses the off-chain guard and calls the contract directly with its FC key
for amt, label in ((10, "kill switch on"), (500, "kill off, $500 > per-tx cap")):
    if label.startswith("kill off"):
        c.set_kill_switch(OWNER, False)
    try:
        c.settle(PK, amt * 10**6, "usdc.near", "attacker.near", "x", int(F.NOW * 1e9))
        print(f"[FAIL] 8_bypass_guard ({label}): contract ACCEPTED"); results.append(False)
    except ContractError as e:
        print(f"[PASS] 8_bypass_guard ({label}): contract rejected with {e}"); results.append(True)
print(f"policy after demo: {json.dumps(c.get_policy(AGENT))}")
print(f"audit log: {AUDIT}")
if LIVE:
    for label, h, ok in c.txs:
        print(f"  tx {'ok  ' if ok else 'FAIL'} {label:<28} https://testnet.nearblocks.io/txns/{h}" if h else f"  tx {'ok  ' if ok else 'FAIL'} {label:<28} (no tx hash printed by near-cli)")
print(f"RESULT: {sum(results)}/{len(results)} scenarios as expected")
sys.exit(0 if all(results) else 1)
