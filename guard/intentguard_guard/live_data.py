"""REAL, READ-ONLY market data for the default demo (no keys, no signatures, no funds).

  1. NEAR Intents 1Click: POST /v0/quote with dry=true (oneclick.py). A dry quote has no deposit address.
  2. Ref Finance (v2.ref-finance.near, NEAR mainnet) `get_pool` view: live constant-product reserves for the
     price-sanity check. Pool 4512 is the deepest SIMPLE_POOL for native USDC / wNEAR (checked 2026-11-12).
  3. NEP-148 `ft_metadata` view on each token contract (symbol, decimals), NEAR mainnet.

Every function raises on any error. `demo.py` catches that and falls back to the offline fixtures, printing
`DATA: fixtures (offline fallback: <reason>)` so a reader can always tell which source was used.
Set INTENTGUARD_DATA=fixtures to force the offline path (unit tests do not touch the network)."""
import base64, json, os, time, urllib.request

from . import oneclick

MAINNET_RPCS = [u for u in os.environ.get("NEAR_MAINNET_RPC", "https://free.rpc.fastnear.com,https://rpc.mainnet.near.org").split(",") if u]
REF_CONTRACT = "v2.ref-finance.near"
REF_POOL_USDC_WNEAR = int(os.environ.get("INTENTGUARD_REF_POOL", "4512"))
USDC = "17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1"   # native USDC on NEAR (Circle)
WNEAR = "wrap.near"
HDR = {"Content-Type": "application/json", "User-Agent": "intentguard/0.2"}


def view(account_id, method, args=None, timeout=15):
    """Read-only `call_function` view on NEAR mainnet. Tries each RPC in MAINNET_RPCS."""
    body = {"jsonrpc": "2.0", "id": "ig", "method": "query", "params": {
        "request_type": "call_function", "finality": "final", "account_id": account_id, "method_name": method,
        "args_base64": base64.b64encode(json.dumps(args or {}).encode()).decode()}}
    last = None
    for rpc in MAINNET_RPCS:
        try:
            req = urllib.request.Request(rpc, json.dumps(body).encode(), HDR)
            r = json.load(urllib.request.urlopen(req, timeout=timeout))
            if "error" in r or "error" in r.get("result", {}):
                raise RuntimeError(f"{method}: {r.get('error') or r['result']['error']}")
            return json.loads(bytes(r["result"]["result"]).decode())
        except Exception as e:  # try the next RPC
            last = e
    raise RuntimeError(f"all mainnet RPCs failed for {account_id}.{method}: {last!r}")


def token_metadata(token):
    m = view(token, "ft_metadata")
    return {"token": token, "symbol": m["symbol"], "name": m.get("name"), "decimals": int(m["decimals"]), "source": "ft_metadata"}


def ref_pool(pool_id, token_in, token_out, dec_in, dec_out, usd_per_in=1.0):
    p = view(REF_CONTRACT, "get_pool", {"pool_id": pool_id})
    ids, amts = p["token_account_ids"], [int(a) for a in p["amounts"]]
    if p.get("pool_kind") != "SIMPLE_POOL" or token_in not in ids or token_out not in ids:
        raise RuntimeError(f"Ref pool {pool_id} is not a {token_in}/{token_out} simple pool")
    r_in, r_out = amts[ids.index(token_in)] / 10 ** dec_in, amts[ids.index(token_out)] / 10 ** dec_out
    if r_in <= 0 or r_out <= 0:
        raise RuntimeError(f"Ref pool {pool_id} is empty")
    return {"reserve_in": r_in, "reserve_out": r_out, "fee": p["total_fee"] / 10_000,
            "liquidity_usd": 2 * r_in * usd_per_in, "source": f"ref-finance pool {pool_id} (mainnet, read-only)",
            "pool_id": pool_id, "fetched_at": int(time.time())}


def snapshot(amounts_usd=(50,)):
    """One read of everything the default demo needs, for USDC -> wNEAR. Raises on any failure."""
    t0 = time.time()
    meta_in, meta_out = token_metadata(USDC), token_metadata(WNEAR)
    pool = ref_pool(REF_POOL_USDC_WNEAR, USDC, WNEAR, meta_in["decimals"], meta_out["decimals"])
    quotes = {}
    for usd in amounts_usd:
        q = oneclick.dry_quote("nep141:" + USDC, "nep141:" + WNEAR, int(round(usd * 10 ** meta_in["decimals"])))
        q["source"] = "1click dry quote (mainnet solvers, dry=true, read-only)"
        quotes[usd] = q
    return {"meta_in": meta_in, "meta_out": meta_out, "pool": pool, "quotes": quotes, "elapsed_s": round(time.time() - t0, 2)}
