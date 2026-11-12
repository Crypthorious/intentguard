// Read-only dashboard. Talks only to public NEAR testnet RPC and the public NearBlocks testnet API.
// No wallet, no keys, no forms. All text from the network is inserted as text (no innerHTML of remote data).
"use strict";
const CONTRACT = "guard2.intentguard-5821c5.testnet";
const AGENT = "bot1";
const RPCS = ["https://rpc.testnet.near.org", "https://test.rpc.fastnear.com"];
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

async function rpc(body) {
  let last;
  for (const url of RPCS) {
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: "rw", ...body }) });
      const j = await r.json();
      if (j.error) throw new Error(JSON.stringify(j.error).slice(0, 200));
      if (j.result && j.result.error) throw new Error(j.result.error);
      $("#rpc-name").textContent = url.replace("https://", "");
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

async function txOutcome(hash, sender) {
  const r = await rpc({ method: "tx", params: { tx_hash: hash, sender_account_id: sender, wait_until: "NONE" } });
  const s = JSON.stringify(r);
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

async function loadLog() {
  try {
    const d = await (await fetch("data/verdicts.json", { cache: "no-store" })).json();
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
      return el("tr", {}, el("td", {}, i + 1), el("td", { class: "mono" }, s.scenario), el("td", {}, guardCell), el("td", {}, contract), el("td", {}, why), el("td", {}, s.data || "-"), el("td", {}, txLink(s.tx)));
    });
    $("#log tbody").replaceChildren(...rows);
  } catch (e) {
    $("#log tbody").replaceChildren(el("tr", {}, el("td", { colspan: 7, class: "err" }, "verdict log missing: " + e.message)));
  }
}

$("#contract-link").textContent = CONTRACT;
$("#contract-link").href = `${EXPLORER}/address/${CONTRACT}`;
$("#refresh").addEventListener("click", () => { loadPolicy(); loadTxs(); });
loadPolicy(); loadTxs(); loadLog();
