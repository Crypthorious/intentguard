"""READ-ONLY NEAR Intents 1Click client (dry quotes only). Opt-in: the demo/tests default to intents_stub.
Calls https://1click.chaindefuser.com/v0/tokens and POST /v0/quote with dry=true. A dry quote returns no deposit
address and moves no funds. No API key needed (keyless quotes carry a small 1Click fee in the quote).
Live check 2026-11-01: 1 wNEAR -> 4.364 USDC dry quote returned with no key; needs a User-Agent header (Cloudflare 1010)."""
import datetime, json, urllib.request

BASE = "https://1click.chaindefuser.com/v0"
HDR = {"Content-Type": "application/json", "User-Agent": "intentguard/0.1"}


def _req(path, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=HDR, method="POST" if data else "GET")
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())


def tokens():
    return _req("/tokens")


def build_dry_request(origin, dest, amount_raw, account="intentguard-demo.near", slippage_bps=100, minutes=10):
    dl = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"dry": True, "swapType": "EXACT_INPUT", "slippageTolerance": slippage_bps, "originAsset": origin,
            "depositType": "INTENTS", "destinationAsset": dest, "amount": str(amount_raw), "refundTo": account,
            "refundType": "INTENTS", "recipient": account, "recipientType": "INTENTS", "deadline": dl}


def parse_quote(resp):
    """Normalise a 1Click quote response to the guard's quote shape plus USD values for an oracle check."""
    q = resp["quote"]
    if not resp.get("quoteRequest", {}).get("dry", False):
        raise ValueError("refusing non-dry quote")
    return {"amount_out": float(q["amountOutFormatted"]), "amount_in_usd": float(q["amountInUsd"]),
            "amount_out_usd": float(q["amountOutUsd"]), "min_amount_out": q.get("minAmountOut"),
            "simulated": False, "dry": True, "source": "1click", "correlation_id": resp.get("correlationId")}


def oracle_deviation_pct(pq):
    """Value lost in the quote vs 1Click's own token price feed (negative = user receives less than fair)."""
    return (pq["amount_out_usd"] / pq["amount_in_usd"] - 1) * 100 if pq["amount_in_usd"] else float("-inf")


def dry_quote(origin, dest, amount_raw, **kw):
    body = build_dry_request(origin, dest, amount_raw, **kw)
    assert body["dry"] is True
    return parse_quote(_req("/quote", body))
