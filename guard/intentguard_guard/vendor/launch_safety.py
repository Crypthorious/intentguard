"""safety.py - shared buy-safety checks for watcher.py (no key, read-only, network via free APIs).

Rules (per user's sniper routine; DO NOT loosen):
  * fresh pump.fun -> PumpSwap (pump_fun_amm) launch, pair age < MAX_AGE_MIN (15; 60 only for smart-wallet candidates)
  * every market LP 100% locked/burned (rugcheck lpLockedPct >= 99.9)
  * no mint authority, no freeze authority, no risky Token-2022 extensions
  * no insiders (graphInsidersDetected / insiderNetworks / insider topHolders) and no RugCheck risks
    (any 'danger'; any 'warn' except ALLOWED_WARN), not rugged
  * top non-pool holder < 5% of supply
  * two-way trading: buys AND sells present (m5, else h1)
  * chase rule: skip if m5 price change > CHASE_M5_PCT or h1 > CHASE_H1_PCT
Decision logic (decide()) is pure and unit-tested; fetch_*() gather data with 429 backoff.
"""
import json, threading, time
import requests

UA = {"User-Agent": "curl/8.5.0", "Accept": "*/*"}
RUG = "https://api.rugcheck.xyz/v1/tokens/{m}/report"
DEX = "https://api.dexscreener.com/tokens/v1/solana/{m}"
PUMP_TRADES = "https://swap-api.pump.fun/v2/coins/{m}/trades?limit=100&cursor=0&minSolAmount=0"

MAX_AGE_MIN = 15
SMART_MAX_AGE_MIN = 60
TOP_HOLDER_MAX_PCT = 5.0
LP_LOCK_MIN_PCT = 99.9
CHASE_M5_PCT = 60.0      # skip if price already +60% in 5 min
CHASE_H1_PCT = 200.0     # ... or +200% in 1 h  (no chase constant found in existing code; see README)
ALLOWED_WARN = {"Low Liquidity", "Low amount of LP Providers"}
RISKY_EXT = ("permanentDelegate", "transferHook", "transferFeeConfig", "defaultAccountState", "nonTransferable",
             "pausableConfig", "confidentialTransferMint", "mintCloseAuthority")
POOL_TYPES = ("AMM", "LOCKER")
# 2026-10-09 rug filter additions (paper book 6W/26L, 6 losses gapped -40..-97%): stricter, never looser
MIN_LIQ_USD = 12000.0          # pool liquidity floor (RugCheck totalMarketLiquidity, else DexScreener liquidity.usd)
TOP10_MAX_PCT = 30.0           # top-10 non-pool holders combined < 30% of supply (clustered dump wallets)
CREATOR_MAX_PCT = 2.0          # creator (dev) wallet still holding >= 2% of supply -> dump risk
MIN_HOLDERS = 150              # RugCheck totalHolders floor (when reported)

# ---------------------------------------------------------------- polite HTTP with per-host spacing + 429 backoff
_host_next = {}
_host_lock = threading.Lock()
SPACING = {"api.rugcheck.xyz": 1.5, "api.dexscreener.com": 1.2, "swap-api.pump.fun": 0.5, "gmgn.ai": 2.0,
           "frontend-api-v3.pump.fun": 0.5}

def get_json(url, tries=4, timeout=15):
    host = url.split("/")[2]
    delay = 3.0
    for i in range(tries):
        with _host_lock:
            wait = _host_next.get(host, 0) - time.time()
            _host_next[host] = max(time.time(), _host_next.get(host, 0)) + SPACING.get(host, 1.0)
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
        except requests.RequestException as e:
            err = f"{type(e).__name__}"
        else:
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    err = "bad json"
            elif r.status_code == 429 or r.status_code >= 500:
                err = f"HTTP {r.status_code}"
                with _host_lock:  # push the whole host back
                    _host_next[host] = time.time() + delay * 2
            else:
                raise RuntimeError(f"{host} HTTP {r.status_code}")
        time.sleep(delay); delay *= 2
    raise RuntimeError(f"{host} unavailable ({err})")

# ---------------------------------------------------------------- data gathering
def fetch(mint, first_seen_ts=None):
    """Gather everything decide() needs. Never raises; errors land in d['errors']."""
    d = {"mint": mint, "errors": [], "fetched_at": time.time(), "first_seen_ts": first_seen_ts}
    try:
        d["rug"] = get_json(RUG.format(m=mint))
    except Exception as e:
        d["errors"].append(f"rugcheck: {e}")
    try:
        j = get_json(DEX.format(m=mint))
        j = j if isinstance(j, list) else (j.get("pairs") or [])
        d["pairs"] = [p for p in j if p.get("chainId") == "solana"]
    except Exception as e:
        d["errors"].append(f"dexscreener: {e}")
    if not d.get("pairs"):
        try:  # fallback for two-way/chase: pump.fun's own trade feed
            d["pump_trades"] = get_json(PUMP_TRADES.format(m=mint)).get("trades") or []
        except Exception as e:
            d["errors"].append(f"pump trades: {e}")
    return d

def _pump_trade_stats(trades, now):
    """From pump.fun trades (newest first): buys/sells in 5m & 1h and price change % over those windows."""
    out = {}
    def ts(t):
        return time.mktime(time.strptime(t["timestamp"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    rows = []
    for t in trades:
        try:
            rows.append((ts(t), t["type"], float(t["priceSol"])))
        except Exception:
            continue
    if not rows:
        return None
    cur = rows[0][2]
    for name, win in (("m5", 300), ("h1", 3600)):
        w = [r for r in rows if now - r[0] <= win]
        out[f"buys_{name}"] = sum(1 for r in w if r[1] == "buy")
        out[f"sells_{name}"] = sum(1 for r in w if r[1] == "sell")
        old = w[-1][2] if w else None
        # only trust the window if the 100-trade page actually reaches back that far
        covered = (now - rows[-1][0]) >= win * 0.8 or len(rows) < 100
        out[f"chg_{name}"] = (cur / old - 1) * 100 if (old and covered) else ((cur / old - 1) * 100 if old else None)
    return out

# ---------------------------------------------------------------- pure decision
def decide(d, max_age_min=MAX_AGE_MIN, now=None):
    """-> (ok: bool, reasons: list[str], info: dict). Fails CLOSED on any missing data."""
    now = now or time.time()
    R, info = [], {"mint": d.get("mint")}
    rug = d.get("rug")
    if not rug:
        return False, ["rugcheck report unavailable"] + d.get("errors", []), info
    meta = rug.get("tokenMeta") or {}
    info.update(name=meta.get("name"), symbol=meta.get("symbol"), creator=rug.get("creator"))
    tok = rug.get("token") or {}
    # authorities / extensions
    if rug.get("mintAuthority") or tok.get("mintAuthority"):
        R.append("mint authority present")
    if rug.get("freezeAuthority") or tok.get("freezeAuthority"):
        R.append("freeze authority present")
    ext = rug.get("token_extensions") or {}
    def _set(v):
        if isinstance(v, dict):
            return any(x not in (None, False, 0, "", {}, []) for x in v.values())
        return v not in (None, False, 0, "", [])
    ext_names = [k for k, v in ext.items() if _set(v)] if isinstance(ext, dict) else [str(e) for e in ext]
    bad_ext = [e for e in ext_names if e in RISKY_EXT]
    if bad_ext:
        R.append(f"risky token extensions {bad_ext}")
    if rug.get("rugged"):
        R.append("rugcheck: rugged")
    # risks
    for rk in rug.get("risks") or []:
        lvl, nm = (rk.get("level") or "").lower(), rk.get("name")
        if lvl == "danger" or (nm not in ALLOWED_WARN):
            R.append(f"rugcheck risk: {nm} ({lvl})")
    # insiders
    if (rug.get("graphInsidersDetected") or 0) > 0:
        R.append(f"insiders detected ({rug.get('graphInsidersDetected')})")
    if rug.get("insiderNetworks"):
        R.append(f"insider networks ({len(rug['insiderNetworks'])})")
    # markets / LP
    markets = rug.get("markets") or []
    amm = [m for m in markets if m.get("marketType") == "pump_fun_amm"]
    if not amm:
        R.append(f"no PumpSwap (pump_fun_amm) market (types {[m.get('marketType') for m in markets]})")
    for m in markets:
        pct = float((m.get("lp") or {}).get("lpLockedPct") or 0)
        if pct < LP_LOCK_MIN_PCT:
            R.append(f"LP only {pct:.1f}% locked on {m.get('marketType')} {m.get('pubkey')}")
    info["pool"] = amm[0].get("pubkey") if amm else (markets[0].get("pubkey") if markets else None)
    # holders (exclude pool / locker accounts)
    pool_owners = {m.get("pubkey") for m in markets} | {m.get("liquidityA") for m in markets} | \
                  {m.get("liquidityB") for m in markets}
    pool_owners |= {a for a, k in (rug.get("knownAccounts") or {}).items()
                    if (k.get("type") if isinstance(k, dict) else k) in POOL_TYPES}
    pool_owners.discard(None)
    holders = rug.get("topHolders")
    if not holders:
        R.append("top holders unavailable")
    else:
        if any(h.get("insider") for h in holders):
            R.append("insider among top holders")
        non_pool = [h for h in holders if h.get("owner") not in pool_owners and h.get("address") not in pool_owners]
        top = max((float(h.get("pct") or 0) for h in non_pool), default=0.0)
        info["top_holder_pct"] = round(top, 3)
        if top >= TOP_HOLDER_MAX_PCT:
            R.append(f"top non-pool holder {top:.2f}% >= {TOP_HOLDER_MAX_PCT}%")
        top10 = sum(sorted((float(h.get("pct") or 0) for h in non_pool), reverse=True)[:10])
        info["top10_pct"] = round(top10, 2)
        if top10 >= TOP10_MAX_PCT:
            R.append(f"rug filter: top-10 non-pool holders {top10:.1f}% >= {TOP10_MAX_PCT:.0f}% (dump-wallet cluster)")
    # creator still holding a bag (dump wallet)
    supply = float(tok.get("supply") or 0)
    cbal = rug.get("creatorBalance")
    if supply > 0 and cbal is not None:
        cpct = 100.0 * float(cbal) / supply
        info["creator_pct"] = round(cpct, 3)
        if cpct >= CREATOR_MAX_PCT:
            R.append(f"rug filter: creator still holds {cpct:.2f}% of supply (>= {CREATOR_MAX_PCT:.0f}%)")
    nh = rug.get("totalHolders")
    if nh is not None:
        info["holders"] = nh
        if int(nh) < MIN_HOLDERS:
            R.append(f"rug filter: only {nh} holders (< {MIN_HOLDERS})")
    # age / trading / chase
    pairs = d.get("pairs") or []
    ps = [p for p in pairs if p.get("dexId") == "pumpswap"] or []
    if ps:
        p = max(ps, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0))
        info["pool"] = info.get("pool") or p.get("pairAddress")
        created = (p.get("pairCreatedAt") or 0) / 1000.0
        tx = p.get("txns") or {}
        pc = p.get("priceChange") or {}
        buys = {k: (tx.get(k) or {}).get("buys", 0) for k in ("m5", "h1")}
        sells = {k: (tx.get(k) or {}).get("sells", 0) for k in ("m5", "h1")}
        chg = {"m5": pc.get("m5"), "h1": pc.get("h1")}
        info["liquidity_usd"] = (p.get("liquidity") or {}).get("usd")
        info["src"] = "dexscreener"
    elif d.get("pump_trades"):
        st = _pump_trade_stats(d["pump_trades"], now) or {}
        created = d.get("first_seen_ts") or 0
        buys = {k: st.get(f"buys_{k}", 0) for k in ("m5", "h1")}
        sells = {k: st.get(f"sells_{k}", 0) for k in ("m5", "h1")}
        chg = {"m5": st.get("chg_m5"), "h1": st.get("chg_h1")}
        info["src"] = "pump.fun trades (dexscreener unavailable)"
        if not created:
            R.append("pair age unknown (no dexscreener pumpswap pair, no migration timestamp)")
    else:
        return False, R + ["no market data (dexscreener + pump.fun unavailable)"] + d.get("errors", []), info
    # LP size floor (fails closed when neither source reports liquidity)
    liq = rug.get("totalMarketLiquidity")
    if not liq:
        liq = info.get("liquidity_usd")
    info["liq_usd"] = round(float(liq), 0) if liq else None
    if not liq:
        R.append("rug filter: pool liquidity unknown (LP size cannot be checked)")
    elif float(liq) < MIN_LIQ_USD:
        R.append(f"rug filter: liquidity ${float(liq):,.0f} < ${MIN_LIQ_USD:,.0f}")
    if pairs and not ps:
        R.append(f"no DexScreener pumpswap pair (dexes {sorted({p.get('dexId') for p in pairs})})")
    if created:
        age = (now - created) / 60.0
        info["age_min"] = round(age, 1)
        if age > max_age_min:
            R.append(f"age {age:.1f} min > {max_age_min} min")
    info.update(buys=buys, sells=sells, chg=chg)
    if not ((buys["m5"] > 0 and sells["m5"] > 0) or (buys["h1"] > 0 and sells["h1"] > 0)):
        R.append(f"not two-way trading (buys {buys}, sells {sells})")
    if chg["m5"] is None and chg["h1"] is None:
        R.append("price change unavailable (chase rule cannot be evaluated)")
    if chg["m5"] is not None and float(chg["m5"]) > CHASE_M5_PCT:
        R.append(f"chase: m5 +{float(chg['m5']):.0f}% > {CHASE_M5_PCT:.0f}%")
    if chg["h1"] is not None and float(chg["h1"]) > CHASE_H1_PCT:
        R.append(f"chase: h1 +{float(chg['h1']):.0f}% > {CHASE_H1_PCT:.0f}%")
    return (not R), R, info

def check(mint, max_age_min=MAX_AGE_MIN, first_seen_ts=None):
    return decide(fetch(mint, first_seen_ts), max_age_min)

# ---------------------------------------------------------------- post-migration "price holding" entry filter
HOLD_MIN_AGE_MIN = 5.0        # earliest entry: 5 min after migration (and still < MAX_AGE_MIN)
HOLD_MAX_DRAWDOWN_PCT = 15.0  # (a) current price no more than 15% below the peak since migration
HOLD_M5_MIN_PCT = -10.0       # (b) m5 change must be > -10%
HOLD_MIN_BUYS_M5 = 20         # (c) >= 20 buys in last 5 min ...
HOLD_POLL_S = 60              # watcher re-evaluates every 60 s inside the 5-15 min window
HOLD_MAX_PAGES = 30           # pump.fun trade pages (100 each) per poll
# 2026-10-09 additions (all inside the existing hold filter, so they apply to every post-migration entry)
DUMP_WALLET_SOL = 8.0         # (e) any single wallet net-selling >= 8 SOL in the last 5 min -> dump wallet, skip
BOUNCE_BUCKET_S = 60          # (f) bounce/structure: two consecutive 60-s buckets of prints ...
BOUNCE_MIN_PRINTS = 3         #     ... each with >= 3 prints
BOUNCE_MA_S = 120             #     current price must be >= mean print price of the last 120 s (short MA reclaim)
SMART_PREFER_UNTIL_MIN = 10.0 # (g) smart list non-empty: until 10 min after migration require a smart-wallet buy print;
                              #     after that, enter without one (never blocks forever)

def _iso_ts(s):
    return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone

def trade_rows(trades):
    """pump.fun trades -> [(ts, 'buy'|'sell', priceSol, amountSol, userAddress|None)] (bad rows dropped).
    Consumers index [0..3]; [4] (wallet) is optional - older 4-tuples stay valid."""
    out = []
    for t in trades or []:
        try:
            out.append((_iso_ts(t["timestamp"]), t["type"], float(t["priceSol"]), float(t.get("amountSol") or 0),
                        t.get("userAddress")))
        except Exception:
            continue
    return out

def fetch_trades_since(mint, since_ts, max_pages=HOLD_MAX_PAGES):
    """Page pump.fun trades (newest first) back to since_ts. -> (rows newest-first with ts > since_ts, complete)."""
    rows, cursor = [], "0"
    for _ in range(max_pages):
        j = get_json(f"https://swap-api.pump.fun/v2/coins/{mint}/trades?limit=100&cursor={cursor}&minSolAmount=0")
        page = trade_rows(j.get("trades"))
        rows += [r for r in page if r[0] > since_ts]
        pg = j.get("pagination") or {}
        if not page or page[-1][0] <= since_ts or not pg.get("hasMore") or not pg.get("nextCursor"):
            return rows, True
        cursor = pg["nextCursor"]
    return rows, False

def _wallet(t):
    return t[4] if len(t) > 4 else None

def bounce_signal(trades, now, cur=None):
    """Pure. (ok, reason|None, info). Higher low across the last two BOUNCE_BUCKET_S buckets AND current price >=
    the mean print price of the last BOUNCE_MA_S seconds. trades sorted ascending."""
    b = BOUNCE_BUCKET_S
    last = [t[2] for t in trades if 0 <= now - t[0] < b]
    prev = [t[2] for t in trades if b <= now - t[0] < 2 * b]
    ma_w = [t[2] for t in trades if 0 <= now - t[0] < BOUNCE_MA_S]
    info = {"bounce_prints": [len(prev), len(last)]}
    if len(last) < BOUNCE_MIN_PRINTS or len(prev) < BOUNCE_MIN_PRINTS:
        return False, (f"bounce: too few recent prints ({len(prev)}/{len(last)} in the last two {b}s buckets, "
                       f"need {BOUNCE_MIN_PRINTS} each) - dead/illiquid"), info
    cur = cur if cur else last[-1]
    lo_prev, lo_last = min(prev), min(last)
    ma = sum(ma_w) / len(ma_w)
    info.update(bounce_low_prev=lo_prev, bounce_low_last=lo_last, bounce_ma=ma, bounce_cur=cur)
    if lo_last <= lo_prev:
        return False, f"bounce: no higher low (last {b}s low {lo_last:.3g} <= prior {lo_prev:.3g}) - still dumping", info
    if cur < ma:
        return False, f"bounce: price {cur:.3g} below {BOUNCE_MA_S}s MA {ma:.3g} (no reclaim)", info
    return True, None, info

def hold_decide(mig_ts, trades, trades_complete, pair=None, now=None, creator=None, smart=None):
    """Pure. mig_ts = migration time; trades = all pump.fun rows since migration (any order);
    trades_complete = rows reach back to migration; pair = DexScreener pumpswap pair (optional);
    creator = dev wallet (optional, for 'dev selling'); smart = set of smart-wallet addresses (optional).
    -> (ok, reasons, info, wait) ; wait=True means 'too early, re-check later' (not a rejection of the token)."""
    now = now or time.time()
    R, info = [], {}
    if not mig_ts:
        return False, ["hold: migration time unknown"], info, False
    age = (now - mig_ts) / 60.0
    info["hold_age_min"] = round(age, 2)
    if age < HOLD_MIN_AGE_MIN:
        return False, [f"hold: only {age:.1f} min since migration (< {HOLD_MIN_AGE_MIN:.0f})"], info, True
    if age > MAX_AGE_MIN:
        return False, [f"hold: age {age:.1f} min > {MAX_AGE_MIN} min"], info, False
    trades = sorted([t for t in trades or [] if t[0] >= mig_ts - 5], key=lambda t: t[0])
    pair = pair or {}
    tx5 = ((pair.get("txns") or {}).get("m5")) or {}
    pc5 = (pair.get("priceChange") or {}).get("m5")
    try:
        cur = float(pair.get("priceNative")) if pair.get("priceNative") else None
    except (TypeError, ValueError):
        cur = None
    if cur is None and trades:
        cur = trades[-1][2]
    # (a) drawdown from peak since migration (needs full trade history since migration)
    if not trades or not trades_complete:
        R.append("hold: price history since migration incomplete (peak unknown)")
        peak = None
    else:
        peak = max([t[2] for t in trades] + ([cur] if cur else []))
    if cur is None:
        R.append("hold: current price unavailable")
    elif peak:
        dd = (1 - cur / peak) * 100
        info.update(hold_peak=peak, hold_cur=cur, hold_drawdown_pct=round(dd, 1))
        if dd > HOLD_MAX_DRAWDOWN_PCT:
            R.append(f"hold: price {dd:.0f}% below post-migration peak (> {HOLD_MAX_DRAWDOWN_PCT:.0f}%)")
    w5 = [t for t in trades if now - t[0] <= 300]
    # (b) m5 change: DexScreener, else trades (window must be covered)
    covered5 = trades_complete or (trades and now - trades[0][0] >= 300)
    if pc5 is not None:
        m5, src = float(pc5), "dexscreener"
    elif w5 and covered5:
        older = [t for t in trades if now - t[0] > 300]
        base = older[-1][2] if older else w5[0][2]
        m5, src = (w5[-1][2] / base - 1) * 100, "pump.fun"
    else:
        m5, src = None, None
    info.update(hold_m5=m5, hold_m5_src=src)
    if m5 is None:
        R.append("hold: m5 price change unavailable")
    elif m5 <= HOLD_M5_MIN_PCT:
        R.append(f"hold: m5 {m5:.0f}% <= {HOLD_M5_MIN_PCT:.0f}% (dumping)")
    # (c) real buying in last 5 min
    if "buys" in tx5:
        nb = int(tx5.get("buys") or 0)
    elif covered5:
        nb = sum(1 for t in w5 if t[1] == "buy")
    else:
        nb = None
    bv = sum(t[3] for t in w5 if t[1] == "buy"); sv = sum(t[3] for t in w5 if t[1] == "sell")
    info.update(hold_buys_m5=nb, hold_buy_sol_m5=round(bv, 3), hold_sell_sol_m5=round(sv, 3))
    if nb is None:
        R.append("hold: m5 buy count unavailable")
    elif nb < HOLD_MIN_BUYS_M5:
        R.append(f"hold: only {nb} buys in 5 min (< {HOLD_MIN_BUYS_M5})")
    if not covered5 or not w5:
        R.append("hold: 5-min buy/sell volume unavailable")
    elif bv < sv:
        R.append(f"hold: 5-min buy volume {bv:.2f} SOL < sell volume {sv:.2f} SOL")
    # (e) dump wallets: one wallet net-selling big in the last 5 min, or the creator selling at all since migration
    net = {}
    for t in w5:
        w = _wallet(t)
        if w:
            net[w] = net.get(w, 0.0) + (t[3] if t[1] == "sell" else -t[3])
    if net:
        dw, dsol = max(net.items(), key=lambda kv: kv[1])
        info.update(hold_max_wallet_net_sell_sol=round(dsol, 3))
        if dsol >= DUMP_WALLET_SOL:
            R.append(f"rug filter: dump wallet {dw[:6]}.. net-sold {dsol:.1f} SOL in 5 min (>= {DUMP_WALLET_SOL:g})")
    if creator:
        dev_sold = sum(t[3] for t in trades if t[1] == "sell" and _wallet(t) == creator)
        if dev_sold > 0:
            R.append(f"rug filter: creator sold {dev_sold:.2f} SOL since migration")
    # (f) bounce / structure entry
    bok, br, binfo = bounce_signal(trades, now, cur)
    info.update(binfo)
    if not bok:
        R.append(br)
    # (g) smart-money preference
    if smart:
        hits = sorted({_wallet(t) for t in trades if t[1] == "buy" and _wallet(t) in smart})
        info["hold_smart_buyers"] = hits
        if not hits and age < SMART_PREFER_UNTIL_MIN:
            R.append(f"smart: no smart-wallet buy yet ({len(smart)} tracked); waiting until "
                     f"{SMART_PREFER_UNTIL_MIN:.0f} min after migration before entering without one")
    return (not R), R, info, False

def pumpswap_pair(d):
    ps = [p for p in (d.get("pairs") or []) if p.get("dexId") == "pumpswap"]
    return max(ps, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0)) if ps else None
