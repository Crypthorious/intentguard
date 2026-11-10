# IntentGuard

Policy firewall for an AI trading agent. The agent proposes a swap. An off-chain guard denies it when a spending cap, launch-safety rule, pool-price check, or copied-wallet score fails. A NEAR contract enforces the per-transaction cap, the rolling 24-hour cap, and a human kill switch. The agent can reach that contract only with a function-call access key limited to the method `settle`.

Track: AI Security & Defense (`security`). NEAR's role is the control plane: the caps and the key permission are on-chain, so a process that skips the off-chain guard still cannot raise its own limit or clear the kill switch.

## What is real, simulated, or read-only

| Path | What it does | What it does not do |
|---|---|---|
| `python3 guard/demo.py` (default) | Deterministic offline demo. Guard verdicts plus `ContractSim`, a Python mirror of the contract rules. | No network. No chain transaction. No NEAR Intents quote. `settle` records a local ledger entry only. |
| `cd contract && cargo test` | Runs the Rust contract in the near-sdk unit-test VM, including cap, kill-switch, and key-binding rejections. | Does not deploy. Does not call `intents.near`. |
| `python3 scripts/verify_testnet_code.py` | Read-only public RPC. Compares `build/intentguard.wasm` to the code on `guard.intentguard-5821c5.testnet` and prints `get_owner`, `is_killed`, and `get_policy`. | No credentials. No signature. No state change. |
| `python3 guard/live_quote_check.py` | Read-only POST to the public 1Click API with `dry: true`. Prints the quote and a price-loss check against 1Click's own USD figures. | Not a settlement. The client refuses a response whose request was not dry. No API key. No deposit is broadcast. Not part of `./run.sh`. |
| `INTENTGUARD_NETWORK=testnet python3 guard/demo.py` and `./smoke_testnet.sh` | Sign testnet transactions with keys already in `~/.near-credentials`. | Not run by the default checks. No mainnet. These scripts are not required to review the prototype. |
| On-chain `settle` | Records the amount, updates the 24h window, emits a NEP-297 `settle` event, and returns the remaining daily budget. | Does not call `intents.near` `execute_intents`. Does not sign a NEP-413 intent. Does not move tokens. Marked `TODO(intents)` in `contract/src/lib.rs`. |

`build/intentguard.wasm` (153,281 bytes, sha256 `a27e10243060b99ceb447ed3755a811ae70dcae0f2ff2cb322ed5a40932d0ca8`, code hash `BwJYCHzNavSTyr462q3xFXTUr9NgP2bR6uUXXMmmfj3V`) is the artifact deployed on 2026-11-01. It is committed so the read-only check works on a fresh clone without rebuilding. A later rebuild, reproducible or not, is a different file and has not been deployed.

## Fresh clone

```bash
git clone https://github.com/Crypthorious/intentguard.git
cd intentguard
python3 -m pip install -r requirements.txt
# Rust 1.99.1 and the wasm32 target: contract/rust-toolchain.toml
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/near/cargo-near/releases/download/cargo-near-v0.23.0/cargo-near-installer.sh | sh
./run.sh
python3 scripts/verify_testnet_code.py
```

`./run.sh` needs Python 3.10+, Rust 1.99.1 (near-sdk 5.29.1 declares rust-version 1.93 and edition 2024), the `wasm32-unknown-unknown` target, and cargo-near 0.23.0. It does not need Docker, a NEAR account, or an API key. `requests` is imported by the vendored launch-safety fetchers; the demo and unit tests do not call those fetchers.

## Try it

1. Do: `cd contract && cargo test`
   See: `test result: ok. 13 passed`, including `over_per_tx_cap_rejected`, `over_daily_cap_rejected`, `kill_switch_blocks`, `unbound_key_rejected`, `external_caller_rejected`, `agent_cannot_flip_kill_switch`.
2. Do: `cd contract && cargo near build non-reproducible-wasm`
   See: `contract/target/near/intentguard.wasm`. This wasm is not the deployed file. The deployed file is `build/intentguard.wasm`.
3. Do: `cd guard && python3 -m unittest discover -s tests -v`
   See: `Ran 38 tests` and `OK` (13 guard, 3 dry-quote parser, 22 vendored risk-gate).
4. Do: `python3 guard/demo.py`
   See one line per scenario, then `RESULT: 9/9 scenarios as expected` and exit code 0:
   - `1_safe_swap_usdc_wnear` `guard=ALLOW`, settle remaining daily `200000000`
   - `2_safe_meme_buy` `guard=ALLOW`
   - `3_over_cap` `guard=DENY`, `max_notional: $150.00 > $100.00` and `contract: per-tx cap 150.00 > 100.00 USD`
   - `4_rug_bundled_token` `guard=DENY`, mint authority, bundled launch, insiders, LP lock, creator holding, liquidity
   - `5_bad_quote_manipulated` `guard=DENY`, quote deviates `-8.00%` from the pool-reserve fair price
   - `6_copy_insider_wallet` `guard=DENY`, `insider9.near score 0/10 REJECT`
   - `7_kill_switch_on` `guard=DENY`, `contract: kill switch ON`
   - `8_bypass_guard` twice: the agent calls the contract directly and is rejected with `ERR_KILL_SWITCH_ON`, then `ERR_OVER_PER_TX_CAP`
   - The two lines before `RESULT` say settlement is a simulated ledger and quotes are fixtures
5. Do: `./run.sh`
   See: the four steps above, in that order, and exit code 0.
6. Do: `python3 scripts/verify_testnet_code.py`
   See: `bytes_equal True`, `get_owner "intentguard-5821c5.testnet"`, and `RESULT OK`.
7. Do: `python3 guard/live_quote_check.py`
   See: one `1Click dry quote` line and a verdict. The numbers move with the market. This is a quote, not a payment. Checked 2026-11-10: `1.0 wNEAR -> 3.639013 USDC`, deviation `+0.000%` against 1Click's own USD figures, verdict `ALLOW`.

## How the control works

Proposal fields: `agent`, `token_in`, `token_out`, `amount_in`, `amount_usd`, `quote`, `pool`, `token_report`, `signal_wallet`.

`guard/intentguard_guard/guard.py` `evaluate` is fail-closed. Missing data or an exception becomes `DENY`.

| Check | Code | Blocks when |
|---|---|---|
| risk | `vendor/risk_gate.py` `check`, with `market="skip"`, plus the contract policy | Kill file, notional over the cap, too many open positions or trades, daily loss stop; contract kill switch, paused agent, per-tx cap, 24h cap |
| launch | `vendor/launch_safety.py` `decide` | Mint or freeze authority, LP lock under 99.9%, insiders or bundles, top holder at least 5%, top 10 at least 30%, creator at least 2%, under 150 holders, liquidity under $12k, one-way trading, chase. Skipped for allowlisted majors `usdc.near`, `wrap.near`, `eth.bridge.near` |
| price | `guard.py` `check_price` and `vendor/pool_reserve.py` | Quote differs by more than 2% from constant-product fair output, or pool liquidity under $12k. A Uniswap V4 `sqrtPriceX96` mid is supported by the vendored helper |
| reputation | `vendor/wallet_score.py` `judge` and `verdict` | Copied signal wallet scores under 6/10 or `REJECT` |

Contract (`contract/src/lib.rs`, near-sdk 5.29.1):

- `new(owner)`. Owner only: `register_agent`, `set_caps`, `set_kill_switch`, `set_agent_paused`, `add_agent_key`, `revoke_agent_key`.
- `add_agent_key` adds a function-call access key on the contract account. Receiver is the contract itself. Method name is `settle` only. Allowance is limited.
- `settle(amount, token_in, token_out, intent_hash)` requires the predecessor to be the contract account (`ERR_MUST_USE_AGENT_KEY`), maps `signer_account_pk` to an agent (`ERR_KEY_NOT_BOUND`), then applies the kill switch, pause, per-tx cap, and 24h cap. Success writes the spend and logs a NEP-297 `settle` event.
- Views: `get_policy`, `is_killed`, `get_owner`, `agent_for_key`.

### Function-call key limits

The deployed agent key can call only `settle` on `guard.intentguard-5821c5.testnet`. It cannot transfer NEAR, add or delete keys, stake, or call `set_kill_switch`, `register_agent`, or `set_caps`. The owner account is a different account and is the only predecessor allowed to change policy (`ERR_NOT_OWNER`).

The key lives on the contract account, so a successful `settle` is a self-call: predecessor and signer account are the contract, and the signer public key selects the agent. The contract account still has its own full-access key, held outside the repo, so the agent key cannot lock the human out of the contract account. The agent key's gas allowance is finite (0.25 NEAR on the deployed key). When that allowance is spent, `settle` stops until the owner adds a replacement key. An account that had only this function-call key and no full-access key could not add a new key; that is the usual NEAR function-call-key lockout, and it is not how this contract account is set up.

The key does not authorize NEAR Intents. `settle` does not forward an intent.

`ContractSim` checks the bound key, the caps, and the kill switch. It does not model the predecessor check `ERR_MUST_USE_AGENT_KEY`. That check is in the Rust tests and was exercised on testnet on 2026-11-01 (see `DEPLOY_TESTNET.md`).

## Disclosures (Q-005)

Baseline, not the NEAR integration. These files are the owner's earlier rules, identified by their headers. Git history on GitHub starts with one commit on 2026-11-04, so there is no older tag to diff. The split is by path:

- `guard/intentguard_guard/vendor/risk_gate.py` and `risk_gate_config.json`. Paper/shadow pre-trade gate. The config comment describes a stage-1 perps book. `evaluate` calls `check` with an in-memory config and `market="skip"`. It does not call `fetch_market`. `fetch_market` and `check_order`, if called directly, request public Bybit linear tickers at `https://api.bybit.com/v5/market/tickers?category=linear`. The demo and `./run.sh` do not call them. Default config path is `risk_gate_config.json` (fixed 2026-11-10; the previous path `config.json` was not in the tree).
- `guard/intentguard_guard/vendor/launch_safety.py`. Header describes shared buy-safety checks. A comment dates stricter rug filters to 2026-10-09, before the hackathon announcement on 2026-10-19. The guard calls `decide` on fixture reports. `fetch` would call public RugCheck, DexScreener, and pump.fun URLs. The demo and unit tests do not call `fetch`.
- `guard/intentguard_guard/vendor/wallet_score.py`. Header: rule functions from `wallet_intel/server/score.py`, with the config block inlined.
- `guard/intentguard_guard/vendor/pool_reserve.py`. Header: Uniswap V4 helpers from `rh_trader`.

Those modules had no LICENSE header. They are included under `LICENSE` (MIT). The owner confirms the right to publish that prior code before the repository is made public.

Hackathon integration, written with AI coding assistance in Cursor: `contract/src/lib.rs`, `guard/intentguard_guard/guard.py`, `contract_sim.py`, `contract_testnet.py`, `oneclick.py`, `intents_stub.py`, `fixtures.py`, `guard/demo.py`, `guard/live_quote_check.py`, `guard/tests/`, `scripts/verify_testnet_code.py`, and the docs. Runtime does not call NEAR AI Cloud or any other model. The verdicts are deterministic rules. If any integration file was written without an AI tool, correct this paragraph before submission.

Third-party libraries:

- `near-sdk` 5.29.1, published 2026-09-17, license `MIT OR Apache-2.0` (crate metadata). Rust edition 2024, rust-version 1.93.
- Python 3 standard library.
- `requests` 2.32.5, used only if the vendored launch-safety fetchers are called.
- NEAR Intents 1Click HTTP API, called with `urllib` by the opt-in script. No 1Click SDK is vendored. No JWT (Q-006). A keyless dry quote includes 1Click's usual fee inside the quoted price.

No other NEAR Hackathon submission is named in this repository (Q-015). If the same person submits a second project, name it here before the repository is made public.

## Testnet

Contract `guard.intentguard-5821c5.testnet`. Owner `intentguard-5821c5.testnet`. Deploy transactions, the public function-call key, and the 2026-11-01 smoke log are in `DEPLOY_TESTNET.md`.

Read-only state observed 2026-11-10 from `https://rpc.testnet.near.org`: code hash equals `build/intentguard.wasm`, owner is the account above, kill switch is off, `bot1` policy is per-tx `100000000`, daily `250000000`, spent `70000000`, settlements `2`. That spent figure is the two allowed demo settlements (50 and 20 USDC, 6 decimals), not a new payment made for this check.

Keys are not in the repository. `.gitignore` excludes `.env`, `*.key`, `.near-credentials/`, and `*credentials*.json`. A scan of the tree found no private key, seed phrase, or API token. The ed25519 string in `DEPLOY_TESTNET.md` is a 44-character public key.

## Reproducible build

`contract/Cargo.toml` pins `sourcescan/cargo-near:0.23.0-rust-1.99.1` for `cargo near build reproducible-wasm`. Docker is required. The build uses the committed git revision and ignores uncommitted edits, and the wasm embeds that revision, so two builds of the same commit match and a later commit does not.

```bash
# clean worktree, Docker running, cargo-near 0.23.0 on PATH
cd contract
cargo near build reproducible-wasm
sha256sum target/near/intentguard.wasm
# run the same command again; the sha256 is the reproducibility result
```

The reproducible wasm is not the testnet code. The testnet code is the 2026-11-01 non-reproducible artifact `build/intentguard.wasm`, built with cargo-near 0.22.0 before this metadata existed. This repository does not redeploy.

The image digest and the result of the local double build are in `DEPLOY_TESTNET.md`.

## Limitations

- Simulated settlement. Neither `ContractSim` nor on-chain `settle` submits an intent or transfers an asset.
- Simulated quotes in the default demo. `intents_stub.py` is constant-product math on fixture reserves. `skew` exists so the demo can show a bad quote.
- The 1Click command is a separate, live, read-only quote. It is not evidence that a swap settled.
- Token reports, pools, and wallet histories in `fixtures.py` are synthetic. They use the shapes of RugCheck, DexScreener, and wallet_intel. They are not live NEAR accounts.
- Launch and reputation rules were written for Solana pump.fun-style reports and wallet histories. Applied here, they score those fixture shapes. They are not a NEAR token indexer.
- The NEP-297 event string interpolates `agent`, token ids, and `intent_hash` without JSON escaping. Fixture ids are plain. A quote or newline in those strings would break the log line. Policy enforcement does not depend on the log.
- No dashboard and no HTTP service. The local demo is the review path (hackathon Q-012).
- No mainnet deployment and no claim of production custody.

## License

MIT. See `LICENSE`.
