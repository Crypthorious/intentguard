# IntentGuard

Policy firewall for AI trading agents that settle swaps through NEAR Intents.
An off-chain guard runs four checks on every proposed swap; a NEAR contract enforces per-agent spending caps
and a kill switch on-chain, and the agent can only reach it through a function-call access key limited to `settle`.

Status: testnet only. Contract deployed to NEAR testnet at `guard.intentguard-5821c5.testnet` (see DEPLOY_TESTNET.md). NEAR Intents hand-off is still simulated, see "Simulated parts" below.

## Requirements
- Rust (stable, >= 1.93 for near-sdk 5.29.1) with target `wasm32-unknown-unknown`: `rustup target add wasm32-unknown-unknown`
- `cargo-near` 0.22: `curl --proto '=https' --tlsv1.2 -LsSf https://github.com/near/cargo-near/releases/latest/download/cargo-near-installer.sh | sh`
- Python 3.10+ with `requests` (`pip install requests`; only imported, no network call is made by tests or demo)

## Quick check (everything)
Do: `./run.sh`
See: `test result: ok. 13 passed` (contract), a wasm at `contract/target/near/intentguard.wasm`,
`Ran 34 tests ... OK` (guard), and the demo ending in `RESULT: 9/9 scenarios as expected`. Exit code 0.

## Step by step
1. Do: `cd contract && cargo test`
   See: 13 tests pass, including `over_per_tx_cap_rejected`, `over_daily_cap_rejected`, `kill_switch_blocks`,
   `unbound_key_rejected`, `external_caller_rejected`, `agent_cannot_flip_kill_switch`.
2. Do: `cd contract && cargo near build non-reproducible-wasm`
   See: `contract/target/near/intentguard.wasm` (~150 KB) and `intentguard_abi.json`.
3. Do: `cd guard && python3 -m unittest discover -s tests -v`
   See: 34 tests OK (13 guard tests + 21 vendored risk-gate rule tests).
4. Do: `python3 guard/demo.py`
   See one line per scenario:
   - `1_safe_swap_usdc_wnear guard=ALLOW` and `settle={... 'remaining_daily': 200000000}`
   - `2_safe_meme_buy guard=ALLOW`
   - `3_over_cap guard=DENY` - `max_notional: $150.00 > $100.00`, `contract: per-tx cap 150.00 > 100.00 USD`
   - `4_rug_bundled_token guard=DENY` - mint authority, bundled launch, insiders, LP 12% locked, creator 18%, ...
   - `5_bad_quote_manipulated guard=DENY` - `quote deviates -8.00% from pool-reserve fair price`
   - `6_copy_insider_wallet guard=DENY` - `signal wallet insider9.near score 0/10 REJECT`
   - `7_kill_switch_on guard=DENY` - `contract: kill switch ON`
   - `8_bypass_guard` x2 - agent calls the contract directly: `ERR_KILL_SWITCH_ON`, then `ERR_OVER_PER_TX_CAP`
   - `RESULT: 9/9 scenarios as expected`, exit code 0. Every verdict is appended to an audit JSONL (path printed).

## How it works
Proposal (JSON from the agent): `agent, token_in, token_out, amount_in, amount_usd, quote, pool, token_report, signal_wallet`.
`guard/intentguard_guard/guard.py::evaluate` runs, fail-closed (missing data or exception -> DENY):
| check | code | blocks when |
|---|---|---|
| risk | `vendor/risk_gate.py::check` + contract policy mirror | kill file, notional > cap, too many open positions/trades, daily loss stop; contract kill switch, agent paused, per-tx cap, 24h cap |
| launch | `vendor/launch_safety.py::decide` | mint/freeze authority, LP < 99.9% locked, insiders/bundles, top holder >= 5%, top10 >= 30%, creator >= 2%, < 150 holders, liquidity < $12k, one-way trading, chase. Skipped for allowlisted majors (`usdc.near`, `wrap.near`, ...) |
| price | `guard.py::check_price` + `vendor/pool_reserve.py` | quote differs > 2% from constant-product fair output from pool reserves (or V4 sqrtPriceX96 mid); pool liquidity < $12k |
| reputation | `vendor/wallet_score.py::judge/verdict` | copied signal wallet scores < 6/10 or REJECT (sniper/bundler, dev-linked, transfer-fed, wash, followers lose to delay, too fast to copy) |

Contract (`contract/src/lib.rs`, near-sdk 5.29.1):
- `new(owner)`, owner-only: `register_agent(agent, per_tx_cap, daily_cap)`, `set_caps`, `set_kill_switch(on)`, `set_agent_paused`,
  `add_agent_key(agent, public_key, allowance_yocto)` (adds a function-call key on the contract account, receiver = itself, method `settle` only), `revoke_agent_key`.
- `settle(amount, token_in, token_out, intent_hash)`: requires predecessor == contract (i.e. signed by a key on the contract account), maps `signer_account_pk` -> agent, panics with
  `ERR_KILL_SWITCH_ON | ERR_AGENT_PAUSED | ERR_OVER_PER_TX_CAP | ERR_OVER_DAILY_CAP | ERR_KEY_NOT_BOUND | ERR_MUST_USE_AGENT_KEY`; on success records spend and logs a NEP-297 `EVENT_JSON` `settle` event.
- Views: `get_policy(agent)`, `is_killed()`, `get_owner()`, `agent_for_key(public_key)`.

## Simulated parts (explicit)
- NEAR Intents: `guard/intentguard_guard/intents_stub.py` returns a constant-product quote from fixture reserves. No 1Click / solver-relay call, no NEP-413 signing, no `intents.near` `execute_intents`. In the contract this hand-off is `TODO(intents)` in `settle`.
- Real NEAR Intents quotes (opt-in, read-only): `guard/intentguard_guard/oneclick.py` asks the 1Click API for a `dry: true` quote (no deposit address, no funds move, no API key) and `python3 guard/live_quote_check.py` runs it through a price-loss check against 1Click's own token prices. The default demo and `run.sh` stay offline.
- Contract in the default (offline) demo: `guard/intentguard_guard/contract_sim.py`, a Python mirror of `lib.rs` with the same rules and error strings. The Rust contract itself is exercised by `cargo test` (near-sdk unit-testing VM mock), not on a live chain.
- Data: token reports, pools and wallet histories in `guard/intentguard_guard/fixtures.py` are synthetic, shaped like RugCheck/DexScreener and wallet_intel output.

## Testnet deploy (done 2026-11-01)
Live contract: `guard.intentguard-5821c5.testnet`, owner `intentguard-5821c5.testnet`. Tx hashes, explorer links, key locations and
redeploy commands: DEPLOY_TESTNET.md.
- Do: `./smoke_testnet.sh` See: allowed settles return `remaining_daily`, blocked ones show `ERR_OVER_PER_TX_CAP`, `ERR_KEY_NOT_BOUND`,
  `ERR_MUST_USE_AGENT_KEY`, `ERR_KILL_SWITCH_ON`, `ERR_OVER_DAILY_CAP`, `ERR_NOT_OWNER`, and the agent key refused for `set_kill_switch`.
- Do: `INTENTGUARD_NETWORK=testnet python3 guard/demo.py` See: the same 9 scenarios run against the live contract
  (`guard/intentguard_guard/contract_testnet.py`), tx links printed at the end, `RESULT: 9/9`.
