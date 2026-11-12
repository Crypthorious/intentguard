#!/usr/bin/env python3
"""Turn a live testnet demo export (INTENTGUARD_EXPORT=...) into dashboard/data/verdicts.json.

near-cli-rs does not print the hash of a FAILED transaction, so this fills the hashes of the rejected
`settle` calls (scenarios 8-13) from the public NearBlocks v3 testnet API (read-only, no key), matching them
in time order, and confirms each one's error code from the transaction outcome over public RPC.
Usage: python3 scripts/build_dashboard_data.py /tmp/rw/verdicts.json [dashboard/data/verdicts.json]"""
import json, re, sys, urllib.request

NB = "https://api-testnet.nearblocks.io/v3/accounts/{}/txns?limit=50"
RPC = "https://rpc.testnet.near.org"


def get(url, body=None):
    req = urllib.request.Request(url, json.dumps(body).encode() if body else None,
                                 {"Content-Type": "application/json", "User-Agent": "rugwall-dashboard-build"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def tx_error(h, sender):
    r = get(RPC, {"jsonrpc": "2.0", "id": 1, "method": "tx", "params": {"tx_hash": h, "sender_account_id": sender, "wait_until": "FINAL"}})
    m = re.findall(r"ERR_[A-Z_]+", json.dumps(r))
    return m[0] if m else None


src = json.load(open(sys.argv[1]))
dst = sys.argv[2] if len(sys.argv) > 2 else "dashboard/data/verdicts.json"
contract = src["contract"]
txs = sorted(get(NB.format(contract))["data"], key=lambda t: int(t["block_timestamp"]))
start_ns = (src["scenarios"][0]["ts"] - 30) * 10**9
failed = [t for t in txs if int(t["block_timestamp"]) >= start_ns and not t["outcomes"]["status"]
          and any(a.get("method") == "settle" for a in t["actions"])]
bypass = [s for s in src["scenarios"] if s.get("kind") == "bypass"]
for s, t in zip(bypass, failed[-len(bypass):] if len(failed) >= len(bypass) else []):
    s["tx"] = t["transaction_hash"]
    s["onchain_error"] = tx_error(t["transaction_hash"], t["signer_account_id"])
for s in src["scenarios"]:
    if isinstance(s.get("settle"), dict) and s["settle"].get("tx"):
        s["tx"] = s["settle"]["tx"]
    elif s.get("kind") == "guard":
        s.pop("tx", None)   # guard DENY never reaches the chain
src["failed_tx_matched"] = sum(1 for s in bypass if s.get("tx"))
json.dump(src, open(dst, "w"), indent=1)
print(f"wrote {dst}: {len(src['scenarios'])} scenarios, {src['failed_tx_matched']}/{len(bypass)} rejected txs matched")
for s in bypass:
    print(f"  {s['scenario']:<26} expected {s['expected']:<20} on-chain {s.get('onchain_error')}  {s.get('tx')}")
