"""Pre-trade RISK GATE (PAPER/SHADOW; never places orders, never reads keys).

Every future LIVE order must call  check(order) -> {"allow": bool, "reasons": [...], ...}
before it is sent.  Fail-closed: any missing input / exception -> deny.

order = {"book": "breakout", "symbol": "SOLUSDT", "side": "long"|"short", "entry": float,
         "stop": float, "tp": float|None, "notional": float (USD), "equity": float (account USD),
         "leverage": optional (computed = notional/equity if absent), "mode": "live"|"shadow",
         "ts": ISO-8601 Z (optional, default now)}
"""
import json, os, time, threading, urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
# This package stores the vendored config as risk_gate_config.json (there is no config.json).
CONFIG = os.environ.get("RISK_GATE_CONFIG", os.path.join(HERE, "risk_gate_config.json"))
_lock = threading.Lock()


def load_config(path=None):
    with open(path or CONFIG) as f:
        return json.load(f)


def parse_ts(v):
    if v is None:
        return datetime.now(timezone.utc)
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ account state from a ledger
def read_jsonl(path):
    out = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return out


def book_state(events, at=None, scale_notional=None, equity=None):
    """Replay open/close events strictly before `at`.  scale_notional: re-size every trade to
    min(notional, scale_notional) (P/L scaled by the same factor) = 'what stage-1 sizing would have seen'."""
    at = parse_ts(at) if at is not None else datetime.now(timezone.utc)
    day0 = at.replace(hour=0, minute=0, second=0, microsecond=0)
    wk0 = at - timedelta(days=7)
    open_pos, scale_of = {}, {}
    closes = []
    trades_today = 0
    for e in events:
        t = e.get("type")
        if t not in ("open", "close"):
            continue
        ts = parse_ts(e.get("ts"))
        if ts >= at:
            break
        sym = e.get("symbol")
        if t == "open":
            n = float(e.get("notional") or 0)
            f = min(1.0, scale_notional / n) if (scale_notional and n > 0) else 1.0
            scale_of[sym] = f
            open_pos[sym] = {"symbol": sym, "side": e.get("side"), "notional": n * f, "opened": e.get("ts")}
            if ts >= day0:
                trades_today += 1
        else:
            f = scale_of.pop(sym, 1.0)
            open_pos.pop(sym, None)
            closes.append({"ts": ts, "symbol": sym, "pnl": float(e.get("pnl") or 0) * f,
                           "reason": e.get("reason"), "r": e.get("r_multiple")})
    today = [c for c in closes if c["ts"] >= day0]
    realized_today = sum(c["pnl"] for c in today)
    # weekly drawdown: peak-to-now of cumulative realized P/L over the last 7 days, vs equity
    cum, peak, wk = 0.0, 0.0, [c for c in closes if c["ts"] >= wk0]
    for c in wk:
        cum += c["pnl"]
        peak = max(peak, cum)
    week_dd_usd = max(peak - cum, -cum, 0.0)
    consec, last_loss = 0, None
    for c in reversed(closes):
        if c["pnl"] < 0:
            consec += 1
            last_loss = last_loss or c["ts"]
        else:
            break
    stopped_today = sorted({c["symbol"] for c in today if c["pnl"] < 0 and (c["reason"] or "").startswith("stop")})
    return {"open_positions": list(open_pos.values()), "realized_today": round(realized_today, 6),
            "week_drawdown_usd": round(week_dd_usd, 6), "consecutive_losses": consec,
            "last_loss_ts": iso(last_loss) if last_loss else None, "trades_today": trades_today,
            "stopped_today": stopped_today, "closed_trades": len(closes), "equity": equity}


# ------------------------------------------------------------------ public market data (read-only)
_mcache = {"t": 0, "data": None}


def fetch_market(cfg, force=False):
    """Bulk Bybit linear tickers (public). Returns {symbol: {...}} or None on failure."""
    m = cfg.get("market", {})
    with _lock:
        if not force and _mcache["data"] and time.time() - _mcache["t"] < m.get("cache_s", 30):
            return _mcache["data"]
    try:
        req = urllib.request.Request("https://api.bybit.com/v5/market/tickers?category=linear",
                                     headers={"User-Agent": "risk-gate/1 (paper)"})
        with urllib.request.urlopen(req, timeout=8) as r:
            j = json.load(r)
        now = time.time()
        out = {}
        for x in j["result"]["list"]:
            try:
                out[x["symbol"]] = {"bid": float(x["bid1Price"]), "ask": float(x["ask1Price"]),
                                    "mark": float(x["markPrice"]), "turnover24h": float(x["turnover24h"]),
                                    "oi_usd": float(x.get("openInterestValue") or 0),
                                    "funding": float(x.get("fundingRate") or 0), "fetched": now}
            except Exception:
                pass
        with _lock:
            _mcache.update(t=now, data=out)
        return out
    except Exception:
        return None


# ------------------------------------------------------------------ the gate
def _f(order, k):
    v = order.get(k)
    return None if v is None else float(v)


def check(order, state, cfg, market=None, now=None, paper_closed=None):
    """Pure rule evaluation. market: ticker dict for the symbol, None = unavailable, "skip" = not
    evaluated (historical shadow replay). paper_closed: closed paper trades of this book (live flag)."""
    reasons, warns, metrics = [], [], {}
    now = now or time.time()
    try:
        mode = order.get("mode", "live")
        book, sym, side = order.get("book"), order.get("symbol"), order.get("side")
        entry, stop, tp = _f(order, "entry"), _f(order, "stop"), _f(order, "tp")
        notional, equity = _f(order, "notional"), _f(order, "equity")
        if not sym or side not in ("long", "short") or not entry or entry <= 0 or not notional or notional <= 0 or not equity or equity <= 0:
            return _verdict(False, ["bad_order: need symbol, side long/short, entry>0, notional>0, equity>0"], warns, metrics, mode)
        # 1 kill switch
        if os.path.exists(cfg["kill_file"]):
            reasons.append(f"KILL: {cfg['kill_file']} exists (blocks everything)")
        # 2 live-enable flag
        if mode == "live":
            lv = cfg["live"]
            if not os.path.exists(lv["approved_file"]):
                reasons.append(f"live_not_approved: {lv['approved_file']} missing (user OK file)")
            if paper_closed is None or paper_closed < lv["min_paper_closed_trades"]:
                reasons.append(f"live_paper_track: {paper_closed} closed paper trades < {lv['min_paper_closed_trades']}")
            if book not in lv["allowed_books"]:
                reasons.append(f"live_book_not_allowed: {book} (allowed {lv['allowed_books']})")
            if sym not in lv["allowed_symbols"]:
                reasons.append(f"live_symbol_not_allowed: {sym}")
        # 3 notional
        cap = min(cfg["max_notional_usd"], cfg["max_notional_pct_equity"] * equity)
        metrics["notional"] = round(notional, 4)
        if notional > cap + 1e-9:
            reasons.append(f"max_notional: ${notional:.2f} > ${cap:.2f}")
        if notional < cfg.get("min_notional_usd", 0) - 1e-9:
            reasons.append(f"min_notional: ${notional:.2f} < ${cfg['min_notional_usd']:.2f} (venue minimum)")
        # 4 leverage
        lev = _f(order, "leverage")
        lev = max(lev or 0, notional / equity)
        metrics["leverage"] = round(lev, 4)
        if lev > cfg["max_leverage"] + 1e-9:
            reasons.append(f"max_leverage: {lev:.2f}x > {cfg['max_leverage']}x")
        # 5 stop present + correct side
        stop_ok = stop is not None and stop > 0 and ((side == "long" and stop < entry) or (side == "short" and stop > entry))
        if cfg.get("require_stop", True) and not stop_ok:
            reasons.append(f"stop_missing_or_wrong_side: stop={stop} entry={entry} side={side}")
        qty = notional / entry
        fees = notional * 2 * (cfg["taker_fee"] + cfg["slippage"])
        if stop_ok:
            # 6 max loss per trade (stop distance x size + round-trip costs)
            loss = qty * abs(entry - stop) + fees
            lim = min(cfg["max_loss_per_trade_usd"], cfg["max_loss_per_trade_pct"] * equity)
            metrics["max_loss_usd"] = round(loss, 4)
            if loss > lim + 1e-9:
                reasons.append(f"max_loss_per_trade: ${loss:.2f} (stop {abs(entry-stop)/entry*100:.2f}% x ${notional:.2f} + fees) > ${lim:.2f}")
            # 7 reward:risk (net of round-trip costs)
            risk = qty * abs(entry - stop)
            if tp is not None and tp > 0:
                if (side == "long" and tp <= entry) or (side == "short" and tp >= entry):
                    reasons.append("tp_wrong_side")
                    rr = 0.0
                else:
                    rr = (qty * abs(tp - entry) - fees) / (risk + fees)
            else:
                a = (cfg.get("assumed_rr_no_tp") or {}).get(book)
                if a is None:
                    rr = None
                    reasons.append("reward_risk: no tp and no assumed_rr_no_tp for this book")
                else:
                    rr = (a * risk - fees) / (risk + fees)
                    warns.append(f"no tp (trailing exit): R:R uses assumed {a}R for {book}")
            if rr is not None:
                metrics["rr_net"] = round(rr, 3)
                if rr < cfg["min_reward_risk"] - 1e-9:
                    reasons.append(f"min_reward_risk: {rr:.2f} < {cfg['min_reward_risk']} (net of fees)")
        # 8 open positions
        ops = state.get("open_positions") or []
        if any(p["symbol"] == sym for p in ops):
            reasons.append(f"already_open: {sym}")
        if len(ops) >= cfg["max_open_positions"]:
            reasons.append(f"max_open_positions: {len(ops)} open >= {cfg['max_open_positions']}")
        # 9 correlated exposure (same direction across BTC-beta coins)
        beta = set(cfg["btc_beta_symbols"])
        if sym in beta:
            same = [p for p in ops if p["symbol"] in beta and p["side"] == side]
            tot = sum(p["notional"] for p in same) + notional
            metrics["corr_same_dir_notional"] = round(tot, 2)
            if len(same) + 1 > cfg["max_correlated_same_dir_positions"]:
                reasons.append(f"correlated_positions: {len(same)+1} same-dir {side} BTC-beta > {cfg['max_correlated_same_dir_positions']}")
            if tot > cfg["max_correlated_same_dir_notional_usd"] + 1e-9:
                reasons.append(f"correlated_notional: ${tot:.2f} same-dir {side} BTC-beta > ${cfg['max_correlated_same_dir_notional_usd']:.2f}")
        # 10 daily realized loss stop
        dl = min(cfg["daily_loss_stop_usd"], cfg["daily_loss_stop_pct"] * equity)
        rt = state.get("realized_today") or 0.0
        metrics["realized_today"], metrics["daily_stop"] = round(rt, 4), round(-dl, 4)
        if rt <= -dl + 1e-9:
            reasons.append(f"daily_loss_stop: realized today ${rt:.2f} <= -${dl:.2f}")
        # 11 weekly drawdown stop
        wd = state.get("week_drawdown_usd") or 0.0
        if wd >= cfg["weekly_drawdown_stop_pct"] * equity - 1e-9 and wd > 0:
            reasons.append(f"weekly_drawdown_stop: 7d realized DD ${wd:.2f} >= {cfg['weekly_drawdown_stop_pct']*100:.0f}% of ${equity:.2f}")
        # 12 consecutive-loss cooldown
        cl = state.get("consecutive_losses") or 0
        if cl >= cfg["consecutive_loss_limit"] and state.get("last_loss_ts"):
            until = parse_ts(state["last_loss_ts"]) + timedelta(hours=cfg["consecutive_loss_cooldown_h"])
            t_now = parse_ts(order.get("ts")) if order.get("ts") else datetime.fromtimestamp(now, timezone.utc)
            if t_now < until:
                reasons.append(f"loss_cooldown: {cl} losses in a row, cooling down until {iso(until)}")
        # 13 no re-entry after a stop-out on the same symbol, same UTC day (Risk rule)
        if cfg.get("no_reentry_after_stop_same_day") and sym in (state.get("stopped_today") or []):
            reasons.append(f"reentry_after_stop: {sym} stopped out today (UTC)")
        # 14 trades per day
        if (state.get("trades_today") or 0) >= cfg["max_trades_per_day"]:
            reasons.append(f"max_trades_per_day: {state.get('trades_today')} >= {cfg['max_trades_per_day']}")
        # 15 market sanity (public data, fail-closed)
        mc = cfg.get("market", {})
        if mc.get("enabled", True):
            if market == "skip":
                warns.append("market checks skipped (historical replay)")
            elif not market:
                reasons.append(f"market_data_unavailable: {sym} (fail-closed)")
            else:
                age = now - market.get("fetched", 0)
                bid, ask = market["bid"], market["ask"]
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
                spread = (ask - bid) / mid * 1e4 if mid else 1e9
                metrics.update(spread_bps=round(spread, 2), turnover24h=round(market["turnover24h"]),
                               oi_usd=round(market["oi_usd"]), funding=market["funding"])
                if age > mc["max_data_age_s"]:
                    reasons.append(f"market_data_stale: {age:.0f}s > {mc['max_data_age_s']}s")
                if spread > mc["max_spread_bps"]:
                    reasons.append(f"spread: {spread:.1f}bp > {mc['max_spread_bps']}bp")
                if market["turnover24h"] < mc["min_turnover_24h_usd"]:
                    reasons.append(f"liquidity: 24h turnover ${market['turnover24h']/1e6:.1f}M < ${mc['min_turnover_24h_usd']/1e6:.0f}M")
                if market["oi_usd"] < mc["min_open_interest_usd"]:
                    reasons.append(f"open_interest: ${market['oi_usd']/1e6:.1f}M < ${mc['min_open_interest_usd']/1e6:.0f}M")
                if abs(market["funding"]) > mc["max_abs_funding_rate"]:
                    reasons.append(f"funding: |{market['funding']*100:.3f}%| > {mc['max_abs_funding_rate']*100:.3f}% per interval")
                if mid and abs(entry - mid) / mid * 100 > mc["max_price_deviation_pct"]:
                    reasons.append(f"price_deviation: entry {entry} vs mid {mid:.6g} > {mc['max_price_deviation_pct']}%")
        return _verdict(not reasons, reasons, warns, metrics, mode)
    except Exception as e:  # fail closed
        return _verdict(False, reasons + [f"gate_error: {e!r}"[:300]], warns, metrics, order.get("mode", "live"))


def _verdict(allow, reasons, warns, metrics, mode):
    return {"allow": bool(allow), "verdict": "ALLOW" if allow else "DENY", "reasons": reasons,
            "warnings": warns, "metrics": metrics, "mode": mode}


def audit(rec, cfg):
    p = cfg["audit_log"]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with _lock, open(p, "a") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def paper_closed_count(cfg, book):
    p = cfg["paper_books"].get(book)
    return sum(1 for e in read_jsonl(p) if e.get("type") == "close") if p else 0


def check_order(order, cfg=None, log=True, state=None, market=None):
    """High-level entry point for live bots: builds account state from the LIVE ledger, fetches
    public market data, evaluates, writes the audit log. Returns the verdict dict."""
    try:
        cfg = cfg or load_config()
        order = dict(order)
        order.setdefault("mode", "live")
        order.setdefault("ts", iso(datetime.now(timezone.utc)))
        if state is None:
            src = cfg["live"]["ledger"] if order["mode"] == "live" else cfg["paper_books"].get(order.get("book"), "")
            state = book_state(read_jsonl(src), at=order["ts"])
        if market is None:
            mk = fetch_market(cfg)
            market = (mk or {}).get(order.get("symbol"))
        v = check(order, state, cfg, market=market, paper_closed=paper_closed_count(cfg, order.get("book")))
    except Exception as e:
        v = _verdict(False, [f"gate_error: {e!r}"[:300]], [], {}, (order or {}).get("mode", "live"))
    v["order"] = {k: order.get(k) for k in ("book", "symbol", "side", "entry", "stop", "tp", "notional", "equity", "ts", "mode")}
    v["checked_at"] = iso(datetime.now(timezone.utc))
    if log and cfg:
        try:
            audit(v, cfg)
        except Exception:
            pass
    return v
