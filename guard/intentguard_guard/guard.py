"""IntentGuard off-chain guard. evaluate(proposal, ctx) -> verdict dict. Fail-closed: any error -> DENY.

Checks (each reuses existing paper-trading code, see vendor/):
  1 risk       vendor/risk_gate.check (kill file, notional cap, open positions, daily loss, trades/day)
               + per-agent caps / kill switch read from the IntentGuard contract (ContractSim or testnet view)
  2 launch     vendor/launch_safety.decide (rugcheck-shaped report: authorities, LP lock, insiders, holders,
               creator bag, liquidity, two-way trading) - skipped only for allowlisted majors
  3 price      quote vs constant-product fair price from pool reserves (vendor/pool_reserve for V4 sqrtPrice)
  4 reputation vendor/wallet_score.judge + verdict on the copied signal wallet (score >= min, not REJECT)

On ALLOW, if ctx carries a `signer` (verdict.GuardSigner) and a `contract_id`, the guard signs an ed25519 verdict
over (contract, agent, intent hash, amount, token_in, token_out, expiry, nonce). The contract refuses any `settle`
without a valid, fresh, unused verdict, so an agent that skips the guard cannot settle even inside its caps.
DENY verdicts are never signed.
"""
import hashlib, json, os, time, traceback
from .vendor import risk_gate, launch_safety, wallet_score, pool_reserve

DEFAULT_CFG = {
    "allowlisted_tokens": ["usdc.near", "wrap.near", "eth.bridge.near"],
    "max_price_deviation_pct": 2.0,
    "min_pool_liquidity_usd": 12000.0,
    "min_wallet_score": 6,
    "launch_max_age_min": 10 ** 9,
    "risk_gate": {
        "max_notional_usd": 100.0, "min_notional_usd": 1.0, "max_notional_pct_equity": 0.25, "max_leverage": 1.0,
        "require_stop": False, "max_loss_per_trade_usd": 1e9, "max_loss_per_trade_pct": 1.0, "min_reward_risk": 0,
        "assumed_rr_no_tp": {}, "taker_fee": 0.0, "slippage": 0.0, "max_open_positions": 5, "max_trades_per_day": 20,
        "btc_beta_symbols": [], "max_correlated_same_dir_notional_usd": 1e9, "max_correlated_same_dir_positions": 99,
        "daily_loss_stop_usd": 50.0, "daily_loss_stop_pct": 0.05, "weekly_drawdown_stop_pct": 0.15,
        "consecutive_loss_limit": 3, "consecutive_loss_cooldown_h": 24, "no_reentry_after_stop_same_day": True,
        "market": {"enabled": False}, "live": {}, "kill_file": "/nonexistent/KILL",
    },
}


def check_risk(p, ctx, cfg):
    R = []
    rcfg = dict(cfg["risk_gate"])
    if ctx.get("kill_file"):
        rcfg["kill_file"] = ctx["kill_file"]
    order = {"book": "intentguard", "symbol": p["token_out"], "side": "long", "entry": float(p.get("ref_price") or 1.0),
             "notional": float(p["amount_usd"]), "equity": float(ctx["treasury_usd"]), "mode": "shadow", "ts": p.get("ts")}
    v = risk_gate.check(order, ctx.get("book_state") or {}, rcfg, market="skip")
    R += [f"risk_gate: {r}" for r in v["reasons"]]
    c = ctx.get("contract")
    if c is not None:  # caps, pause, and kill switch from the contract, checked before signing.
        # The stored spent_in_window is used as-is. The contract's 24h reset is not applied here,
        # so after a window rollover this check can deny a settle the contract would accept.
        if c.kill_switch:
            R.append("contract: kill switch ON")
        pol = c.get_policy(p["agent"])
        amt = int(round(float(p["amount_usd"]) * 1e6))
        if pol is None:
            R.append(f"contract: agent {p['agent']} not registered")
        else:
            if pol["paused"]:
                R.append("contract: agent paused")
            if amt > pol["per_tx_cap"]:
                R.append(f"contract: per-tx cap {amt/1e6:.2f} > {pol['per_tx_cap']/1e6:.2f} USD")
            if pol["spent_in_window"] + amt > pol["daily_cap"]:
                R.append(f"contract: daily cap {(pol['spent_in_window']+amt)/1e6:.2f} > {pol['daily_cap']/1e6:.2f} USD")
    return R, v["metrics"]


def check_launch(p, cfg, now):
    if p["token_out"] in cfg["allowlisted_tokens"]:
        return [], {"skipped": "allowlisted major"}
    rep = p.get("token_report")
    if not rep:
        return ["launch: no token safety report (fail-closed)"], {}
    ok, reasons, info = launch_safety.decide(rep, max_age_min=cfg["launch_max_age_min"], now=now)
    return ([] if ok else [f"launch: {r}" for r in reasons]), info


def fair_out(amount_in, pool):
    fee = pool.get("fee", 0.003)
    if "sqrt_price_x96" in pool:   # Uniswap-V4 style pool: mid from sqrtPrice (vendored), no curve
        mid = pool_reserve.mid_tokens_per_eth_raw(pool["sqrt_price_x96"])
        return amount_in * (1 - fee) * mid
    a = amount_in * (1 - fee)
    return pool["reserve_out"] * a / (pool["reserve_in"] + a)


def check_price(p, cfg):
    pool, q = p.get("pool"), p.get("quote")
    if not pool or not q:
        return ["price: pool reserves or quote missing (fail-closed)"], {}
    fair = fair_out(float(p["amount_in"]), pool)
    dev = (float(q["amount_out"]) / fair - 1) * 100
    m = {"fair_out": fair, "quote_out": q["amount_out"], "deviation_pct": round(dev, 3)}
    R = []
    if abs(dev) > cfg["max_price_deviation_pct"]:
        R.append(f"price: quote deviates {dev:+.2f}% from pool-reserve fair price (> {cfg['max_price_deviation_pct']}%)")
    liq = pool.get("liquidity_usd")
    if liq is None and "liquidity" in pool and "sqrt_price_x96" in pool:
        liq = pool_reserve.onchain_liq_usd(pool, pool.get("eth_usd", 0))
    m["liquidity_usd"] = liq
    if liq is None or liq < cfg["min_pool_liquidity_usd"]:
        R.append(f"price: pool liquidity {liq} < {cfg['min_pool_liquidity_usd']} USD")
    return R, m


def check_reputation(p, cfg):
    sw = p.get("signal_wallet")
    if not sw:
        return [], {"skipped": "no copied wallet"}
    flags, minor, bonus = wallet_score.judge(sw["metrics"], sw.get("extra", {}), sw.get("copy_summary", {}), sw.get("chain", "solana"))
    s, v, why = wallet_score.verdict(sw["metrics"], flags, minor, bonus)
    R = []
    if v == "REJECT" or s < cfg["min_wallet_score"]:
        R.append(f"reputation: signal wallet {sw.get('address')} score {s}/10 {v} (< {cfg['min_wallet_score']} or REJECT)")
    return R, {"score": s, "verdict": v, "why": why}


def amount_raw(p):
    """Settlement amount in the quote asset's smallest unit (USDC, 6 dp), as the contract sees it."""
    return int(round(float(p["amount_usd"]) * 1e6))


def intent_hash(p):
    """sha256 over the fields the agent proposed and the guard checked (the quote included)."""
    core = {k: p.get(k) for k in ("agent", "token_in", "token_out", "amount_in", "amount_usd")}
    core["quote_amount_out"] = (p.get("quote") or {}).get("amount_out")
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def evaluate(p, ctx, cfg=None, audit_path=None):
    cfg = cfg or DEFAULT_CFG
    now = ctx.get("now", time.time())
    out = {"proposal_id": p.get("id"), "agent": p.get("agent"), "checks": {}, "reasons": []}
    try:
        for name, fn in (("risk", lambda: check_risk(p, ctx, cfg)), ("launch", lambda: check_launch(p, cfg, now)),
                         ("price", lambda: check_price(p, cfg)), ("reputation", lambda: check_reputation(p, cfg))):
            r, m = fn()
            out["checks"][name] = {"pass": not r, "reasons": r, "metrics": m}
            out["reasons"] += r
    except Exception as e:
        out["reasons"].append(f"guard_error (fail-closed): {e!r}")
        out["trace"] = traceback.format_exc(limit=3)
    out["allow"] = not out["reasons"]
    out["verdict"] = "ALLOW" if out["allow"] else "DENY"
    if out["allow"] and ctx.get("signer") is not None and ctx.get("contract_id"):
        try:
            out["intent_hash"] = intent_hash(p)
            out["amount_raw"] = amount_raw(p)
            out["signed_verdict"] = ctx["signer"].sign(ctx["contract_id"], p["agent"], out["intent_hash"], out["amount_raw"],
                                                       p["token_in"], p["token_out"], now_ns=ctx.get("verdict_now_ns"),
                                                       ttl_ns=ctx.get("verdict_ttl_ns", 120 * 10**9))
            out["guard_public_key"] = ctx["signer"].public_key
        except Exception as e:  # fail closed: no signature -> treated as DENY
            out["allow"], out["verdict"] = False, "DENY"
            out["reasons"].append(f"guard_error (fail-closed): could not sign verdict: {e!r}")
    out["data_sources"] = {k: (p.get(k) or {}).get("source") for k in ("quote", "pool") if isinstance(p.get(k), dict)}
    if audit_path:
        os.makedirs(os.path.dirname(audit_path) or ".", exist_ok=True)
        with open(audit_path, "a") as f:
            f.write(json.dumps(out, default=str) + "\n")
    return out
