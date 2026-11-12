// Read-only dashboard. Talks only to public NEAR testnet RPC and the public NearBlocks testnet API.
// No wallet, no keys, no forms. All text from the network is inserted as text (no innerHTML of remote data).
"use strict";
const CONTRACT = "guard2.intentguard-5821c5.testnet";
const AGENT = "bot1";
const RPCS = ["https://rpc.testnet.near.org", "https://test.rpc.fastnear.com"];
// Regular RPC nodes forget transactions after a few days. Transaction lookups go to archival nodes first.
const TX_RPCS = ["https://archival-rpc.testnet.fastnear.com", "https://archival-rpc.testnet.near.org", ...RPCS];
const NB = `https://api-testnet.nearblocks.io/v3/accounts/${CONTRACT}/txns?limit=25`;
const EXPLORER = "https://testnet.nearblocks.io";
const $ = (s) => document.querySelector(s);

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
}
const txLink = (h) => h ? el("a", { href: `${EXPLORER}/txns/${h}`, target: "_blank", rel: "noopener", class: "mono" }, h.slice(0, 10) + "…") : el("span", { class: "muted" }, "-");
const usdc = (x) => (Number(x) / 1e6).toLocaleString(undefined, { maximumFractionDigits: 2 }) + " USDC";

async function rpc(body, urls = RPCS) {
  let last;
  for (const url of urls) {
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: "rw", ...body }) });
      const j = await r.json();
      if (j.error) throw new Error(JSON.stringify(j.error).slice(0, 200));
      if (j.result && j.result.error) throw new Error(j.result.error);
      if (urls === RPCS) $("#rpc-name").textContent = url.replace("https://", "");
      return j.result;
    } catch (e) { last = e; }
  }
  throw last;
}
async function view(method, args = {}) {
  const res = await rpc({ method: "query", params: { request_type: "call_function", finality: "final", account_id: CONTRACT, method_name: method, args_base64: btoa(JSON.stringify(args)) } });
  return JSON.parse(new TextDecoder().decode(new Uint8Array(res.result)) || "null");
}

async function loadPolicy() {
  const dl = $("#policy"); const err = $("#policy-err");
  err.hidden = true;
  try {
    const [cfg, pol, acct] = await Promise.all([
      view("get_config"), view("get_policy", { agent: AGENT }),
      rpc({ method: "query", params: { request_type: "view_account", finality: "final", account_id: CONTRACT } }),
    ]);
    const rows = [
      ["contract version", cfg.version],
      ["owner (human)", cfg.owner],
      ["kill switch", cfg.kill_switch ? el("b", { class: "bad" }, "ON: every settle is refused") : el("b", { class: "ok" }, "off")],
      ["guard_public_key", cfg.guard_public_key ? el("span", { class: "mono" }, cfg.guard_public_key) : el("b", { class: "bad" }, "not set: settle fails closed")],
      ["verdict max TTL", `${Number(cfg.max_verdict_ttl_ns) / 1e9} s (domain ${cfg.verdict_domain})`],
      [`agent ${AGENT} per-tx cap`, pol ? usdc(pol.per_tx_cap) : "not registered"],
      [`agent ${AGENT} daily cap`, pol ? usdc(pol.daily_cap) : "-"],
      [`spent in current 24h window`, pol ? `${usdc(pol.spent_in_window)} (${pol.settlements} settlements, window opened ${new Date(Number(pol.window_start_ns) / 1e6).toISOString().replace("T", " ").slice(0, 16)} UTC)` : "-"],
      [`agent ${AGENT} paused`, pol ? (pol.paused ? el("b", { class: "bad" }, "yes") : "no") : "-"],
      ["settlements (all agents)", cfg.settlements_total],
      ["contract account balance", (Number(BigInt(acct.amount) / 10n ** 20n) / 1e4).toFixed(2) + " testnet NEAR"],
      ["code hash", el("span", { class: "mono" }, acct.code_hash)],
    ];
    dl.replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  } catch (e) {
    err.textContent = "Could not read the contract over RPC: " + e.message; err.hidden = false;
  }
}

const txCache = new Map();
function getTx(hash, sender) {
  if (!txCache.has(hash)) txCache.set(hash, rpc({ method: "tx", params: { tx_hash: hash, sender_account_id: sender, wait_until: "NONE" } }, TX_RPCS).catch((e) => { txCache.delete(hash); throw e; }));
  return txCache.get(hash);
}
async function txOutcome(hash, sender) {
  const r = await getTx(hash, sender);
  const s = JSON.stringify(r.status || r);
  const err = s.match(/ERR_[A-Z_]+/);
  const logs = (r.receipts_outcome || []).flatMap((o) => o.outcome.logs || []);
  const ev = logs.map((l) => l.startsWith("EVENT_JSON:") ? JSON.parse(l.slice(11)) : null).find(Boolean);
  return { err: err && err[0], ev };
}

async function loadTxs() {
  const tb = $("#txs tbody");
  try {
    const j = await (await fetch(NB)).json();
    const txs = j.data || [];
    $("#tx-meta").textContent = `${txs.length} most recent`;
    const rows = txs.map((t) => {
      const methods = t.actions.map((a) => a.method || a.action.toLowerCase()).join(", ");
      const result = el("span", { class: t.outcomes.status ? "ok" : "bad" }, t.outcomes.status ? "ok" : "rejected");
      const tr = el("tr", {},
        el("td", { class: "mono" }, new Date(Number(t.block_timestamp) / 1e6).toISOString().replace("T", " ").slice(0, 19)),
        el("td", { class: "mono" }, methods),
        el("td", { class: "mono" }, t.signer_account_id === CONTRACT ? (methods.includes("settle") ? "agent key (settle-only)" : "contract account") : t.signer_account_id),
        el("td", {}, result),
        el("td", {}, txLink(t.transaction_hash)));
      if (methods.includes("settle")) {
        txOutcome(t.transaction_hash, t.signer_account_id).then(({ err, ev }) => {
          if (!t.outcomes.status && err) result.textContent = "rejected: " + err;
          else if (ev && ev.event === "settle") result.textContent = `ok: settled ${usdc(ev.data.amount)} → ${ev.data.token_out}, verdict nonce ${ev.data.verdict_nonce || "-"}`;
        }).catch(() => {});
      }
      return tr;
    });
    tb.replaceChildren(...(rows.length ? rows : [el("tr", {}, el("td", { colspan: 5 }, "No transactions yet."))]));
  } catch (e) {
    tb.replaceChildren(el("tr", {}, el("td", { colspan: 5, class: "err" }, "NearBlocks API unavailable: " + e.message)));
  }
}

let LOG = null;
const logReady = fetch("data/verdicts.json", { cache: "no-store" }).then((r) => r.json()).then((d) => (LOG = d));
async function loadLog() {
  try {
    const d = await logReady;
    $("#log-meta").textContent = `run ${new Date(d.generated_at * 1000).toISOString().replace("T", " ").slice(0, 16)} UTC · ${d.network} · ${d.result} as expected · data: ${d.data}`;
    if (d.market) {
      const p = d.market.pool, q = d.market.quote_50;
      $("#market").replaceChildren(
        el("div", {}, el("b", {}, "Ref Finance pool " + p.pool_id + ": "), `${Math.round(p.reserve_in).toLocaleString()} USDC / ${Math.round(p.reserve_out).toLocaleString()} wNEAR, fee ${(p.fee * 100).toFixed(2)}%`),
        el("div", {}, el("b", {}, "1Click dry quote: "), `$50 USDC → ${q.amount_out.toFixed(4)} wNEAR (dry=true)`),
        el("div", {}, el("b", {}, "Guard key: "), el("span", { class: "mono" }, d.guard_public_key)));
    }
    const rows = d.scenarios.map((s, i) => {
      const guardCell = s.kind === "bypass" ? el("span", { class: "muted" }, "skipped") : el("span", { class: "pill " + (s.verdict === "ALLOW" ? "allow" : "deny") }, s.verdict + (s.signed ? " · signed" : ""));
      let contract;
      if (s.kind === "bypass") contract = el("span", { class: "bad mono" }, s.onchain_error || s.got);
      else if (s.settle && typeof s.settle === "object") contract = el("span", { class: "ok" }, `settled ${usdc(s.settle.amount)}`);
      else contract = el("span", { class: "muted" }, "not sent");
      const why = s.kind === "bypass" ? el("span", {}, s.label) : (s.reasons && s.reasons.length ? el("ul", { class: "reasons" }, ...s.reasons.slice(0, 4).map((r) => el("li", {}, r)), s.reasons.length > 4 ? el("li", {}, `+${s.reasons.length - 4} more`) : null) : el("span", { class: "ok" }, s.deviation_pct != null ? `all checks pass (quote ${s.deviation_pct > 0 ? "+" : ""}${s.deviation_pct}% vs pool)` : "all checks pass"));
      return el("tr", {}, el("td", {}, i + 1), el("td", { class: "mono" }, s.scenario), el("td", {}, guardCell), el("td", {}, contract), el("td", {}, why), el("td", {}, s.data || "-"), el("td", {}, txLink(s.tx), s.tx ? liveBadge(s, d) : null));
    });
    $("#log tbody").replaceChildren(...rows);
  } catch (e) {
    $("#log tbody").replaceChildren(el("tr", {}, el("td", { colspan: 7, class: "err" }, "verdict log missing: " + e.message)));
  }
}

// Re-reads a logged transaction from NEAR testnet now and says whether the chain still shows the logged result.
function liveBadge(s, d) {
  const b = el("div", { class: "small muted" }, "checking chain…");
  onchainNow(s, d).then((o) => {
    const want = s.kind === "bypass" ? s.onchain_error : null;
    const same = o.live && (want ? o.error === want : o.ok);
    b.className = "small " + (same ? "ok" : "muted");
    b.textContent = o.live ? (same ? "✓ confirmed on-chain now" : "chain says: " + (o.error || "ok")) : "saved copy (RPC unreachable)";
  });
  return b;
}


// ---------------------------------------------------------------- live re-checks used by the log and "Try it"
const b64json = (b) => { const t = new TextDecoder().decode(Uint8Array.from(atob(b), (c) => c.charCodeAt(0))); return t ? JSON.parse(t) : null; };
async function onchainNow(s, d) {
  try {
    const r = await getTx(s.tx, d.contract);
    const fc = r.transaction.actions[0].FunctionCall;
    const st = r.status || {};
    const err = JSON.stringify(st).match(/ERR_[A-Z_]+/);
    return { live: true, args: b64json(fc.args), ok: "SuccessValue" in st, error: err && err[0],
             ret: "SuccessValue" in st ? b64json(st.SuccessValue) : null };
  } catch (e) {
    const o = s.onchain || {};
    return { live: false, args: o.args, ok: o.ok, error: o.error, ret: o.return, why: e.message };
  }
}
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
function b58decode(str) {
  let n = 0n;
  for (const ch of str) { const i = B58.indexOf(ch); if (i < 0) throw new Error("bad base58"); n = n * 58n + BigInt(i); }
  const out = [];
  while (n > 0n) { out.unshift(Number(n & 255n)); n >>= 8n; }
  for (const ch of str) { if (ch !== "1") break; out.unshift(0); }
  return new Uint8Array(out);
}
const hexBytes = (h) => new Uint8Array((h.match(/../g) || []).map((x) => parseInt(x, 16)));
// The exact bytes contract/src/lib.rs `verdict_message` and guard/intentguard_guard/verdict.py sign.
const verdictMessage = (contract, agent, a, tokenOut, v) => new TextEncoder().encode(
  ["intentguard-verdict-v1", contract, agent, a.intent_hash, a.amount, a.token_in, tokenOut, v.expires_at_ns, v.nonce].join("\n"));
async function verifyVerdict(guardPk, contract, agent, a, tokenOut) {
  const v = a.verdict;
  if (!v || !/^[0-9a-f]{128}$/i.test(v.signature)) return false;
  const key = await crypto.subtle.importKey("raw", b58decode(guardPk.replace("ed25519:", "")), { name: "Ed25519" }, false, ["verify"]);
  return crypto.subtle.verify({ name: "Ed25519" }, key, hexBytes(v.signature), verdictMessage(contract, agent, a, tokenOut, v));
}
let guardKeyNow = null;
async function guardKey(d) {
  if (!guardKeyNow) guardKeyNow = view("get_guard_key").then((k) => (k ? { key: k, live: true } : { key: d.guard_public_key, live: false })).catch(() => ({ key: d.guard_public_key, live: false }));
  return guardKeyNow;
}

// ---------------------------------------------------------------- Try it in 1 minute
const TRY = [
  { id: "1_safe_swap_usdc_wnear", title: "Safe swap", what: "Swap $50 USDC → wNEAR at a real 1Click quote, copying a wallet with a good record." },
  { id: "4_rug_bundled_token", title: "Rug token", what: "Buy $20 of a token with a bundled launch, mint authority, insiders and a 12% LP lock." },
  { id: "5_bad_quote_manipulated", title: "Rigged quote", what: "Swap $50 USDC → wNEAR, but the real 1Click quote was tampered with by 8% on the way to the agent." },
  { id: "6_copy_insider_wallet", title: "Copying an insider", what: "Copy a $30 trade from a wallet with an insider, dump-on-buyers record." },
  { id: "9_bypass_no_verdict", title: "Agent skips the guard", what: "A compromised agent calls settle directly: $10, inside every cap, no guard signature." },
  { id: "11_replay_old_verdict", title: "Replays an approval", what: "The agent re-sends the signed approval from the safe swap to get a second trade." },
  { id: "12_tamper_token", title: "Swaps the token after approval", what: "The guard approved $10 of wNEAR. The agent changes token_out to attacker.near and keeps the signature." },
  { id: "13_forged_verdict", title: "Forges an approval", what: "The agent signs its own \"approval\" with its own key." },
];
const CHECKS = [["risk", "Risk caps and kill switch", /^(risk_gate|contract):/], ["launch", "Rug check on the token", /^launch:/],
  ["price", "Quote vs pool price", /^price:/], ["reputation", "Copied wallet's track record", /^reputation:/]];
const WALLET_COPIED = new Set(["1_safe_swap_usdc_wnear", "6_copy_insider_wallet"]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let tryRun = 0;

function tryButtons() {
  const box = $("#try-buttons");
  box.replaceChildren(...TRY.map((t, i) => {
    const b = el("button", { type: "button", class: "chip", "data-i": i }, `${i + 1}. ${t.title}`);
    b.addEventListener("click", () => runTry(i));
    return b;
  }));
}

async function runTry(i) {
  const run = ++tryRun;
  const t = TRY[i];
  document.querySelectorAll("#try-buttons .chip").forEach((b) => b.classList.toggle("on", Number(b.dataset.i) === i));
  const out = $("#try-out");
  const step = (n, title) => { const body = el("div", { class: "step-b" }, el("span", { class: "muted" }, "…")); out.append(el("div", { class: "step" }, el("div", { class: "step-n" }, n), el("div", {}, el("b", {}, title), body))); return body; };
  out.replaceChildren(el("p", { class: "what" }, t.what));
  const d = LOG || await logReady;
  const s = d.scenarios.find((x) => x.scenario === t.id);
  if (run !== tryRun) return;
  const bypass = s.kind === "bypass";

  // 1 guard
  const g = step(1, "Rugwall guard checks the proposal");
  await sleep(350); if (run !== tryRun) return;
  if (bypass) g.replaceChildren(el("span", { class: "warn" }, "Skipped. The agent goes straight to the contract with its settle-only key."));
  else {
    g.replaceChildren(el("ul", { class: "checks" }, ...CHECKS.map(([name, label, re]) => {
      const bad = (s.reasons || []).filter((r) => re.test(r));
      if (!bad.length && name === "launch" && s.token_out === "wrap.near") return el("li", { class: "muted" }, "– " + label + ": skipped, wNEAR is an allowlisted major");
      if (!bad.length && name === "reputation" && !WALLET_COPIED.has(s.scenario)) return el("li", { class: "muted" }, "– " + label + ": no copied wallet in this trade");
      if (name === "price") label += s.data === "live" ? " (real 1Click quote vs real Ref pool, read at run time)" : " (fixture token and pool)";
      return el("li", { class: bad.length ? "bad" : "ok" }, (bad.length ? "✗ " : "✓ ") + label + (bad.length ? ": " + bad[0].replace(re, "").trim() + (bad.length > 1 ? ` (+${bad.length - 1} more)` : "") : ""));
    })), el("div", {}, "Verdict: ", el("span", { class: "pill " + (s.verdict === "ALLOW" ? "allow" : "deny") }, s.verdict)));
  }

  // 2 signature
  const sg = step(2, "Signed approval (ed25519), checked in your browser");
  const [oc, gk] = await Promise.all([s.tx ? onchainNow(s, d) : null, guardKey(d)]);
  if (run !== tryRun) return;
  const a = oc && oc.args;
  const agent = AGENT;
  if (!bypass && s.verdict === "DENY") sg.replaceChildren(el("span", {}, "None. Rugwall never signs a DENY, so this trade has no ticket to the chain."));
  else if (!a || !a.verdict) sg.replaceChildren(el("span", { class: "bad" }, "No signature attached."));
  else {
    const kids = [el("div", { class: "small mono" }, "sig " + a.verdict.signature.slice(0, 24) + "…  nonce " + a.verdict.nonce)];
    try {
      const ok = await verifyVerdict(gk.key, d.contract, agent, a, a.token_out);
      kids.push(el("div", { class: ok ? "ok" : "bad" }, ok ? `✓ Valid: signed by the guard key the contract stores (${gk.key.slice(0, 16)}…${gk.live ? ", read live" : ""}).`
        : `✗ Not valid for these exact fields under the guard key ${gk.key.slice(0, 16)}…`));
      if (t.id === "12_tamper_token") {
        const orig = await verifyVerdict(gk.key, d.contract, agent, a, "wrap.near");
        kids.push(el("div", { class: orig ? "ok" : "bad" }, `${orig ? "✓" : "✗"} The same signature over token_out = wrap.near (what the guard approved) is ${orig ? "valid" : "not valid"}. Changing one field broke it.`));
      }
      if (t.id === "11_replay_old_verdict") {
        const used = await view("is_nonce_used", { nonce: a.verdict.nonce }).catch(() => null);
        if (used != null) kids.push(el("div", { class: used ? "bad" : "ok" }, `is_nonce_used(${a.verdict.nonce.slice(0, 8)}…) on the contract right now: ${used}. This approval was already spent.`));
      }
    } catch (e) {
      kids.push(el("div", { class: "muted" }, "Your browser can't check Ed25519 signatures (" + e.message + "). The contract checks it on-chain anyway; see step 3."));
    }
    sg.replaceChildren(...kids);
  }

  // 3 contract
  const ct = step(3, "NEAR contract " + d.contract);
  await sleep(250); if (run !== tryRun) return;
  if (!s.tx) ct.replaceChildren(el("span", {}, "Nothing sent. The agent has no signed approval, and the contract refuses any settle without one."), " ",
    (() => { const b = el("button", { type: "button", class: "link" }, "See what happens if it tries anyway →"); b.addEventListener("click", () => runTry(4)); return b; })());
  else {
    const res = oc.ok ? el("b", { class: "ok" }, `Settled ${usdc(oc.args.amount)} → ${oc.args.token_out}${oc.ret ? `, ${usdc(oc.ret.remaining_daily)} left in today's cap` : ""}`)
      : el("b", { class: "bad" }, "Rejected: " + (oc.error || "failed"));
    ct.replaceChildren(res, el("div", { class: "small muted" }, oc.live ? "Read from NEAR testnet just now. " : "Saved copy (testnet RPC unreachable right now). ",
      el("a", { href: `${EXPLORER}/txns/${s.tx}`, target: "_blank", rel: "noopener" }, "Open the transaction on NearBlocks ↗")));
  }
  const nxt = (i + 1) % TRY.length;
  const nb = el("button", { type: "button" }, `Next: ${TRY[nxt].title} →`);
  nb.addEventListener("click", () => runTry(nxt));
  out.append(el("div", { class: "try-next" }, el("span", { class: "small muted" }, `Case ${i + 1} of ${TRY.length}  `), nb));
}

// ---------------------------------------------------------------- copy buttons for the agent snippets
document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#" + b.dataset.copy).textContent); b.textContent = "Copied"; }
  catch { b.textContent = "Select and copy"; }
  setTimeout(() => (b.textContent = "Copy"), 1500);
}));
document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".tabpane").forEach((p) => (p.hidden = p.id !== b.dataset.tab));
}));
$("#try-start").addEventListener("click", () => { $("#try").scrollIntoView({ behavior: "smooth", block: "start" }); runTry(0); });
tryButtons();

$("#contract-link").textContent = CONTRACT;
$("#contract-link").href = `${EXPLORER}/address/${CONTRACT}`;
$("#refresh").addEventListener("click", () => { loadPolicy(); loadTxs(); });
loadPolicy(); loadTxs(); loadLog();
