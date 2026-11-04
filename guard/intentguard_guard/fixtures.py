"""SIMULATED demo inputs (shapes match the real data sources the vendored rules were written for:
RugCheck report + DexScreener pairs for launch_safety, wallet_intel metrics for wallet_score)."""
NOW = 1_793_000_000.0


def _report(mint, *, creator_bal, holders, lp_locked, insiders=0, mint_auth=None, risks=(), total_holders=420, liq=60000):
    return {
        "mint": mint,
        "rug": {
            "tokenMeta": {"name": mint, "symbol": mint[:5].upper()}, "creator": "Dev111",
            "token": {"supply": 1_000_000_000, "mintAuthority": mint_auth, "freezeAuthority": None},
            "mintAuthority": mint_auth, "freezeAuthority": None, "token_extensions": {}, "rugged": False,
            "risks": list(risks), "graphInsidersDetected": insiders, "insiderNetworks": [],
            "markets": [{"marketType": "pump_fun_amm", "pubkey": "Pool1", "liquidityA": "VaultA", "liquidityB": "VaultB",
                         "lp": {"lpLockedPct": lp_locked}}],
            "knownAccounts": {}, "topHolders": holders, "creatorBalance": creator_bal,
            "totalHolders": total_holders, "totalMarketLiquidity": liq,
        },
        "pairs": [{"dexId": "pumpswap", "pairAddress": "Pool1", "liquidity": {"usd": liq}, "pairCreatedAt": (NOW - 3600) * 1000,
                   "txns": {"m5": {"buys": 40, "sells": 31}, "h1": {"buys": 400, "sells": 350}},
                   "priceChange": {"m5": 2.0, "h1": 12.0}}],
        "errors": [],
    }


SAFE_MEME = _report("goodmeme.pump", creator_bal=5_000_000, lp_locked=100.0,
                    holders=[{"owner": f"W{i}", "address": f"A{i}", "pct": 2.5 - i * 0.1, "insider": False} for i in range(10)])
RUG_MEME = _report("rugmeme.pump", creator_bal=180_000_000, lp_locked=12.0, insiders=7, mint_auth="Dev111",
                   risks=[{"name": "Bundled launch: 9 wallets bought in block 0", "level": "danger"}], total_holders=61, liq=4000,
                   holders=[{"owner": "Bndl1", "address": "B1", "pct": 22.0, "insider": True},
                            {"owner": "Bndl2", "address": "B2", "pct": 14.0, "insider": True},
                            {"owner": "Bndl3", "address": "B3", "pct": 9.0, "insider": False}])

GOOD_WALLET = {"address": "smart1.near", "chain": "solana",
               "metrics": {"positions": 64, "closed": 58, "profit_factor": 2.1, "median_ret_pct": 6.5, "best_trade_share": 0.22,
                           "realized_pnl_usd": 4200, "volume_usd": 61000, "wash_like_share": 0.0, "transfer_fed_share": 0.02,
                           "median_hold_s": 2400},
               "extra": {"snipe_share": 0.02, "dev_share": 0.0},
               "copy_summary": {"d0s": {"n": 58, "mean_pct": 9.0}, "d15s": {"n": 58, "mean_pct": 5.1, "median_pct": 2.0},
                                "d60s": {"n": 58, "mean_pct": 3.2, "median_pct": 1.0}}}
BAD_WALLET = {"address": "insider9.near", "chain": "solana",
              "metrics": {"positions": 30, "closed": 28, "profit_factor": 9.0, "median_ret_pct": -12.0, "best_trade_share": 0.81,
                          "realized_pnl_usd": 52000, "volume_usd": 90000, "wash_like_share": 0.0, "transfer_fed_share": 0.4,
                          "median_hold_s": 25},
              "extra": {"snipe_share": 0.6, "dev_share": 0.3, "n_deployed": 5},
              "copy_summary": {"d0s": {"n": 28, "mean_pct": 40.0}, "d15s": {"n": 28, "mean_pct": -18.0, "median_pct": -25.0}}}

# pools: amount units are token units; USDC->wNEAR at ~2.0 USDC/NEAR, deep pool
NEAR_POOL = {"reserve_in": 2_000_000.0, "reserve_out": 1_000_000.0, "fee": 0.003, "liquidity_usd": 4_000_000.0}
MEME_POOL = {"reserve_in": 30_000.0, "reserve_out": 300_000_000.0, "fee": 0.003, "liquidity_usd": 60_000.0}
RUG_POOL = {"reserve_in": 2_000.0, "reserve_out": 900_000_000.0, "fee": 0.003, "liquidity_usd": 4_000.0}
