#!/usr/bin/env python3
"""Rugwall MCP server (stdio, JSON-RPC 2.0, no dependencies beyond the guard's own).

Lets any MCP client (Claude Desktop, Cursor, an agent framework) ask Rugwall before it trades:
  rugwall_check_swap   run the four guard checks on a USDC -> wNEAR proposal priced with a REAL 1Click
                       dry quote and live Ref Finance reserves; returns ALLOW/DENY with reasons.
                       It never signs: signing stays with the guard process that holds the verdict key.
  rugwall_policy       read the live testnet contract policy (caps, kill switch, guard key) over public RPC.
Read-only. No keys, no transactions. Config for a client:
  {"command": "python3", "args": ["/path/to/intentguard/mcp/rugwall_mcp.py"]}"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guard"))
from intentguard_guard import guard, fixtures as F  # noqa: E402

CONTRACT = os.environ.get("INTENTGUARD_CONTRACT", "guard2.intentguard-5821c5.testnet")
TOOLS = [
    {"name": "rugwall_check_swap",
     "description": "Check a proposed USDC->wNEAR swap for an AI trading agent: spend caps (live testnet contract), "
                    "price vs live Ref Finance pool reserves using a real 1Click dry quote, and optional copied-wallet reputation. "
                    "Returns ALLOW or DENY with reasons. Read-only; does not sign or trade.",
     "inputSchema": {"type": "object", "properties": {
         "amount_usd": {"type": "number", "description": "Swap size in USDC"},
         "agent": {"type": "string", "default": "bot1"},
         "copied_wallet": {"type": "string", "enum": ["none", "good_demo", "insider_demo"], "default": "none",
                           "description": "Demo wallet histories (fixtures) for the reputation check"}},
         "required": ["amount_usd"]}},
    {"name": "rugwall_policy",
     "description": "Read the live Rugwall contract policy on NEAR testnet: owner, kill switch, guard public key, an agent's caps and spend.",
     "inputSchema": {"type": "object", "properties": {"agent": {"type": "string", "default": "bot1"}}}},
]


def _contract():
    from intentguard_guard.contract_testnet import ContractTestnet
    owner = CONTRACT.split(".", 1)[1]
    return ContractTestnet(owner, CONTRACT, "/nonexistent")   # views only; no key is ever read


def check_swap(args):
    from intentguard_guard import live_data as L
    usd = float(args["amount_usd"])
    snap = L.snapshot((usd,))
    wallet = {"good_demo": F.GOOD_WALLET, "insider_demo": F.BAD_WALLET}.get(args.get("copied_wallet", "none"))
    p = {"id": "mcp", "agent": args.get("agent", "bot1"), "token_in": L.USDC, "token_out": L.WNEAR, "amount_in": usd,
         "amount_usd": usd, "quote": snap["quotes"][usd], "pool": snap["pool"], "token_report": None, "signal_wallet": wallet}
    cfg = json.loads(json.dumps(guard.DEFAULT_CFG)); cfg["allowlisted_tokens"].append(L.USDC)
    ctx = {"contract": _contract(), "treasury_usd": 1000.0, "now": F.NOW}
    v = guard.evaluate(p, ctx, cfg)
    return {"verdict": v["verdict"], "reasons": v["reasons"], "contract": CONTRACT,
            "price": v["checks"].get("price", {}).get("metrics"), "quote_out_wnear": snap["quotes"][usd]["amount_out"],
            "sources": {"quote": snap["quotes"][usd]["source"], "pool": snap["pool"]["source"]},
            "note": "Read-only check. A settle on the contract still needs the guard's signed verdict."}


def policy(args):
    c = _contract()
    return {"contract": CONTRACT, "config": c.get_config(), "policy": c.get_policy(args.get("agent", "bot1"))}


def handle(msg):
    m, mid = msg.get("method"), msg.get("id")
    if m == "initialize":
        res = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
               "capabilities": {"tools": {}}, "serverInfo": {"name": "rugwall", "version": "0.2.0"}}
    elif m == "tools/list":
        res = {"tools": TOOLS}
    elif m == "tools/call":
        name, args = msg["params"]["name"], msg["params"].get("arguments") or {}
        try:
            out = {"rugwall_check_swap": check_swap, "rugwall_policy": policy}[name](args)
            res = {"content": [{"type": "text", "text": json.dumps(out, default=str)}], "isError": False}
        except Exception as e:
            res = {"content": [{"type": "text", "text": f"error: {e!r}"}], "isError": True}
    elif m == "ping":
        res = {}
    elif mid is None:      # notifications (e.g. notifications/initialized)
        return None
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {m}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            out = handle(json.loads(line))
        except Exception as e:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": repr(e)}}
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    main()
