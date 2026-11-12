#!/usr/bin/env python3
"""Rugwall (formerly IntentGuard) demo. Prints one line per scenario; exits 0 only if every scenario behaved as expected.

DATA (default): REAL read-only market data for the USDC -> wNEAR scenarios: a NEAR Intents 1Click quote with
dry=true, live Ref Finance pool 4512 reserves (mainnet view call) and NEP-148 ft_metadata. If any of those reads
fails, or INTENTGUARD_DATA=fixtures, it falls back to the offline fixtures and prints why. The two meme-token
scenarios always use fixture tokens (goodmeme.pump / rugmeme.pump are not real tokens).
CONTRACT (default): ContractSim, a Python mirror of contract/src/lib.rs. INTENTGUARD_NETWORK=testnet uses the
deployed testnet contract instead (signs TESTNET transactions with keys in ~/.near-credentials).
VERDICTS: every ALLOW is signed by the guard (ed25519); the contract refuses `settle` without a valid,
fresh, unused signature."""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intentguard_guard import guard, intents_stub as I, fixtures as F, verdict as V
from intentguard_guard.contract_sim import ContractSim, ContractError

LIVE = os.environ.get("INTENTGUARD_NETWORK") == "testnet"
EXPORT = os.environ.get("INTENTGUARD_EXPORT")          # optional: write a JSON verdict log (used by the dashboard)
tmp = tempfile.mkdtemp()
AUDIT = os.path.join(tmp, "audit.jsonl")

# ---------------------------------------------------------------- market data: live read-only, fixtures fallback
AMOUNTS = (10, 30, 50, 150)
DATA, data_note, snap = "fixtures", "", None
if os.environ.get("INTENTGUARD_DATA", "live") != "fixtures":
    try:
        from intentguard_guard import live_data as L
        snap = L.snapshot(AMOUNTS)
        DATA = "live"
    except Exception as e:  # network down, API changed, rate limit... -> offline fixtures, said out loud
        data_note = f"offline fallback: {type(e).__name__}: {str(e)[:120]}"
else:
    data_note = "forced by INTENTGUARD_DATA=fixtures"
if DATA == "live":
    TOKEN_IN, TOKEN_OUT = L.USDC, L.WNEAR
    NEAR_POOL = snap["pool"]
    cfg = json.loads(json.dumps(guard.DEFAULT_CFG))
    cfg["allowlisted_tokens"].append(L.USDC)
else:
    TOKEN_IN, TOKEN_OUT, NEAR_POOL, cfg = "usdc.near", "wrap.near", F.NEAR_POOL, guard.DEFAULT_CFG

# ---------------------------------------------------------------- contract + guard signing key
if LIVE:
    from intentguard_guard.contract_testnet import ContractTestnet
    OWNER = os.environ.get("INTENTGUARD_OWNER", "intentguard-5821c5.testnet")
    c = ContractTestnet(OWNER, os.environ.get("INTENTGUARD_CONTRACT", "guard2." + OWNER),
                        os.environ.get("INTENTGUARD_AGENT_KEY", "~/.near-credentials/testnet/agent-keys/bot1.json"))
    signer = V.GuardSigner.from_key_file(os.environ.get("INTENTGUARD_GUARD_KEY", "~/.near-credentials/testnet/agent-keys/guard-verdict.json"))
    AGENT, PK, CONTRACT_ID = os.environ.get("INTENTGUARD_AGENT", "bot1"), c.agent_public_key(), c.contract
    c.set_guard_key(OWNER, signer.public_key)
else:
    OWNER, AGENT, PK = "human.testnet", "bot1", "ed25519:AGENTKEY"
    signer = V.GuardSigner.generate()                     # fresh guard key for this offline run
    c = ContractSim(OWNER, guard_public_key=signer.public_key)
    CONTRACT_ID = c.contract
c.register_agent(OWNER, AGENT, per_tx_cap=100 * 10**6, daily_cap=250 * 10**6)   # USDC 6dp: $100/tx, $250/day
c.add_agent_key(OWNER, AGENT, PK)
ctx = {"contract": c, "treasury_usd": 1000.0, "now": F.NOW, "kill_file": os.path.join(tmp, "KILL"),
       "signer": signer, "contract_id": CONTRACT_ID}
log = []


def near_proposal(pid, usd, skew=0.0, wallet=None):
    if DATA == "live":
        q = dict(snap["quotes"][usd])
        if skew:  # a solver/relay tampers with the real quote before the agent sees it
            q["amount_out"] *= (1 + skew)
            q["source"] += f", then tampered {skew:+.0%} for this scenario"
    else:
        q = I.quote(usd, NEAR_POOL["reserve_in"], NEAR_POOL["reserve_out"], NEAR_POOL["fee"], skew)
        q["source"] = "intents_stub fixture"
    return {"id": pid, "agent": AGENT, "token_in": TOKEN_IN, "token_out": TOKEN_OUT, "amount_in": usd, "amount_usd": usd,
            "quote": q, "pool": NEAR_POOL, "token_report": None, "signal_wallet": wallet}


def meme_proposal(pid, usd, token_out, pool, report):
    q = I.quote(usd, pool["reserve_in"], pool["reserve_out"], pool["fee"])
    q["source"] = "intents_stub fixture"
    return {"id": pid, "agent": AGENT, "token_in": TOKEN_IN, "token_out": token_out, "amount_in": usd, "amount_usd": usd,
            "quote": q, "pool": dict(pool, source="fixture pool (fixture token)"), "token_report": report, "signal_wallet": None}


def settle(label, amount, token_in, token_out, intent_hash, verdict):
    kw = {"label": label} if LIVE else {}
    return c.settle(PK, amount, token_in, token_out, intent_hash, time.time_ns(), verdict, **kw)


def record(sid, ok, **kw):
    e = {"scenario": sid, "pass": ok, "ts": int(time.time()), **kw}
    if LIVE and c.txs:
        e["tx"] = c.txs[-1][1]
    log.append(e)
    return ok


def run(p, expect):
    v = guard.evaluate(p, ctx, cfg, audit_path=AUDIT)
    settled = None
    if v["allow"]:
        try:
            settled = settle(f"settle {p['id']}", v["amount_raw"], p["token_in"], p["token_out"], v["intent_hash"], v["signed_verdict"])
            p["_verdict"] = v
        except ContractError as e:
            settled = f"CONTRACT REJECTED {e}"
    ok = v["verdict"] == expect
    src = "live" if "1click" in str(p["quote"].get("source")) else "fixture"
    sig = f" sig=ed25519:{v['signed_verdict']['signature'][:12]}.." if v.get("signed_verdict") else ""
    print(f"[{'PASS' if ok else 'FAIL'}] {p['id']:<26} guard={v['verdict']:<5} expected={expect:<5} data={src:<7}{sig} "
          f"settle={settled if settled is not None else '-'}")
    for r in v["reasons"]:
        print(f"        - {r}")
    pm = v["checks"].get("price", {}).get("metrics", {})
    record(p["id"], ok, kind="guard", verdict=v["verdict"], expected=expect, reasons=v["reasons"], data=src,
           deviation_pct=pm.get("deviation_pct"), amount_usd=p["amount_usd"], token_out=p["token_out"],
           signed=bool(v.get("signed_verdict")), settle=settled if isinstance(settled, (dict, str)) else None)
    return ok


def bypass(sid, label, expect_err, amount, token_out, intent_hash, verdict):
    """The agent skips the guard and calls `settle` itself with its function-call key."""
    try:
        r = settle(sid, amount, TOKEN_IN, token_out, intent_hash, verdict)
        print(f"[FAIL] {sid:<26} ({label}): contract ACCEPTED {r}")
        return record(sid, False, kind="bypass", label=label, expected=expect_err, got="ACCEPTED")
    except ContractError as e:
        ok = str(e) == expect_err
        print(f"[{'PASS' if ok else 'FAIL'}] {sid:<26} ({label}): contract rejected with {e} (expected {expect_err})")
        return record(sid, ok, kind="bypass", label=label, expected=expect_err, got=str(e))


results = []
print("== Rugwall (formerly IntentGuard) demo: " + (f"LIVE testnet contract {c.contract}" if LIVE else "SIMULATED contract (ContractSim)") + " ==")
if DATA == "live":
    m_in, m_out, pool = snap["meta_in"], snap["meta_out"], snap["pool"]
    print(f"DATA: live, read-only. ft_metadata {m_in['symbol']} {m_in['decimals']}dp / {m_out['symbol']} {m_out['decimals']}dp; "
          f"{pool['source']}: {pool['reserve_in']:,.0f} {m_in['symbol']} / {pool['reserve_out']:,.0f} {m_out['symbol']} "
          f"(fee {pool['fee']*100:.2f}%); 1Click dry quotes for ${', $'.join(map(str, AMOUNTS))} ({snap['elapsed_s']}s)")
    print(f"      1Click: $50 {m_in['symbol']} -> {snap['quotes'][50]['amount_out']:.6f} {m_out['symbol']} (dry=true, no deposit address, no funds)")
else:
    print(f"DATA: fixtures ({data_note})")
print(f"GUARD KEY: {signer.public_key} (contract stores this public key; ALLOW verdicts are signed with it)")

p1 = near_proposal("1_safe_swap_usdc_wnear", 50, wallet=F.GOOD_WALLET)
results.append(run(p1, "ALLOW"))
results.append(run(meme_proposal("2_safe_meme_buy", 20, "goodmeme.pump", F.MEME_POOL, F.SAFE_MEME), "ALLOW"))
results.append(run(near_proposal("3_over_cap", 150), "DENY"))
results.append(run(meme_proposal("4_rug_bundled_token", 20, "rugmeme.pump", F.RUG_POOL, F.RUG_MEME), "DENY"))
results.append(run(near_proposal("5_bad_quote_manipulated", 50, skew=-0.08), "DENY"))
results.append(run(near_proposal("6_copy_insider_wallet", 30, wallet=F.BAD_WALLET), "DENY"))
c.set_kill_switch(OWNER, True)
results.append(run(near_proposal("7_kill_switch_on", 10), "DENY"))

# 8-13: a compromised agent skips the off-chain guard and calls the contract directly with its function-call key
results.append(bypass("8_bypass_kill_switch_on", "kill switch on, no verdict", "ERR_KILL_SWITCH_ON", 10 * 10**6, TOKEN_OUT, "x", None))
c.set_kill_switch(OWNER, False)
results.append(bypass("9_bypass_no_verdict", "kill off, $10 inside every cap, no guard signature", "ERR_NO_VERDICT", 10 * 10**6, TOKEN_OUT, "x", None))
results.append(bypass("10_bypass_over_cap", "kill off, $500 > per-tx cap", "ERR_OVER_PER_TX_CAP", 500 * 10**6, TOKEN_OUT, "x", None))
v1 = (p1.get("_verdict") or {})
results.append(bypass("11_replay_old_verdict", "re-sends scenario 1's signed verdict", "ERR_REPLAY",
                      v1.get("amount_raw", 0), TOKEN_OUT, v1.get("intent_hash", "x"), v1.get("signed_verdict")))
p12 = near_proposal("12_tamper_token", 10)
v12 = guard.evaluate(p12, ctx, cfg, audit_path=AUDIT)   # guard approves a $10 wNEAR buy...
results.append(bypass("12_tamper_token", "guard approved $10 wNEAR; agent swaps token_out to attacker.near", "ERR_BAD_SIG",
                      v12.get("amount_raw", 0), "attacker.near", v12.get("intent_hash", "x"), v12.get("signed_verdict")))
rogue = V.GuardSigner.generate()                       # ...or the agent signs its own "approval"
results.append(bypass("13_forged_verdict", "agent signs its own verdict with its own key", "ERR_BAD_SIG", 10 * 10**6, TOKEN_OUT, "forged",
                      rogue.sign(CONTRACT_ID, AGENT, "forged", 10 * 10**6, TOKEN_IN, TOKEN_OUT)))

pol = c.get_policy(AGENT)
print(f"policy after demo: {json.dumps(pol)}")
print(f"audit log: {AUDIT}")
print("settlement: the contract records the spend and emits a NEP-297 event; it does not call intents.near or move tokens")
print("quotes: " + ("REAL 1Click dry quotes + live Ref pool reserves for USDC->wNEAR; meme tokens are fixtures" if DATA == "live"
                    else "offline fixtures (intents_stub constant-product) - " + data_note))
if LIVE:
    for label, h, ok in c.txs:
        print(f"  tx {'ok  ' if ok else 'FAIL'} {label:<28} https://testnet.nearblocks.io/txns/{h}" if h else f"  tx {'ok  ' if ok else 'FAIL'} {label:<28} (no tx hash printed by near-cli)")
print(f"RESULT: {sum(results)}/{len(results)} scenarios as expected")
if EXPORT:
    out = {"generated_at": int(time.time()), "network": "testnet" if LIVE else "simulated", "contract": CONTRACT_ID,
           "guard_public_key": signer.public_key, "data": DATA, "data_note": data_note,
           "market": ({"pool": snap["pool"], "quote_50": snap["quotes"][50], "meta": [snap["meta_in"], snap["meta_out"]]} if snap else None),
           "policy_after": pol, "result": f"{sum(results)}/{len(results)}", "scenarios": log,
           "txs": [{"label": l, "hash": h, "ok": ok} for l, h, ok in getattr(c, "txs", [])]}
    with open(EXPORT, "w") as f:
        json.dump(out, f, indent=1, default=str)
sys.exit(0 if all(results) else 1)
