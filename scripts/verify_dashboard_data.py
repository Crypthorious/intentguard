#!/usr/bin/env python3
"""Offline check of the dashboard's saved data (no network, no key): every saved transaction's guard signature
verifies, or fails, exactly as the dashboard's in-browser check and the contract say it should.
Usage: python3 scripts/verify_dashboard_data.py [dashboard/data/verdicts.json]"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guard"))
from intentguard_guard import verdict as V  # noqa: E402

d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "dashboard/data/verdicts.json"))
pk = V.near_pk_to_bytes(d["guard_public_key"])
# expected signature result per on-chain outcome: settled -> valid; ERR_REPLAY -> valid but spent; ERR_BAD_SIG -> invalid
EXPECT = {None: True, "ERR_REPLAY": True, "ERR_BAD_SIG": False}
bad = 0
for s in d["scenarios"]:
    o = s.get("onchain")
    if not s.get("tx"):
        continue
    if not o:
        print(f"FAIL {s['scenario']}: tx without saved onchain copy (run scripts/snapshot_onchain.py)"); bad += 1; continue
    a, v = o["args"], o["args"].get("verdict")
    if v is None:
        ok = o["error"] in ("ERR_NO_VERDICT", "ERR_KILL_SWITCH_ON", "ERR_OVER_PER_TX_CAP")
        print(f"{'ok  ' if ok else 'FAIL'} {s['scenario']:<26} no verdict -> {o['error']}"); bad += not ok; continue
    sig_ok = V.verify(pk, d["contract"], "bot1", a["intent_hash"], a["amount"], a["token_in"], a["token_out"], v)
    ok = sig_ok == EXPECT.get(o["error"], None) and o["ok"] == (o["error"] is None)
    print(f"{'ok  ' if ok else 'FAIL'} {s['scenario']:<26} signature valid={sig_ok} -> {o['error'] or 'settled'}"); bad += not ok
print("RESULT", "OK" if not bad else f"{bad} FAILED")
sys.exit(1 if bad else 0)
