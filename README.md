# Rugwall (formerly IntentGuard)

**Rug, price and copy-trade firewall for NEAR trading agents.**

An AI trading agent proposes a swap. Rugwall checks it for four things: a rug-shaped token, a quote that is off the live pool price, a copied wallet with an insider track record, and the human's spending caps. Only if all four pass does the guard sign an ed25519 verdict. The NEAR contract stores the guard's public key and refuses any `settle` that lacks a fresh, unused signature over the exact amount, tokens and intent hash. An agent that skips the guard cannot settle, even inside its caps.

The repository is still called `intentguard`. The product was renamed because two other NEAR Hackathon entries are also called IntentGuard.

- Track: AI Security & Defense (`security`). It also fits `defi` and `agents`.
- Live dashboard (read-only, NEAR testnet): **https://rugwall-near.netlify.app**. Press **Try it in 1 minute**: no wallet, no setup.
- Contract (testnet): [`guard2.intentguard-5821c5.testnet`](https://testnet.nearblocks.io/address/guard2.intentguard-5821c5.testnet), v0.2 with signed verdicts. The original v0.1 contract `guard.intentguard-5821c5.testnet` is unchanged and still live.
- Demo video: `demo/intentguard-demo.mp4`, also on the dashboard.

## The problem

Trading agents now hold wallets. One prompt injection, a honeypot token, a manipulated solver quote or a copied wallet that turns out to be a dev dumping can drain the treasury in one transaction. Spending caps limit how much is lost. They do not ask whether the trade should happen at all. An off-chain checker does ask, but a compromised agent can simply skip it.

## What NEAR does here

- **Function-call access key.** The agent's only key can call one method, `settle`, on one contract. It cannot transfer NEAR, add keys or change policy.
- **On-chain policy.** The per-transaction cap, the rolling 24-hour cap, the per-agent pause and the human kill switch live in the contract. The agent cannot raise its own limit.
- **On-chain signature check.** `settle` runs `env::ed25519_verify` on the guard's verdict. Every verdict is bound to the contract, the agent, the intent hash, the amount, both tokens, an expiry and a nonce. That turns the off-chain rug, price and reputation checks into something the chain enforces. No signature means no settle.
- **NEAR Intents 1Click** supplies the real quote (`dry: true`), and **Ref Finance** pool reserves on NEAR supply the fair price that the quote is checked against.

## Try it: do X → see Y

No NEAR account, key or API key is needed for steps 1 to 6.

1. **Do:** open https://rugwall-near.netlify.app and press **Try it in 1 minute**, then click through the 8 cases (safe swap, rug token, rigged quote, copying an insider, agent skips the guard, replayed approval, token swapped after approval, forged approval).
   **See:** for each case, what the guard decided in the last live testnet run (which of the four checks failed and why), then your browser verifies the guard's ed25519 signature itself against the guard key read live from the contract, and reads the real `settle` transaction from NEAR testnet: `Settled 50 USDC → wrap.near` results for the safe swap, "Nothing sent" for the three guard DENYs, and `ERR_NO_VERDICT`, `ERR_REPLAY` or `ERR_BAD_SIG` for the four attacks. For the token swap, it also shows that the same signature is valid over the token the guard approved, so the one changed field is what broke it. Nothing is sent to the chain.
   **Also see:** the live contract policy read from testnet RPC: `guard_public_key` = `ed25519:Ho3s8kHdLEpbBrAVtRNCSMxPgHYEFhx5JqkFRtRHRBXj`, per-tx cap 100 USDC, daily cap 250 USDC, and the kill switch off. Below that are the on-chain transactions. Rejected `settle` calls show their panic code (`ERR_NO_VERDICT`, `ERR_REPLAY`, `ERR_BAD_SIG`, `ERR_KILL_SWITCH_ON`, `ERR_OVER_PER_TX_CAP`), and each one links to NearBlocks. The page also has the guard verdict log and the demo video.
2. **Do:** `cd contract && cargo test`
   **See:** `test result: ok. 27 passed`. The 14 signed-verdict tests include `no_verdict_rejected_even_within_caps`, `tampered_amount_rejected`, `tampered_token_rejected`, `replayed_verdict_rejected`, `expired_verdict_rejected`, `verdict_from_other_key_rejected` and `rotated_guard_key_voids_old_verdicts`. The 13 v0.1 cap, kill-switch and key tests still pass.
3. **Do:** `cd guard && python3 -m unittest discover -s tests -v`
   **See:** `Ran 53 tests` and `OK`. That is 13 guard, 11 signed-verdict, 4 live-data and MCP (network mocked), 3 dry-quote parser and 22 vendored risk-gate tests.
4. **Do:** `python3 guard/demo.py`
   **See:** a `DATA: live, read-only.` line naming Ref Finance pool 4512's reserves and the 1Click dry quotes, then one line per scenario, then `RESULT: 13/13 scenarios as expected` and exit code 0:
   - `1_safe_swap_usdc_wnear`: `guard=ALLOW`, `data=live`, `sig=ed25519:…`, settles with remaining daily `200000000`
   - `2_safe_meme_buy`: `guard=ALLOW`, signed and settled (the token is a fixture)
   - `3_over_cap`: `guard=DENY`, `max_notional: $150.00 > $100.00` and `contract: per-tx cap`
   - `4_rug_bundled_token`: `guard=DENY` for mint authority, a bundled launch, insiders, the LP lock, the creator's holding and liquidity
   - `5_bad_quote_manipulated`: `guard=DENY`, because the real 1Click quote, tampered by 8%, deviates about `-7.8%` from the live pool price
   - `6_copy_insider_wallet`: `guard=DENY`, `insider9.near score 0/10 REJECT`
   - `7_kill_switch_on`: `guard=DENY`, `contract: kill switch ON`
   - `8_bypass_kill_switch_on`: the agent calls the contract directly and gets `ERR_KILL_SWITCH_ON`
   - `9_bypass_no_verdict`: with the kill switch off, a $10 settle inside every cap but with no guard signature gets **`ERR_NO_VERDICT`**
   - `10_bypass_over_cap`: `ERR_OVER_PER_TX_CAP`
   - `11_replay_old_verdict`: re-sending scenario 1's signed verdict gets `ERR_REPLAY`
   - `12_tamper_token`: the guard approved $10 of wNEAR and the agent changed `token_out` to `attacker.near`, so it gets `ERR_BAD_SIG`
   - `13_forged_verdict`: the agent signed its own "approval" and gets `ERR_BAD_SIG`

   If the network is unavailable, the demo prints `DATA: fixtures (offline fallback: <reason>)`, uses the offline fixtures and still reaches 13/13. `INTENTGUARD_DATA=fixtures` forces that path.
5. **Do:** `python3 scripts/verify_testnet_code.py`
   **See:** `bytes_equal True`, `get_guard_key "ed25519:Ho3s8kHd…"` and `RESULT OK`. The committed `build/intentguard-v0.2.wasm` is the code on `guard2.intentguard-5821c5.testnet`. `--v1` checks the original contract. `python3 scripts/verify_dashboard_data.py` checks offline that every saved dashboard transaction's guard signature verifies, or fails, the way the contract ruled (`RESULT OK`).
6. **Do:** `./run.sh`
   **See:** contract tests, the wasm build, guard tests and the demo, in that order, then exit code 0.
7. **Do (signs TESTNET transactions, needs the owner's keys):** `INTENTGUARD_NETWORK=testnet python3 guard/demo.py`
   **See:** the same 13/13 against the deployed contract, with a NearBlocks link for every transaction. The run on 2026-11-12 is listed in `DEPLOY_TESTNET.md`.
8. **Do:** `python3 examples/agent_quickstart.py`
   **See:** in about a second, offline: `safe $50 swap -> guard ALLOW, signed; contract settled 50.00 USDC, 200.00 left today`, `rigged quote (-8%) -> guard DENY, nothing sent: price: quote deviates -8.00% …` and `skip the guard -> contract rejected: ERR_NO_VERDICT`. This is the integration in one file.
9. **Do (optional, MCP):** add `{"command": "python3", "args": ["<repo>/mcp/rugwall_mcp.py"]}` to an MCP client, then call `rugwall_check_swap` with `{"amount_usd": 50}`.
   **See:** `ALLOW` with the live quote, the pool fair price and the deviation. `{"amount_usd": 150, "copied_wallet": "insider_demo"}` returns `DENY` with three reasons. The tool is read-only and never signs.

## What is real, simulated, or read-only

| Path | Real | Not real / not done |
|---|---|---|
| Contract on testnet (`guard2.…`) | Caps, the 24h window, pause, the kill switch, the settle-only function-call key, and ed25519 verdict verification with expiry (10-minute maximum TTL) and nonce replay protection | `settle` records the spend and emits a NEP-297 event. It does **not** call `intents.near` `execute_intents` or move tokens (`TODO(intents)` in `lib.rs`) |
| `python3 guard/demo.py` (default) | 1Click quote with `dry: true` (no deposit address, no funds), Ref Finance pool 4512 reserves via a mainnet `get_pool` view, and `ft_metadata` for USDC (6 dp) and wNEAR (24 dp) | The contract is `ContractSim`, a Python mirror of `lib.rs` with the same error codes. The meme tokens and wallet histories are fixtures. Scenario 5 tampers with the real quote on purpose |
| `INTENTGUARD_NETWORK=testnet …demo.py` | Signs testnet transactions with keys in `~/.near-credentials` | Not part of `./run.sh`. No mainnet |
| Dashboard and "Try it in 1 minute" | Live testnet RPC views (policy, `get_guard_key`, `is_nonce_used`), live NearBlocks v3 transaction list, each logged transaction re-read from archival testnet RPC, and the guard's ed25519 signatures verified in the browser (WebCrypto) | The guard's verdicts are the saved export of the last live testnet run (`dashboard/data/verdicts.json`); the guard and its key run off-chain and never touch the page. Clicking sends no transaction. If every RPC is down, it shows the saved copy and says so. No wallet connect, no forms |
| `mcp/rugwall_mcp.py` | Live quote, pool and contract policy reads | Read-only. It never signs |

## Add Rugwall to your agent

Three steps: ask the guard, get a signed verdict, settle with it. `examples/agent_quickstart.py` runs the whole loop offline.

**MCP (read-only pre-trade check, any MCP client):**

```json
{"mcpServers": {"rugwall": {"command": "python3", "args": ["/path/to/intentguard/mcp/rugwall_mcp.py"]}}}
```

Then call `rugwall_check_swap {"amount_usd": 50}` before every swap (`ALLOW` with the live 1Click quote vs the Ref pool), and `rugwall_policy {"agent": "bot1"}` for the live caps, kill switch and guard key. The MCP tool never signs.

**Python (the guard process holds the verdict key; the agent only passes the verdict on):**

```python
from intentguard_guard import guard, verdict
from intentguard_guard.contract_testnet import ContractTestnet

contract = ContractTestnet("intentguard-5821c5.testnet", "guard2.intentguard-5821c5.testnet",
                           "~/.near-credentials/testnet/agent-keys/bot1.json")   # agent's settle-only key
signer = verdict.GuardSigner.from_key_file("~/.near-credentials/testnet/agent-keys/guard-verdict.json")
ctx = {"contract": contract, "treasury_usd": 1000, "signer": signer,
       "contract_id": "guard2.intentguard-5821c5.testnet"}

v = guard.evaluate(proposal, ctx)        # risk caps, rug check, quote vs pool, copied wallet
if v["allow"]:                           # ALLOW comes with an ed25519 verdict; DENY is never signed
    contract.settle(contract.agent_public_key(), v["amount_raw"], proposal["token_in"],
                    proposal["token_out"], v["intent_hash"], verdict=v["signed_verdict"])
else:
    print("blocked:", v["reasons"])
```

**What reaches NEAR** (the agent's function-call key can only call `settle` on this contract):

```bash
near contract call-function as-transaction guard2.intentguard-5821c5.testnet settle \
  json-args '{"amount":"50000000","token_in":"<usdc>","token_out":"wrap.near","intent_hash":"<sha256 hex>",
    "verdict":{"nonce":"<u64>","expires_at_ns":"<now + at most 10 min>","signature":"<128 hex chars>"}}' \
  prepaid-gas '30 Tgas' attached-deposit '0 NEAR' \
  sign-as guard2.intentguard-5821c5.testnet network-config testnet \
  sign-with-access-key-file agent-key.json send
# no verdict -> ERR_NO_VERDICT · any field changed -> ERR_BAD_SIG · reused -> ERR_REPLAY
```

## How it works

```
agent proposal ──► Rugwall guard (off-chain, fail-closed)
                    1 risk: caps + kill switch read from the contract, vendored risk_gate
                    2 launch: rug report (authorities, LP lock, bundles, insiders, holders, liquidity)
                    3 price: live 1Click quote vs Ref pool constant-product fair output (±2%)
                    4 reputation: copied wallet score ≥ 6/10 and not REJECT
                 ── ALLOW ──► ed25519 verdict over (contract, agent, intent_hash, amount, token_in, token_out, expires_at_ns, nonce)
agent ──settle(amount, token_in, token_out, intent_hash, verdict)──► contract (function-call key, settle only)
                    kill switch, pause, per-tx cap → verdict present? → not expired, TTL ≤ 10 min → nonce unused
                    → ed25519_verify against the stored guard key → 24h cap → record spend, burn nonce, emit event
```

The verdict message is UTF-8, with newline-separated fields:

```
intentguard-verdict-v1
<contract_id>
<agent>
<intent_hash>
<amount, smallest unit>
<token_in>
<token_out>
<expires_at_ns>
<nonce>
```

`verdict_message` in `contract/src/lib.rs` and `guard/intentguard_guard/verdict.py` build the same bytes. A shared test vector checks both. The signature is sent as 128 hex characters.

| Contract error | When |
|---|---|
| `ERR_MUST_USE_AGENT_KEY` / `ERR_KEY_NOT_BOUND` | Not called through a bound agent function-call key |
| `ERR_KILL_SWITCH_ON` / `ERR_AGENT_PAUSED` | The human stopped trading |
| `ERR_OVER_PER_TX_CAP` / `ERR_OVER_DAILY_CAP` | Over the on-chain caps |
| `ERR_NO_VERDICT` | No guard verdict attached |
| `ERR_GUARD_KEY_NOT_SET` | No guard key configured (fails closed) |
| `ERR_VERDICT_EXPIRED` / `ERR_VERDICT_TTL_TOO_LONG` | Block time is past `expires_at_ns`, or the expiry is more than 10 minutes ahead |
| `ERR_REPLAY` | The nonce was already settled |
| `ERR_BAD_SIG` | Malformed signature, the wrong key, or any signed field changed |

Owner-only methods: `register_agent`, `set_caps`, `set_kill_switch`, `set_agent_paused`, `add_agent_key`, `revoke_agent_key`, and `set_guard_key`, which rotates the key and voids old verdicts at once. Views: `get_config`, `get_policy`, `list_agents`, `get_guard_key`, `is_nonce_used`, `is_killed`, `get_owner`, `agent_for_key`.

Guard checks (`guard/intentguard_guard/guard.py`, fail-closed, so missing data or an exception means `DENY`):

| Check | Code | Blocks when |
|---|---|---|
| risk | `vendor/risk_gate.py` `check` (with `market="skip"`), plus the contract policy | Kill file, notional over the cap, too many positions or trades, daily loss stop, contract kill switch, a paused agent, the per-tx cap, the 24h cap |
| launch | `vendor/launch_safety.py` `decide` | Mint or freeze authority, LP lock under 99.9%, insiders or bundles, a top holder at 5% or more, the top 10 at 30% or more, the creator at 2% or more, under 150 holders, liquidity under $12k, one-way trading. Skipped for allowlisted majors (USDC, wNEAR, ETH) |
| price | `check_price` | The quote differs from the constant-product fair output by more than 2%, or pool liquidity is under $12k |
| reputation | `vendor/wallet_score.py` | The copied signal wallet scores under 6/10 or `REJECT` |

Keys: the guard's verdict key is the guard's own ed25519 key, not a NEAR account key. It never signs a transaction. The offline demo makes a new one on every run. The testnet guard reads it from `~/.near-credentials/testnet/agent-keys/guard-verdict.json`, outside the repo. The agent's function-call key, the owner key and the guard key are three separate keys.

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

`./run.sh` needs Python 3.10 or newer with `cryptography`, Rust 1.99.1 (near-sdk 5.29.1 declares rust-version 1.93), the `wasm32-unknown-unknown` target and cargo-near 0.23.0. It does not need Docker, a NEAR account or an API key. It uses the network for live read-only data if it can, and falls back to fixtures if it can't.

## Disclosures (Q-005)

Baseline, not the NEAR integration. The first commit is `83c21b6` on 2026-11-04. There is no pre-hackathon tag, so the split is by path and by the headers in the files:

- `guard/intentguard_guard/vendor/risk_gate.py` and `risk_gate_config.json`. Paper/shadow pre-trade gate. The config comment describes a stage-1 perps book. `evaluate` calls `check` with an in-memory config and `market="skip"`. It does not call `fetch_market`. `fetch_market` and `check_order`, if called directly, request public Bybit linear tickers at `https://api.bybit.com/v5/market/tickers?category=linear`. The demo and `./run.sh` do not call them. Default config path is `risk_gate_config.json` (fixed 2026-11-10; the previous path `config.json` was not in the tree).
- `guard/intentguard_guard/vendor/launch_safety.py`. Header describes shared buy-safety checks. A comment dates stricter rug filters to 2026-10-09, before the hackathon announcement on 2026-10-19. The guard calls `decide` on fixture reports. `fetch` would call public RugCheck, DexScreener, and pump.fun URLs. The demo and unit tests do not call `fetch`.
- `guard/intentguard_guard/vendor/wallet_score.py`. Header: rule functions from `wallet_intel/server/score.py`, with the config block inlined.
- `guard/intentguard_guard/vendor/pool_reserve.py`. Header: Uniswap V4 helpers from `rh_trader`.

Provenance check on 2026-11-10. None of those four modules contains a copyright line, an SPDX identifier, or a LICENSE header. The headers name earlier files by path: `safety.py` / `watcher.py`, `wallet_intel/server/score.py`, and `rh_trader/rh_chain.py` plus `rh_safety.py`. The risk-gate file describes itself as a paper/shadow gate. Those paths are not published repositories. The GitHub account `Crypthorious` has one visible repository, this private `intentguard` repo. Web search for the distinctive comments (the 2026-10-09 `6W/26L` rug-filter note, `Pons graduation LP is a single wide position`, and `transfer_fed_share` together with this file's `capped at WATCH` wording) did not find this source. A GitHub code search for `6W/26L` returned unrelated win/loss notes, not this file. Code search for the Pons sentence was rate-limited, so that index was not fully searched.

No third-party copyright holder is identified, and no upstream license was found that would forbid MIT. `LICENSE` is the MIT grant for the code its copyright holder owns. It does not relicense `near-sdk` or `requests`, and it does not give anyone a license to a file the copyright holder does not own. The hackathon contact sentence is not a copyright license. If a vendored file was copied from someone else, that file has to be removed or replaced before the repository is made public. Agreeing to the contact sentence does not fix that.

Hackathon integration, written with AI coding assistance in Cursor: `contract/src/lib.rs`, `guard/intentguard_guard/guard.py`, `verdict.py`, `live_data.py`, `contract_sim.py`, `contract_testnet.py`, `oneclick.py`, `intents_stub.py`, `fixtures.py`, `guard/demo.py`, `guard/live_quote_check.py`, `guard/tests/`, `mcp/rugwall_mcp.py`, `dashboard/`, `scripts/`, and the docs. Runtime does not call NEAR AI Cloud or any other model. The verdicts are deterministic rules. If any integration file was written without an AI tool, correct this paragraph before submission.

Third-party libraries:

- `near-sdk` 5.29.1, published 2026-09-17, license `MIT OR Apache-2.0` (crate metadata). Rust edition 2024, rust-version 1.93.
- Python 3 standard library.
- `requests` 2.32.5, Apache-2.0 as published with the installed package. Used only if the vendored launch-safety fetchers are called. Its source is not in this repository. Installing it also installs its own dependencies under their own licenses.
- `cryptography` (Apache-2.0 OR BSD-3-Clause), for the guard's ed25519 verdict signatures. `ed25519-dalek` 2.2.0 (BSD-3-Clause) is a Rust dev-dependency used only by the contract unit tests to sign test verdicts.
- Public read-only data: NEAR mainnet RPC views on `v2.ref-finance.near` (`get_pool`) and the USDC / wNEAR token contracts (`ft_metadata`); NearBlocks testnet API v3 for the dashboard's transaction list.
- NEAR Intents 1Click HTTP API, called with `urllib` by the demo, the MCP tool and the opt-in script. No 1Click SDK is vendored. No JWT (Q-006). A keyless dry quote includes 1Click's usual fee inside the quoted price.

No other NEAR Hackathon submission is named in this repository (Q-015). If the same person submits a second project, name it here before the repository is made public.

## Testnet

v0.2 contract (signed verdicts): `guard2.intentguard-5821c5.testnet`, deployed 2026-11-12 with `new(owner, guard_public_key)`. The state layout changed (guard key and used nonces), so it went to a fresh sub-account instead of a migration. The v0.1 contract `guard.intentguard-5821c5.testnet` is unchanged. The owner of both is `intentguard-5821c5.testnet`. Deploy transactions, public keys and both live runs are in `DEPLOY_TESTNET.md`. `smoke_testnet.sh` still targets the v0.1 contract and its 4-argument `settle`, and refuses to run against any other contract. For v0.2 use `INTENTGUARD_NETWORK=testnet python3 guard/demo.py`.

The read-only state below is for the v0.1 contract.

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

The reproducible wasm is not the testnet code. The v0.1 testnet code is the 2026-11-01 non-reproducible artifact `build/intentguard.wasm`. The v0.2 testnet code is `build/intentguard-v0.2.wasm` (174,068 bytes, sha256 `deb22a07f3c32bc4bae37613ad344c7a6a4d4c383d887404a021bf4f6cb67904`, code hash `FzK5Y6nKKCW1ZqiLcgSoA8h4vXQYSZCWwKV2ASx196No`), a `non-reproducible-wasm` build from 2026-11-12. A reproducible build of v0.2 has not been recorded.

Checked 2026-11-10: two builds of commit `a3927dbd9b17dc32ad963f7f1cc2aa8cb54075cc` both produced sha256 `4c98ac5a7a89e383fce1e845cf63582ca489471adf1559bf31f8d495922cec74` (153,817 bytes). That result was written down in commit `3d14cd43486cd43181bdaf8d0eb178bcd24cf0de`. A build of any other commit embeds that other commit and will not match. A host `non-reproducible-wasm` build the same day, Rust 1.99.1, produced a third file of 153,321 bytes. The deployed file remains the committed 153,281-byte artifact. Details are in `DEPLOY_TESTNET.md`.

## Limitations

- Simulated settlement. Neither `ContractSim` nor on-chain `settle` submits an intent or transfers an asset. The signed verdict gates the contract's spend record, not a token transfer.
- The guard key is a single hot key in the guard process. Anyone who steals it can sign verdicts, though the caps, the kill switch and expiry still apply. The owner can rotate it with `set_guard_key`. There is no TEE attestation of the guard.
- Nonces are random 63-bit values and are stored forever. Storage grows by one entry per settlement, paid from the contract account's balance.
- The off-chain daily-cap check uses the stored `spent_in_window`. It does not apply the contract's 24-hour reset, so after the window rolls the guard can deny a settlement the contract would accept. It never allows one the contract would reject.
- Live data covers USDC → wNEAR only (Ref pool 4512, 1Click). The meme-token reports, their pools and the wallet histories in `fixtures.py` are synthetic, in RugCheck, DexScreener and wallet_intel shapes. The launch and reputation rules were written for Solana pump.fun-style data. They are not a NEAR token indexer.
- The price check compares a 1Click quote, which can route across venues, with one Ref pool. A large venue gap would show up as a deviation.
- The NEP-297 event string interpolates `agent`, the token ids and `intent_hash` without JSON escaping. Policy enforcement does not depend on the log.
- The dashboard's verdict log is a saved export, not a live guard service. The on-chain parts of the dashboard are live.
- No mainnet deployment and no claim of production custody.

## License

MIT, in `LICENSE`, for the code the copyright holder owns. Dependency licenses stay with those packages. See Disclosures for the vendored-file search.
