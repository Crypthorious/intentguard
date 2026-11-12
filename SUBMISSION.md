# Submission checklist

Not submitted. The repository is private. Nothing in this file was sent to the hackathon API, posted on X, or used to change repository visibility.

Deadline: 2026-11-14T23:59:00Z. Judging starts 2026-11-16T00:00:00Z. Results by 2026-11-18T23:59:00Z. All times UTC (Reykjavik, UTC+0, has no offset).

Rules read from https://nearhackathon.com/HACKATHON.md on 2026-11-10. Read that file again before sending. A submission cannot be edited in place. Mistakes go through https://nearhackathon.com/request-changes. Do not submit twice.

Reserved `requestId` (reuse this exact value on a retry after a network error, 400, or 503; do not generate another):

`05235279-010a-42cd-826e-db49abaf0d55`

Do not commit a filled payload. It would contain the contact email. Keep that JSON in an untracked `SUBMISSION.local.json` if you want a local copy. `.gitignore` already excludes that name.

## Checklist

| Step | State |
|---|---|
| Product is a NEAR contract with on-chain signed-verdict checks plus a guard, track `security` | Done in this repo (v0.2 on testnet `guard2.intentguard-5821c5.testnet`) |
| `LICENSE` present (MIT, Q-014) | Done |
| Libraries, prior code, and AI assistance listed in the README (Q-005) | Done |
| Simulated settlement separated from the read-only `dry: true` quote | Done in the README, the demo output, and this file |
| Default checks run without new keys | `./run.sh` and `python3 scripts/verify_testnet_code.py` |
| Reproducible wasm metadata | In `contract/Cargo.toml`. Double-build result in `DEPLOY_TESTNET.md` |
| Demo video of the real program | `demo/intentguard-demo.mp4`: the live testnet run (13/13), rendered 2026-11-12 |
| Hosted demo (Q-012 plus) | https://rugwall-near.netlify.app, read-only. Keep it up until at least 2026-11-18, ideally 2026-11-25 |
| Repository public | Not done. Judges cannot open a private repo. A person has to change visibility. This work does not |
| Demo post published on X | Not done. Drafts are below. A person has to post and attach the video |
| Submission POST | Not done. Requires the fields marked "owner" and an explicit yes on the exact JSON |

## Entry fields

Send exactly these fields. `website` is a spam trap and must be omitted. `consent` stays false until the owner says the sentence.

| Field | Rule | Value for this project |
|---|---|---|
| requestId | UUID, reused on retries | `05235279-010a-42cd-826e-db49abaf0d55` |
| projectName | 2-80 characters | Proposed: `Rugwall`. Two other entries are already called IntentGuard. Alternatives: `Tradewarden`, `Copycatch`. The owner confirms one |
| leadName | 2-80 characters | Owner must provide. The git author handle is not a legal name and is not filled in here |
| email | valid email, max 160, at most 2 submissions | Owner must provide. `noreply@example.com` on the initial commit is a placeholder and must not be sent |
| size | one of `1`, `2 - 4`, `4 - 6`, `6 - 8`, `8+` | Owner must choose |
| tracks | one or more of the published ids, once each | Proposed: `["security"]`. This is the AI Security track. Do not add `defi` or `agents` unless the owner decides the project fits those tracks. Intents settlement is simulated, so this repo does not claim a live Intents product |
| nearAddress | 2-64 lowercase, account-id shape | Stated payout account: `crypthorious.near`. It matches the published pattern. Owner confirms it is the account that should be paid |
| projectUrl | public http(s) repo URL, max 300, unique | `https://github.com/Crypthorious/intentguard` after it is public. It was private on 2026-11-10 |
| demoUrl | public http(s) URL of the X post, max 300 | Owner pastes the post URL after publishing. No post exists yet |
| idea | 20-2000 characters | Draft below, 1111 characters. Owner edits before send |
| consent | boolean true only after the owner agrees | Not given. Required sentence, read verbatim: "I agree that the organizers may use these details to review our submission and contact us about this hackathon." |

Other owner facts, not API fields:

- Q-015: no second hackathon project is named in this repo. If one exists, name it in both READMEs before submit. One person, at most two different projects.
- Q-013: the team keeps the code. Organizers get non-exclusive promo rights to the name, screenshots, video, and repo link. No separate consent field. The owner should know that before posting.
- The contact email and lead name are personal data. They are not in this repository on purpose.

## Draft idea

1755 characters. The owner edits it before sending.

AI trading agents fail open: a prompt injection, a bundled rug token, a tampered solver quote or a copied insider wallet can drain a treasury in one transaction, and an off-chain checker does not help if a compromised agent simply skips it. Rugwall (formerly IntentGuard) is a rug, price and copy-trade firewall for NEAR trading agents. Before a swap, the guard runs four fail-closed checks: launch safety (mint and freeze authority, bundles, insiders, holder concentration, LP lock, liquidity), price sanity (a real NEAR Intents 1Click dry quote against live Ref Finance pool reserves), copied-wallet reputation, and the human's caps and kill switch read from the contract. Only an ALLOW is signed: an ed25519 verdict over the contract, agent, intent hash, amount, tokens, expiry and nonce. The NEAR contract stores the guard's public key and verifies the signature on-chain in settle. It rejects missing, expired, replayed or tampered verdicts, and it still enforces the per-transaction cap, the rolling 24-hour cap and the kill switch. The agent holds only a function-call access key limited to settle, so it cannot raise caps, swap the guard key or move NEAR. On NEAR testnet (guard2.intentguard-5821c5.testnet) the demo runs 13/13. Two signed swaps settle, five bad trades are denied, and six direct-to-contract attacks fail on-chain with ERR_KILL_SWITCH_ON, ERR_NO_VERDICT, ERR_OVER_PER_TX_CAP, ERR_REPLAY and ERR_BAD_SIG. A read-only dashboard (https://rugwall-near.netlify.app) shows the live policy, the guard key and every transaction with its on-chain result. A small MCP tool lets any agent ask Rugwall before it trades. Limits: settle records the spend and emits an event. It does not yet forward to intents.near or move tokens. Testnet only.

## Demo script

The rendered video is `demo/intentguard-demo.mp4`. It shows the real `INTENTGUARD_NETWORK=testnet python3 guard/demo.py` run from 2026-11-12, then the live dashboard. To re-record by hand:

1. Open https://rugwall-near.netlify.app and show the guard key, the caps and the rejected `settle` rows.
2. In a fresh clone, run `python3 guard/demo.py`. Hold on the `DATA: live` line, on `1_safe_swap_usdc_wnear` (ALLOW, signed), on `4_rug_bundled_token` (the rug reasons), and on `9_bypass_no_verdict` (`ERR_NO_VERDICT`).
3. Run `python3 scripts/verify_testnet_code.py` and show `bytes_equal True`, `RESULT OK`.
4. Don't open credential files or show `~/.near-credentials`.

## Draft X post

The human posts this and attaches the video. Both drafts include the required words: built at NEAR HACKATHON, `@NEARProtocol` and `#NEARHackathon`. Links count as 23 characters on X.

Preferred draft (539 characters, so it needs an account that allows long posts):

```
Your AI trading agent can be talked into buying a rug, taking a rigged quote or copying an insider wallet.

Rugwall checks every swap and signs only the safe ones. The NEAR contract verifies that signature on-chain, so an agent that skips the check can't settle, even inside its caps.

Built at NEAR HACKATHON. Testnet demo: 13/13, with real 1Click quotes and Ref Finance pool prices.

Live dashboard: https://rugwall-near.netlify.app
Code: https://github.com/Crypthorious/intentguard

What would you make an agent prove before it spends?

@NEARProtocol #NEARHackathon
```

Short draft (242 characters, within the 280 limit):

```
AI trading agents get tricked into rugs and rigged quotes. Rugwall checks each swap and signs only the safe ones. The NEAR contract rejects anything unsigned. Built at NEAR HACKATHON. Live: https://rugwall-near.netlify.app @NEARProtocol #NEARHackathon
```

Optional extra tags from the rules: `@NearLegion` `@NearBuilders`.

## What still needs a person

1. Make the GitHub repository public, without a force-push.
2. Confirm the project name (`Rugwall` is proposed), then post one of the drafts with the video attached.
3. Confirm the lead name, email, team size, tracks (`security` is proposed; `defi` and `agents` are optional), and payout account `crypthorious.near`.
4. Say the consent sentence.
5. Review the exact JSON and say yes. Only then POST it to `https://nearhackathon.com/api/applications` with the reserved `requestId`.
