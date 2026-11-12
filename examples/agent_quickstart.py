#!/usr/bin/env python3
"""Add Rugwall to your agent: the whole loop in one file. Offline, no keys, no network, about 1 second.

    python3 examples/agent_quickstart.py

1. Your agent builds a swap proposal.
2. It asks the Rugwall guard. The guard runs the risk, launch, price and reputation checks.
   On ALLOW it signs an ed25519 verdict bound to this contract, agent, amount, tokens and intent hash.
3. The agent sends `settle(amount, token_in, token_out, intent_hash, verdict)` to the contract.
   Here the contract is ContractSim, the Python mirror of contract/src/lib.rs with the same error codes.
   On testnet the same call goes to guard2.intentguard-5821c5.testnet (see README, "Add Rugwall to your agent").
4. A rigged quote gets DENY and no signature. If the agent skips the guard, the contract refuses it."""
import os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guard"))
from intentguard_guard import guard, intents_stub, fixtures as F, verdict as V  # noqa: E402
from intentguard_guard.contract_sim import ContractSim, ContractError  # noqa: E402

# Setup (the human does this once): a guard key, the contract, the agent's caps and its settle-only key.
guard_key = V.GuardSigner.generate()                      # testnet: GuardSigner.from_key_file(<file outside the repo>)
contract = ContractSim("human.testnet", guard_public_key=guard_key.public_key)
contract.register_agent("human.testnet", "bot1", per_tx_cap=100 * 10**6, daily_cap=250 * 10**6)  # USDC, 6 dp
contract.add_agent_key("human.testnet", "bot1", "ed25519:AGENTKEY")
ctx = {"contract": contract, "treasury_usd": 1000.0, "now": F.NOW, "signer": guard_key, "contract_id": contract.contract}
pool = dict(F.NEAR_POOL, source="fixture pool")


def proposal(usd, skew=0.0):
    """What your agent wants to do. Live data: intentguard_guard.live_data.snapshot() gives a real 1Click dry quote and Ref pool."""
    return {"id": f"swap-{usd}", "agent": "bot1", "token_in": "usdc.near", "token_out": "wrap.near",
            "amount_in": usd, "amount_usd": usd, "pool": pool, "token_report": None, "signal_wallet": None,
            "quote": intents_stub.quote(usd, pool["reserve_in"], pool["reserve_out"], pool["fee"], skew)}


def agent_trade(p):
    v = guard.evaluate(p, ctx)                                        # step 2: ask Rugwall
    if not v["allow"]:
        return f"guard DENY, nothing sent: {'; '.join(v['reasons'])}"
    r = contract.settle("ed25519:AGENTKEY", v["amount_raw"], p["token_in"], p["token_out"],
                        v["intent_hash"], time.time_ns(), v["signed_verdict"])   # step 3: settle with the verdict
    return f"guard ALLOW, signed; contract settled {r['amount'] / 1e6:.2f} USDC, {r['remaining_daily'] / 1e6:.2f} left today"


print("safe $50 swap      ->", agent_trade(proposal(50)))
print("rigged quote (-8%) ->", agent_trade(proposal(50, skew=-0.08)))
try:                                                                  # step 4: a compromised agent skips the guard
    contract.settle("ed25519:AGENTKEY", 10 * 10**6, "usdc.near", "wrap.near", "made-up", time.time_ns(), None)
    print("skip the guard     -> contract ACCEPTED (this would be a bug)"); sys.exit(1)
except ContractError as e:
    print("skip the guard     -> contract rejected:", e)
