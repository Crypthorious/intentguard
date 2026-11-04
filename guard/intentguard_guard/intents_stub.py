"""SIMULATED NEAR Intents client. The live flow is: 1Click/solver-relay quote -> sign NEP-413 intent ->
intents.near `execute_intents`. The demo stays offline and deterministic, so this stub
returns a deterministic constant-product quote from fixture reserves. `skew` lets the demo fake a bad solver quote.
Real read-only dry quotes: see oneclick.py and guard/live_quote_check.py (opt-in)."""
import hashlib, json


def quote(amount_in, reserve_in, reserve_out, fee=0.003, skew=0.0):
    a = amount_in * (1 - fee)
    out = reserve_out * a / (reserve_in + a)
    return {"amount_out": out * (1 + skew), "simulated": True, "source": "intents_stub"}


def intent_hash(intent):
    return hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
