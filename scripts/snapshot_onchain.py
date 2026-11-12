#!/usr/bin/env python3
"""Add a saved copy of each logged transaction to dashboard/data/verdicts.json (read-only, no key).

For every scenario with a tx hash, reads the transaction from a public ARCHIVAL testnet RPC and stores the
`settle` arguments (amount, tokens, intent hash, the guard verdict if one was sent) and the outcome
(ok + return value, or the contract's ERR_ code). The dashboard reads the same data live first and only
uses this copy if every RPC is down. Regular RPC nodes drop transactions after a few days; archival ones don't.
Usage: python3 scripts/snapshot_onchain.py [dashboard/data/verdicts.json]"""
import base64, json, re, sys, urllib.request

RPCS = ["https://archival-rpc.testnet.fastnear.com", "https://archival-rpc.testnet.near.org"]


def tx(h, sender):
    last = None
    for url in RPCS:
        try:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tx",
                               "params": {"tx_hash": h, "sender_account_id": sender, "wait_until": "NONE"}}).encode()
            req = urllib.request.Request(url, body, {"Content-Type": "application/json", "User-Agent": "rugwall-snapshot"})
            r = json.load(urllib.request.urlopen(req, timeout=30))
            if "result" in r:
                return r["result"], url
            last = r.get("error")
        except Exception as e:
            last = e
    raise RuntimeError(f"{h}: {last}")


path = sys.argv[1] if len(sys.argv) > 1 else "dashboard/data/verdicts.json"
d = json.load(open(path))
for s in d["scenarios"]:
    if not s.get("tx"):
        continue
    r, url = tx(s["tx"], d["contract"])
    fc = r["transaction"]["actions"][0]["FunctionCall"]
    st = r["status"]
    err = re.findall(r"ERR_[A-Z_]+", json.dumps(st))
    ret = json.loads(base64.b64decode(st["SuccessValue"]) or "null") if "SuccessValue" in st else None
    s["onchain"] = {"method": fc["method_name"], "args": json.loads(base64.b64decode(fc["args"])),
                    "signer_public_key": r["transaction"]["public_key"], "ok": "SuccessValue" in st,
                    "error": err[0] if err else None, "return": ret, "source": url}
    print(f"{s['scenario']:<26} {s['onchain']['method']} ok={s['onchain']['ok']} err={s['onchain']['error']}")
json.dump(d, open(path, "w"), indent=1)
