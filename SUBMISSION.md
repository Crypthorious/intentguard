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
| Product is a NEAR contract plus a local guard, track `security` | Done in this repo |
| `LICENSE` present (MIT, Q-014) | Done |
| Libraries, prior code, and AI assistance listed in the README (Q-005) | Done |
| Simulated settlement separated from the read-only `dry: true` quote | Done in the README, the demo output, and this file |
| Default checks run without new keys | `./run.sh` and `python3 scripts/verify_testnet_code.py` |
| Reproducible wasm metadata | In `contract/Cargo.toml`. Double-build result in `DEPLOY_TESTNET.md` |
| Demo video of the real program | Record from the script below. Screenshots alone do not satisfy Q-012 |
| Repository public | Not done. Judges cannot open a private repo. A person has to change visibility. This work does not |
| Demo post published on X | Not done. Drafts are below. A person has to post and attach the video |
| Submission POST | Not done. Requires the fields marked "owner" and an explicit yes on the exact JSON |

## Entry fields

Send exactly these fields. `website` is a spam trap and must be omitted. `consent` stays false until the owner says the sentence.

| Field | Rule | Value for this project |
|---|---|---|
| requestId | UUID, reused on retries | `05235279-010a-42cd-826e-db49abaf0d55` |
| projectName | 2-80 characters | Proposed: `IntentGuard`. Owner confirms or replaces it |
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

AI trading agents fail open: a prompt injection can make the agent pay a bundled token, accept a manipulated quote, or copy a wallet that only looks profitable. IntentGuard is a policy firewall for that decision. Before a swap, an off-chain guard runs four fail-closed checks: a spending and kill-switch risk gate, launch safety (authorities, LP lock, insiders, holder concentration, liquidity), a price check against pool reserves, and a reputation score on the copied wallet. A NEAR testnet contract then enforces the per-transaction cap, the rolling 24-hour cap, and a human-owned kill switch. The agent holds a function-call access key that can call only settle on that contract, so it cannot raise caps, clear the kill switch, or transfer NEAR. NEAR is the control plane for those limits. This prototype does not settle on NEAR Intents: settle records the approved amount and emits an event, and it does not call intents.near or move tokens. Quotes in the default demo are simulated. A separate read-only command can request a 1Click quote with dry set to true, which returns no deposit and moves no funds.

## Demo script

Record the running program. Do not use slides. About two minutes.

1. Open a terminal in a fresh clone with dependencies installed (`README.md`, Fresh clone).
2. Run `python3 guard/demo.py`.
3. Leave the scrollback visible long enough to read three moments: `1_safe_swap_usdc_wnear` ALLOW, `4_rug_bundled_token` DENY with the rug reasons, and both `8_bypass_guard` rejections (`ERR_KILL_SWITCH_ON`, then `ERR_OVER_PER_TX_CAP`).
4. Leave the two lines above `RESULT: 9/9` visible. They say settlement is a simulated ledger and the quotes are fixtures.
5. Run `python3 scripts/verify_testnet_code.py`. The result to show is `bytes_equal True` and `RESULT OK`. Say that this is a public read of testnet code, not a new payment.
6. Optional, if the network is up: `python3 guard/live_quote_check.py`. Say that the line is a 1Click `dry: true` quote and that no swap was sent.
7. Stop. Do not open credential files, do not run `smoke_testnet.sh`, and do not sign anything in the video.

## Draft X post

The human posts this and attaches the video. Required words are in both drafts: built at NEAR HACKATHON, `@NEARProtocol`, `#NEARHackathon`.

Preferred draft (563 characters; needs a post length that allows it):

```
An AI agent with a wallet will pay the wrong thing once a prompt is injected. IntentGuard denies the swap first: caps, a rug and quote check, and a NEAR function-call key that can only call settle.

Built at NEAR HACKATHON. The caps and the kill switch are on a NEAR contract, so the agent cannot raise its own limit. Settlement through NEAR Intents is still simulated; the guard and the testnet caps are what you can run.

https://github.com/Crypthorious/intentguard
What should a human still have to approve before an agent spends?

@NEARProtocol #NEARHackathon
```

Fallback, 257 characters, inside the 280-character limit:

```
AI agents pay the wrong token when a prompt is injected. IntentGuard blocks it: NEAR caps and a key that can only call settle. Built at NEAR HACKATHON. Intents settlement is simulated. https://github.com/Crypthorious/intentguard @NEARProtocol #NEARHackathon
```

Optional extra tags from the rules, if the owner wants them: `@NearLegion` `@NearBuilders`.

## What still needs a person

1. The vendored modules have no identified third-party license. MIT covers them only if you wrote them. If you copied any of those files from someone else, name the file and remove or replace it before the repository is public. The hackathon contact sentence does not license another person's code.
2. Make the GitHub repository public, without force-push.
3. Record or accept the demo video and publish one of the drafts with the video attached.
4. Provide lead name, email, and team size.
5. Confirm project name `IntentGuard`, track `["security"]`, payout account `crypthorious.near`, and the idea text.
6. Say the consent sentence.
7. Review the exact JSON and say yes. Only then POST it to `https://nearhackathon.com/api/applications` with the reserved `requestId`.
