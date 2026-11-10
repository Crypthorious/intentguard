# IntentGuard on NEAR testnet (deployed 2026-11-01, ~16:55 Reykjavik/UTC)

TESTNET ONLY. Faucet-funded, no real money. Nothing on mainnet.

| what | value |
|---|---|
| owner (human) account | `intentguard-5821c5.testnet` |
| contract account | `guard.intentguard-5821c5.testnet` (subaccount, funded with 4 testnet NEAR) |
| agent | `bot1`, function-call key `ed25519:H8wkRvoyUZp6tTh49iSirbMiCM9eSoSFrcYe9rvbv4K7` (receiver = contract, method `settle` only, 0.25 NEAR gas allowance) |
| policy | per-tx cap 100 USDC (`100000000`, 6 dp), daily cap 250 USDC (`250000000`) |
| wasm | `contract/target/near/intentguard.wasm`, 153,281 B, sha256 `a27e10243060b99ceb447ed3755a811ae70dcae0f2ff2cb322ed5a40932d0ca8` |
| on-chain code hash | `BwJYCHzNavSTyr462q3xFXTUr9NgP2bR6uUXXMmmfj3V` (= base58 sha256 of the local wasm, checked via RPC `view_code`) |
| toolchain | rustc stable, cargo-near 0.22.0, near-cli-rs 0.30.1, near-sdk 5.29.1 |

Explorer: https://testnet.nearblocks.io/address/guard.intentguard-5821c5.testnet

## Transactions
| step | tx |
|---|---|
| create owner account (faucet) | [7cRv1J1Jwe5Bd2EEdmk62XpEtCaURyn9Y8snLEPhzNPM](https://testnet.nearblocks.io/txns/7cRv1J1Jwe5Bd2EEdmk62XpEtCaURyn9Y8snLEPhzNPM) |
| create contract subaccount | [Aee3hdkrQWx9rao6KMEhtWtzdiAFJFZ6qNNH4n4rGXVq](https://testnet.nearblocks.io/txns/Aee3hdkrQWx9rao6KMEhtWtzdiAFJFZ6qNNH4n4rGXVq) |
| **deploy + `new(owner)`** | [6n9vuD8A3fGVpMyMcx6CNcHTLeLpM9cCcB7oY3YFFrL1](https://testnet.nearblocks.io/txns/6n9vuD8A3fGVpMyMcx6CNcHTLeLpM9cCcB7oY3YFFrL1) |
| register_agent bot1 | [5nUEBcfN7uXK9BNepBddTg39peVCz6tXGr5ZFd6jD4b8](https://testnet.nearblocks.io/txns/5nUEBcfN7uXK9BNepBddTg39peVCz6tXGr5ZFd6jD4b8) |
| add_agent_key bot1 | [9Kua39wnSQCeti4mfWQJUigW6uiMkREqiyV2wUTASApH](https://testnet.nearblocks.io/txns/9Kua39wnSQCeti4mfWQJUigW6uiMkREqiyV2wUTASApH) |
| settle 50 USDC (agent key) OK | [64j7YvZ4Cc2FyAMnyhnBZZjAEmYyRpFnzG115NJWT99b](https://testnet.nearblocks.io/txns/64j7YvZ4Cc2FyAMnyhnBZZjAEmYyRpFnzG115NJWT99b) |
| set_kill_switch true | [7sYTDd5ReqzgUe3RHz5MMjvN9F3HMLs4ha1KmvT8FfpH](https://testnet.nearblocks.io/txns/7sYTDd5ReqzgUe3RHz5MMjvN9F3HMLs4ha1KmvT8FfpH) |
| set_kill_switch false | [DKTGrCckksP9sfAguKowj2pqYTBpYGxQ9wjpwz2pCgDy](https://testnet.nearblocks.io/txns/DKTGrCckksP9sfAguKowj2pqYTBpYGxQ9wjpwz2pCgDy) |
| settle 100 OK | [9UNfYbp22ow1MjDGLuk9xWobvVArWRasBrLcbxGef8oc](https://testnet.nearblocks.io/txns/9UNfYbp22ow1MjDGLuk9xWobvVArWRasBrLcbxGef8oc) |
| settle 100 OK (daily cap reached) | [HKpNRZoBUXu2ST37ecjW9hbfUjPMWJrCzdAHyPXtFXow](https://testnet.nearblocks.io/txns/HKpNRZoBUXu2ST37ecjW9hbfUjPMWJrCzdAHyPXtFXow) |
| live demo: register_agent (window reset) | [3FYrWXjEY4uqxMFNgjrwbR4Q1ucuY5po5ygoqUJLWhro](https://testnet.nearblocks.io/txns/3FYrWXjEY4uqxMFNgjrwbR4Q1ucuY5po5ygoqUJLWhro) |
| live demo: settle 50 / settle 20 | [745umxfH...](https://testnet.nearblocks.io/txns/745umxfHfDo1dpCmxhuuEfGJQX4fRu51Fg44U3tbMR1o) / [EdUYz4tY...](https://testnet.nearblocks.io/txns/EdUYz4tYuKXfxoXPLpTVAKjANVWknhD5trJXpetY57Qo) |
| live demo: kill on / off | [n9j2LFrd...](https://testnet.nearblocks.io/txns/n9j2LFrdXSGXzRcdJDHdpF5mw6TuTJc3RjNDvKnzK2k) / [QLChCKRc...](https://testnet.nearblocks.io/txns/QLChCKRcMpbsuEGnaQqFqrxtNrAXSPfd63Txuo4CCEa) |

Rejected calls (contract panicked, nothing recorded; near-cli-rs 0.30.1 prints the panic but not the tx hash for failed calls,
see the account page on nearblocks): `ERR_NOT_OWNER` (contract full key calls register_agent), `ERR_OVER_PER_TX_CAP` (150),
`ERR_KEY_NOT_BOUND` (contract full-access key calls settle), `ERR_MUST_USE_AGENT_KEY` (owner calls settle directly),
`ERR_KILL_SWITCH_ON`, `ERR_OVER_DAILY_CAP` (1 USDC after 250 spent). The agent key calling `set_kill_switch` is refused by the
access-key permission (method not allowed; near-cli refuses before broadcast, the chain would reject it the same way).

## Smoke test results (2026-11-01, all as expected)
Views: `get_owner` = `intentguard-5821c5.testnet`, `is_killed` = false, `agent_for_key(<bot1 pk>)` = `bot1`.
Allowed: settle 50 -> remaining 200; settle 100 -> 100; settle 100 -> 0 (each emits a NEP-297 `EVENT_JSON` settle log).
Blocked: the 6 errors above + method-restricted key. Final `get_policy(bot1)`: spent 250/250, 3 settlements, kill switch off.
Live demo (`INTENTGUARD_NETWORK=testnet python3 guard/demo.py`): **9/9 scenarios as expected** against the real contract.

## Where the keys are (paths only, files are chmod 600, dirs 700, never commit them)
- owner full-access key: `~/.near-credentials/testnet/intentguard-5821c5.testnet.json`
- contract account full-access key: `~/.near-credentials/testnet/guard.intentguard-5821c5.testnet.json`
- agent bot1 function-call key: `~/.near-credentials/testnet/agent-keys/bot1.json`
(`~` = /home/box on the build box.)

## Commands
```bash
export PATH="$HOME/.cargo/bin:$PATH"
# rebuild
(cd contract && cargo near build non-reproducible-wasm)
# redeploy code only (state is kept; no init call; schema unchanged so this is safe)
near contract deploy guard.intentguard-5821c5.testnet use-file contract/target/near/intentguard.wasm \
  without-init-call network-config testnet sign-with-legacy-keychain send
# live smoke test (re-registers bot1 = resets its 24h window, then runs allowed + blocked calls)
./smoke_testnet.sh
# full demo against the live contract (default without the env var stays fully offline/simulated)
INTENTGUARD_NETWORK=testnet python3 guard/demo.py
# quick views
near contract call-function as-read-only guard.intentguard-5821c5.testnet get_policy json-args '{"agent":"bot1"}' network-config testnet now
near contract call-function as-read-only guard.intentguard-5821c5.testnet is_killed json-args '{}' network-config testnet now
```
If the contract's state layout changes, deploy to a fresh subaccount (e.g. `guard2.intentguard-5821c5.testnet`) with
`with-init-call new json-args '{"owner":"intentguard-5821c5.testnet"}' prepaid-gas '30 Tgas' attached-deposit '0 NEAR'`
instead of migrating.

## Read-only re-check (2026-11-10)

`python3 scripts/verify_testnet_code.py` against `https://rpc.testnet.near.org`. No credentials and no new transaction.

The committed `build/intentguard.wasm` was byte-identical to the code on `guard.intentguard-5821c5.testnet`. `get_owner` was `intentguard-5821c5.testnet`, `is_killed` was false, and `get_policy(bot1)` was per-tx `100000000`, daily `250000000`, spent `70000000`, settlements `2`, not paused. That spent amount matches the two allowed settlements in the offline demo (50 and 20 USDC at 6 decimals). It is the state left by the earlier testnet demo, not a payment made on 2026-11-10.

The 2026-11-01 smoke log above ended with 250/250 spent and was then reset by `register_agent` during the live demo. Trust the read-only script for the current state.

## Reproducible build

The 2026-11-01 deploy used `cargo near build non-reproducible-wasm` (cargo-near 0.22.0) because Docker and `[package.metadata.near.reproducible_build]` were not available then. That wasm is still the code on testnet. Do not replace it with a reproducible build unless you intend to redeploy.

Metadata added for later builds, image digest copied from the Docker Hub tag `sourcescan/cargo-near:0.23.0-rust-1.99.1` (single amd64 image, digest equals the tag digest):

- image: `sourcescan/cargo-near:0.23.0-rust-1.99.1`
- image_digest: `sha256:8013f039e8005627f10ae66b5519d1a6eeeed7d7aef4b5067d5e9a86c4302fcc`

Measured 2026-11-10. From a clean checkout of commit `a3927dbd9b17dc32ad963f7f1cc2aa8cb54075cc`, `cargo near build reproducible-wasm` was run twice. Both outputs were byte-identical:

| | |
|---|---|
| bytes | 153817 |
| sha256 | `4c98ac5a7a89e383fce1e845cf63582ca489471adf1559bf31f8d495922cec74` |
| base58 sha256 | `6A11akBUFFmCaj3K8Wa7uGAtyNipYk9yWyc3JPA1RJCs` |

That commit is the parent of the commit that records this table. A later commit embeds a new git revision, so a rebuild of `HEAD` will not match this hash. To reproduce it, check out `a3927dbd9b17dc32ad963f7f1cc2aa8cb54075cc` and run the command on a clean tree with Docker. This wasm is not deployed. Testnet still serves `build/intentguard.wasm`.
