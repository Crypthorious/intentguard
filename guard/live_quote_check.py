#!/usr/bin/env python3
"""Opt-in live check: real NEAR Intents 1Click DRY quote (read-only, no funds, no key) run through the price gate.
Usage: python3 guard/live_quote_check.py [amount_wnear]   (default 1). Not part of run.sh, which stays offline."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intentguard_guard import oneclick as O

WNEAR, USDC = "nep141:wrap.near", "nep141:17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1"
MAX_LOSS_PCT = 2.0
amt = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
pq = O.dry_quote(WNEAR, USDC, int(amt * 10**24))
dev = O.oracle_deviation_pct(pq)
verdict = "ALLOW" if dev >= -MAX_LOSS_PCT else "DENY"
print(f"1Click dry quote: {amt} wNEAR -> {pq['amount_out']:.6f} USDC (in ${pq['amount_in_usd']:.4f}, out ${pq['amount_out_usd']:.4f})")
print(f"deviation vs 1Click price feed: {dev:+.3f}%  limit -{MAX_LOSS_PCT}%  -> {verdict}  corr={pq['correlation_id']}")
