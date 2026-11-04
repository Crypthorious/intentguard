"""VENDORED, UNCHANGED rule functions from wallet_intel/server/score.py (med, metrics, verdict, fmt, confidence,
copy_summary, judge). Only the imports/config header is new: score.py pulls CFG from common.py + SQLite; here the
same `score` config block is inlined so the pure rules run standalone."""
import statistics as st, time
from collections import defaultdict

SC = {"min_closed": 20, "min_realized_usd_track": 500, "min_volume_usd_track": 2000, "copy_delays_s": [15, 60, 300]}
DELAYS = SC.get("copy_delays_s", [15, 60, 300])


def now_iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def med(xs):
    return st.median(xs) if xs else None


def metrics(pos, quote_usd, now):
    closed = [p for p in pos if p["closed"] and p["ret"] is not None]
    opn = [p for p in pos if not p["closed"]]
    rets = [p["ret"] for p in closed]
    pnl = [(p["pnl_q"] or 0) * (quote_usd(p) or 0) for p in closed]
    gp, gl = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x < 0)
    days = defaultdict(float)
    for p, x in zip(closed, pnl):
        d = time.strftime("%Y-%m-%d", time.gmtime((p["sells"][-1][0] if p["sells"] else p["first_ts"])))
        days[d] += x
    srt = sorted([x for x in pnl if x > 0], reverse=True)
    ts_all = [p["first_ts"] for p in pos]
    m = {
        "positions": len(pos), "closed": len(closed), "open": len(opn), "tokens": len({p["token"] for p in pos}),
        "wins": sum(1 for r in rets if r > 0), "win_rate": (sum(1 for r in rets if r > 0) / len(rets)) if rets else None,
        "median_ret_pct": (med(rets) * 100) if rets else None, "mean_ret_pct": (st.mean(rets) * 100) if rets else None,
        "profit_factor": (gp / gl) if gl > 0 else (float("inf") if gp > 0 else None),
        "realized_pnl_usd": sum(pnl), "gross_profit_usd": gp, "gross_loss_usd": gl,
        "best_trade_share": (srt[0] / gp) if gp > 0 else None, "top3_share": (sum(srt[:3]) / gp) if gp > 0 else None,
        "median_hold_s": med([p["hold_s"] for p in closed if p["hold_s"] is not None]),
        "active_days": len(days), "profitable_days_share": (sum(1 for v in days.values() if v > 0) / len(days)) if days else None,
        "open_mtm_usd": sum(((p["mtm"] or 0) - p["cost"] * (1 - p["sold_frac"])) * (quote_usd(p) or 0) for p in opn if p["mtm"] is not None),
        "volume_usd": sum(p["cost"] * (quote_usd(p) or 0) for p in pos),
        "first_trade": now_iso(min(ts_all)) if ts_all else None, "last_trade": now_iso(max(ts_all)) if ts_all else None,
        "history_days": ((max(ts_all) - min(ts_all)) / 86400) if ts_all else 0,
        "transfer_fed_share": sum(1 for p in pos if p["transfer_fed"]) / len(pos) if pos else 0,
        "wash_like_share": (sum(1 for p in closed if p["hold_s"] is not None and p["hold_s"] < 20 and abs(p["ret"]) < 0.02) / len(closed)) if closed else 0,
    }
    return m


def verdict(m, flags, minor, bonus):
    s = 5
    reasons = []
    if m["closed"] >= 20 and (m["profit_factor"] or 0) > 1.5:
        s += 2; reasons.append(f"+2 {m['closed']} closed, PF {fmt(m['profit_factor'])}")
    if (m["median_ret_pct"] or -1) > 0:
        s += 1; reasons.append(f"+1 median return {m['median_ret_pct']:+.1f}%")
    if m["best_trade_share"] is not None and m["best_trade_share"] <= 0.5:
        s += 1; reasons.append(f"+1 best trade {m['best_trade_share'] * 100:.0f}% of profit (not a one-hit)")
    for b in bonus:
        s += 1; reasons.append("+1 " + b)
    for f in flags:
        s -= 2; reasons.append("-2 " + f)
    for f in minor:
        s -= 1; reasons.append("-1 " + f)
    s = max(0, min(10, s))
    v = "TRACK" if s >= 7 else ("WATCH" if s >= 4 else "REJECT")
    if len(flags) >= 2 and v != "REJECT":
        v = "REJECT"; reasons.append(f"REJECT: {len(flags)} serious red flags")
    elif flags and v == "TRACK":
        v = "WATCH"; reasons.append("capped at WATCH: a serious red flag (TRACK needs a clean record)")
    if v == "TRACK" and ((m["realized_pnl_usd"] or 0) < SC.get("min_realized_usd_track", 500) or (m["volume_usd"] or 0) < SC.get("min_volume_usd_track", 2000)):
        v = "WATCH"; reasons.append(f"capped at WATCH: tiny size (realised ${m['realized_pnl_usd'] or 0:,.0f}, volume ${m['volume_usd'] or 0:,.0f})")
    if m["closed"] < SC.get("min_closed", 20) and v == "TRACK":
        v = "WATCH"; reasons.append(f"capped at WATCH: only {m['closed']} closed trades (< {SC.get('min_closed', 20)})")
    return s, v, reasons


def fmt(x):
    if x is None:
        return "n/a"
    if x == float("inf"):
        return "inf"
    return f"{x:.2f}"


def confidence(m, copy_n, flags, partial):
    if m["closed"] >= 40 and m["tokens"] >= 20 and m["history_days"] >= 3 and copy_n >= 20 and not flags and not partial:
        return "HIGH"
    if m["closed"] >= 20 and m["tokens"] >= 10:
        return "MEDIUM"
    return "LOW"


def copy_summary(sims):
    out = {}
    for D in [0] + DELAYS:
        xs = [s[D] for s in sims if s.get(D) is not None]
        out[f"d{D}s"] = {"n": len(xs), "mean_pct": (st.mean(xs) * 100) if xs else None,
                         "median_pct": (med(xs) * 100) if xs else None,
                         "win_rate": (sum(1 for x in xs if x > 0) / len(xs)) if xs else None}
    return out


def judge(m, extra, cs, chain):
    flags, minor, bonus = [], [], []
    if (extra.get("snipe_share") or 0) >= 0.3 and m["positions"] >= 5:
        flags.append(f"first-block sniper/bundler: {(extra.get('snipe_share') or 0) * 100:.0f}% of entries within ~2 s of " + ("launch" if chain == "robinhood" else "migration"))
    if (extra.get("dev_share") or 0) >= 0.2 or ((extra.get("n_deployed") or 0) >= 3 and (extra.get("dev_share") or 0) > 0):
        flags.append(f"dev-linked: trades its own launches ({(extra.get('dev_share') or 0) * 100:.0f}% of positions; deployed {(extra.get('n_deployed') or 0)} tokens)")
    if (m.get("wash_like_share") or 0) >= 0.3:
        flags.append(f"wash-like: {m['wash_like_share'] * 100:.0f}% of closes are <20 s round trips at ~0%")
    if (m.get("transfer_fed_share") or 0) >= 0.3:
        flags.append(f"transfer-fed: sells more than it bought on-market in {m['transfer_fed_share'] * 100:.0f}% of tokens (allocations / linked wallets)")
    cp, cs_share = (extra.get("cluster_partners") or 0), (extra.get("cluster_cobuy_share") or 0)
    farm_share = 0.3 if chain == "robinhood" else 0.5      # RH block ~0.1 s; Solana ts is 1 s, so chance co-buys are likelier
    if cp >= 2 and (extra.get("snipe_share") or 0) >= 0.15:
        flags.append(f"sniper cluster: same-block co-buys with {cp} wallets on >=3 tokens")
    elif cp >= 3 and cs_share >= farm_share:
        flags.append(f"coordinated wallet farm: buys in the same block as {cp} other wallets on up to {cs_share * 100:.0f}% of its tokens "
                     "(one operator / bundle-like; its PnL may be self-made)")
    elif cp >= 2 and cs_share >= 0.15:
        minor.append(f"co-buys in the same block with {cp} wallets on >=3 tokens")
    if (extra.get("precall_buys") or 0) >= 3:
        flags.append(f"buys before Telegram calls: {extra['precall_buys']} called tokens bought <=30 min before the post")
    d15 = cs.get("d15s", {}).get("mean_pct")
    d60 = cs.get("d60s", {}).get("mean_pct")
    if extra.get("mirror_of"):
        flags.append(f"mirrors another wallet: buys the same tokens after {extra['mirror_of']} "
                     f"({extra.get('mirror_common')} shared tokens; copier or staggered sub-wallet of one operator)")
    if extra.get("mirrored_by"):
        minor.append(f"{extra['mirrored_by']} wallet(s) buy the same tokens right after it (copiers or its own sub-wallets): "
                     "fills get crowded")
    m15 = cs.get("d15s", {}).get("median_pct")
    m60 = cs.get("d60s", {}).get("median_pct")
    if d15 is not None and cs["d15s"]["n"] >= 5:
        if d15 < -3 or (m15 is not None and m15 < -5):
            flags.append(f"followers lose to delay: copy at +15 s = mean {d15:+.1f}% / median {fmt(m15)}% per trade "
                         f"(wallet's own price basis {fmt(cs['d0s']['mean_pct'])}%)")
        elif d15 < 0 or (m15 is not None and m15 < 0):
            minor.append(f"copy at +15 s weak (mean {d15:+.1f}%, median {fmt(m15)}% per trade; a few big winners carry it)")
        elif d15 > 3 and (d60 or 0) > 0 and (m60 or 0) >= 0:
            bonus.append(f"copyable edge: +15 s mean {d15:+.1f}% (median {fmt(m15)}%), +60 s mean {d60:+.1f}% per trade")
    elif m["closed"] >= 5:
        minor.append("copyable edge unknown (no price series for its tokens)")
    if (m["median_hold_s"] or 1e9) < 60:
        flags.append(f"too fast to copy: median hold {m['median_hold_s']:.0f} s (a follower is still entering when it exits)")
    elif (m["median_hold_s"] or 1e9) < 120:
        minor.append(f"hyper-turnover (median hold {m['median_hold_s']:.0f} s): copy latency eats the move")
    if d60 is not None and cs["d60s"]["n"] >= 5 and d60 < -3 and not any(f.startswith("followers lose") for f in flags):
        minor.append(f"copy at +60 s negative ({d60:+.1f}%/trade)")
    if (extra.get("early_share") or 0) >= 0.3 and (extra.get("snipe_share") or 0) < 0.2 and not extra.get("dev_share"):
        bonus.append(f"early but not insider: {(extra.get('early_share') or 0) * 100:.0f}% of entries in the first 10 min, few block-0 snipes")
    return flags, minor, bonus


# ------------------------------------------------------------------------------------------------ RH
