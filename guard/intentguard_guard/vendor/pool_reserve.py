"""VENDORED pool-reserve pricing helpers.
mid_tokens_per_eth_raw: verbatim from rh_trader/rh_chain.py (Uniswap-V4 sqrtPriceX96 -> mid price).
onchain_liq_usd: verbatim from rh_trader/rh_safety.py (virtual reserve x2 -> USD liquidity)."""


def mid_tokens_per_eth_raw(sqrtp):
    """currency0 = native ETH, currency1 = token -> price1/0 = token raw per wei."""
    return (sqrtp / 2**96) ** 2

def onchain_liq_usd(L, eth_usd):
    """Virtual ETH reserve of the in-range liquidity x2 (Pons graduation LP is a single wide position)."""
    try:
        x_wei = L["liquidity"] * 2**96 / L["sqrt_price_x96"]
        return 2 * x_wei / 1e18 * eth_usd
    except Exception:
        return None

