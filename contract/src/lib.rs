//! IntentGuard on-chain policy contract (testnet only).
//!
//! The human owner registers an AI trading agent with a per-transaction cap and a rolling
//! 24h cap, and installs a *function-call access key* on this contract account that may only call
//! `settle`. The agent signs `settle` with that key; the contract identifies the agent by
//! `env::signer_account_pk()` and rejects any settlement that would exceed a cap, or when the
//! global kill switch / the agent's own pause flag is on. Even an agent process that bypasses the
//! off-chain guard cannot spend past these limits.
//!
//! Signed verdicts (v0.2): the off-chain guard holds an ed25519 key whose PUBLIC half is stored here.
//! `settle` only records a spend that carries a fresh, unused guard signature over the canonical
//! verdict message (see `verdict_message`). An agent that skips the guard has no signature, so the
//! contract rejects it with `ERR_NO_VERDICT` even when the amount is inside every cap. A replayed,
//! expired or tampered verdict is rejected with `ERR_REPLAY`, `ERR_VERDICT_EXPIRED` or `ERR_BAD_SIG`.
//!
//! SIMULATED: `settle` records the approved intent and emits a NEP-297 event; it does NOT forward
//! the signed intent to `intents.near` (verifier). That hand-off is marked TODO(intents) below.
use near_sdk::json_types::U128;
use near_sdk::json_types::U64;
use near_sdk::store::{IterableMap, LookupMap, LookupSet};
use near_sdk::{
    env, near, require, AccountId, Allowance, BorshStorageKey, CurveType, NearToken, PanicOnDefault,
    Promise, PublicKey,
};

const DAY_NS: u64 = 86_400_000_000_000;
/// A verdict may not be valid for longer than this (10 minutes) past the block that settles it.
pub const MAX_VERDICT_TTL_NS: u64 = 600_000_000_000;
pub const VERDICT_DOMAIN: &str = "intentguard-verdict-v1";

#[near(serializers = [borsh])]
#[derive(BorshStorageKey)]
enum Key {
    Agents,
    KeyToAgent,
    UsedNonces,
}

/// The guard's ALLOW verdict, attached by the agent to `settle`.
#[near(serializers = [json])]
#[derive(Clone, Debug, PartialEq)]
pub struct SignedVerdict {
    /// Random 64-bit nonce chosen by the guard. Each nonce settles at most once (`ERR_REPLAY`).
    pub nonce: U64,
    /// Block timestamp (ns) after which the verdict is void (`ERR_VERDICT_EXPIRED`).
    pub expires_at_ns: U64,
    /// Hex of the 64-byte ed25519 signature over `verdict_message(..)`.
    pub signature: String,
}

#[near(serializers = [json])]
#[derive(Debug, PartialEq)]
pub struct ContractConfig {
    pub owner: AccountId,
    pub kill_switch: bool,
    pub guard_public_key: Option<PublicKey>,
    pub max_verdict_ttl_ns: U64,
    pub verdict_domain: String,
    pub settlements_total: u64,
    pub version: String,
}

/// Canonical bytes the guard signs. Newline-separated, UTF-8. The contract id and agent name bind
/// the verdict to one contract and one agent; amount, tokens, intent hash, expiry and nonce bind it
/// to one trade.
pub fn verdict_message(
    contract: &str,
    agent: &str,
    intent_hash: &str,
    amount: u128,
    token_in: &str,
    token_out: &str,
    expires_at_ns: u64,
    nonce: u64,
) -> String {
    format!(
        "{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}",
        VERDICT_DOMAIN, contract, agent, intent_hash, amount, token_in, token_out, expires_at_ns, nonce
    )
}

fn decode_hex_sig(s: &str) -> Option<[u8; 64]> {
    let b = s.as_bytes();
    if b.len() != 128 {
        return None;
    }
    let mut out = [0u8; 64];
    for i in 0..64 {
        let hi = (b[2 * i] as char).to_digit(16)?;
        let lo = (b[2 * i + 1] as char).to_digit(16)?;
        out[i] = (hi * 16 + lo) as u8;
    }
    Some(out)
}

fn ed25519_bytes(pk: &PublicKey) -> [u8; 32] {
    require!(pk.curve_type() == CurveType::ED25519, "ERR_GUARD_KEY_NOT_ED25519");
    let raw = pk.as_bytes();
    let mut out = [0u8; 32];
    out.copy_from_slice(&raw[1..33]);
    out
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub struct AgentPolicy {
    /// Max size of one settlement, in the smallest unit of the quote asset (e.g. USDC 6 dp).
    pub per_tx_cap: U128,
    /// Max total settled within one window of `DAY_NS`.
    pub daily_cap: U128,
    pub spent_in_window: U128,
    pub window_start_ns: u64,
    pub paused: bool,
    pub settlements: u64,
}

#[near(serializers = [json])]
#[derive(Debug, PartialEq)]
pub struct SettleResult {
    pub agent: String,
    pub settlement_id: u64,
    pub amount: U128,
    pub remaining_daily: U128,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct IntentGuard {
    owner: AccountId,
    kill_switch: bool,
    agents: IterableMap<String, AgentPolicy>,
    key_to_agent: LookupMap<PublicKey, String>,
    next_settlement_id: u64,
    guard_public_key: Option<PublicKey>,
    used_nonces: LookupSet<u64>,
}

#[near]
impl IntentGuard {
    #[init]
    pub fn new(owner: AccountId, guard_public_key: Option<PublicKey>) -> Self {
        if let Some(pk) = &guard_public_key {
            ed25519_bytes(pk);
        }
        Self {
            owner,
            kill_switch: false,
            agents: IterableMap::new(Key::Agents),
            key_to_agent: LookupMap::new(Key::KeyToAgent),
            next_settlement_id: 0,
            guard_public_key,
            used_nonces: LookupSet::new(Key::UsedNonces),
        }
    }

    fn assert_owner(&self) {
        require!(env::predecessor_account_id() == self.owner, "ERR_NOT_OWNER");
    }

    // ---------------------------------------------------------------- owner (human) controls
    pub fn register_agent(&mut self, agent: String, per_tx_cap: U128, daily_cap: U128) {
        self.assert_owner();
        require!(per_tx_cap.0 <= daily_cap.0, "ERR_PER_TX_CAP_ABOVE_DAILY_CAP");
        let p = AgentPolicy {
            per_tx_cap,
            daily_cap,
            spent_in_window: U128(0),
            window_start_ns: env::block_timestamp(),
            paused: false,
            settlements: 0,
        };
        self.agents.insert(agent, p);
    }

    pub fn set_caps(&mut self, agent: String, per_tx_cap: U128, daily_cap: U128) {
        self.assert_owner();
        require!(per_tx_cap.0 <= daily_cap.0, "ERR_PER_TX_CAP_ABOVE_DAILY_CAP");
        let p = self.agents.get_mut(&agent).unwrap_or_else(|| env::panic_str("ERR_UNKNOWN_AGENT"));
        p.per_tx_cap = per_tx_cap;
        p.daily_cap = daily_cap;
    }

    /// Bind a function-call access key (only `settle` on this contract, limited gas allowance)
    /// to an agent. The owner calls this; the key is added to the contract account itself.
    pub fn add_agent_key(&mut self, agent: String, public_key: PublicKey, allowance_yocto: U128) -> Promise {
        self.assert_owner();
        require!(self.agents.contains_key(&agent), "ERR_UNKNOWN_AGENT");
        require!(!self.key_to_agent.contains_key(&public_key), "ERR_KEY_ALREADY_BOUND");
        self.key_to_agent.insert(public_key.clone(), agent);
        let allowance = Allowance::limited(NearToken::from_yoctonear(allowance_yocto.0))
            .unwrap_or_else(|| env::panic_str("ERR_ZERO_ALLOWANCE"));
        Promise::new(env::current_account_id()).add_access_key_allowance(
            public_key,
            allowance,
            env::current_account_id(),
            "settle".to_string(),
        )
    }

    pub fn revoke_agent_key(&mut self, public_key: PublicKey) -> Promise {
        self.assert_owner();
        self.key_to_agent.remove(&public_key);
        Promise::new(env::current_account_id()).delete_key(public_key)
    }

    pub fn set_kill_switch(&mut self, on: bool) {
        self.assert_owner();
        self.kill_switch = on;
        env::log_str(&format!("EVENT_JSON:{{\"standard\":\"intentguard\",\"version\":\"0.2.0\",\"event\":\"kill_switch\",\"data\":{{\"on\":{}}}}}", on));
    }

    /// Rotate the guard's verdict-signing key. Verdicts signed by the old key stop working at once.
    pub fn set_guard_key(&mut self, public_key: PublicKey) {
        self.assert_owner();
        ed25519_bytes(&public_key);
        env::log_str(&format!("EVENT_JSON:{{\"standard\":\"intentguard\",\"version\":\"0.2.0\",\"event\":\"guard_key\",\"data\":{{\"public_key\":\"{}\"}}}}", String::from(&public_key)));
        self.guard_public_key = Some(public_key);
    }

    pub fn set_agent_paused(&mut self, agent: String, paused: bool) {
        self.assert_owner();
        let p = self.agents.get_mut(&agent).unwrap_or_else(|| env::panic_str("ERR_UNKNOWN_AGENT"));
        p.paused = paused;
    }

    // ---------------------------------------------------------------- agent entry point
    /// Called by the agent with its function-call key (predecessor == this contract,
    /// signer_account_pk == the bound key). Panics (tx fails, nothing recorded) on any violation.
    /// `verdict` is the guard's signed ALLOW. Without it the call fails with `ERR_NO_VERDICT`.
    pub fn settle(
        &mut self,
        amount: U128,
        token_in: String,
        token_out: String,
        intent_hash: String,
        verdict: Option<SignedVerdict>,
    ) -> SettleResult {
        require!(env::predecessor_account_id() == env::current_account_id(), "ERR_MUST_USE_AGENT_KEY");
        let pk = env::signer_account_pk();
        let agent = self.key_to_agent.get(&pk).cloned().unwrap_or_else(|| env::panic_str("ERR_KEY_NOT_BOUND"));
        require!(!self.kill_switch, "ERR_KILL_SWITCH_ON");
        require!(amount.0 > 0, "ERR_ZERO_AMOUNT");
        let now = env::block_timestamp();
        let id = self.next_settlement_id;
        let p = self.agents.get_mut(&agent).unwrap_or_else(|| env::panic_str("ERR_UNKNOWN_AGENT"));
        require!(!p.paused, "ERR_AGENT_PAUSED");
        require!(amount.0 <= p.per_tx_cap.0, "ERR_OVER_PER_TX_CAP");
        // ---- signed guard verdict: present, well-formed, fresh, unused, valid signature
        let v = verdict.unwrap_or_else(|| env::panic_str("ERR_NO_VERDICT"));
        let guard_pk = self.guard_public_key.as_ref().unwrap_or_else(|| env::panic_str("ERR_GUARD_KEY_NOT_SET"));
        require!(now <= v.expires_at_ns.0, "ERR_VERDICT_EXPIRED");
        require!(v.expires_at_ns.0 - now <= MAX_VERDICT_TTL_NS, "ERR_VERDICT_TTL_TOO_LONG");
        require!(!self.used_nonces.contains(&v.nonce.0), "ERR_REPLAY");
        let sig = decode_hex_sig(&v.signature).unwrap_or_else(|| env::panic_str("ERR_BAD_SIG"));
        let msg = verdict_message(
            env::current_account_id().as_str(), &agent, &intent_hash, amount.0, &token_in, &token_out,
            v.expires_at_ns.0, v.nonce.0,
        );
        require!(env::ed25519_verify(&sig, msg.as_bytes(), &ed25519_bytes(guard_pk)), "ERR_BAD_SIG");
        if now.saturating_sub(p.window_start_ns) >= DAY_NS {
            p.window_start_ns = now;
            p.spent_in_window = U128(0);
        }
        let new_spent = p.spent_in_window.0.checked_add(amount.0).unwrap_or_else(|| env::panic_str("ERR_OVERFLOW"));
        require!(new_spent <= p.daily_cap.0, "ERR_OVER_DAILY_CAP");
        p.spent_in_window = U128(new_spent);
        p.settlements += 1;
        self.used_nonces.insert(v.nonce.0);
        let remaining = U128(p.daily_cap.0 - new_spent);
        self.next_settlement_id += 1;
        env::log_str(&format!(
            "EVENT_JSON:{{\"standard\":\"intentguard\",\"version\":\"0.2.0\",\"event\":\"settle\",\"data\":{{\"agent\":\"{}\",\"id\":{},\"amount\":\"{}\",\"token_in\":\"{}\",\"token_out\":\"{}\",\"intent_hash\":\"{}\",\"verdict_nonce\":\"{}\"}}}}",
            agent, id, amount.0, token_in, token_out, intent_hash, v.nonce.0
        ));
        // TODO(intents): forward the signed intent to the NEAR Intents verifier (`intents.near`,
        // method `execute_intents`) via a cross-contract call. Simulated in this build.
        SettleResult { agent, settlement_id: id, amount, remaining_daily: remaining }
    }

    // ---------------------------------------------------------------- views
    pub fn get_policy(&self, agent: String) -> Option<AgentPolicy> {
        self.agents.get(&agent).cloned()
    }
    pub fn is_killed(&self) -> bool {
        self.kill_switch
    }
    pub fn get_owner(&self) -> AccountId {
        self.owner.clone()
    }
    pub fn agent_for_key(&self, public_key: PublicKey) -> Option<String> {
        self.key_to_agent.get(&public_key).cloned()
    }
    pub fn get_guard_key(&self) -> Option<PublicKey> {
        self.guard_public_key.clone()
    }
    pub fn is_nonce_used(&self, nonce: U64) -> bool {
        self.used_nonces.contains(&nonce.0)
    }
    pub fn list_agents(&self) -> Vec<(String, AgentPolicy)> {
        self.agents.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
    }
    pub fn get_config(&self) -> ContractConfig {
        ContractConfig {
            owner: self.owner.clone(),
            kill_switch: self.kill_switch,
            guard_public_key: self.guard_public_key.clone(),
            max_verdict_ttl_ns: U64(MAX_VERDICT_TTL_NS),
            verdict_domain: VERDICT_DOMAIN.to_string(),
            settlements_total: self.next_settlement_id,
            version: "0.2.0".to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::testing_env;

    const T0: u64 = 1_000_000_000_000; // block time used by most tests (ns)

    fn owner() -> AccountId { "human.testnet".parse().unwrap() }
    fn contract() -> AccountId { "guard.testnet".parse().unwrap() }
    fn agent_pk() -> PublicKey { "ed25519:6E8sCci9badyRkXb3JoRpBj5p8C6Tw41ELDZoiihKEtp".parse().unwrap() }
    fn other_pk() -> PublicKey { "ed25519:DcA2MzgpJbrUATQLLceocVckhhAqrkingax4oJ9kZ847".parse().unwrap() }
    fn guard_sk() -> SigningKey { SigningKey::from_bytes(&[7u8; 32]) }
    fn rogue_sk() -> SigningKey { SigningKey::from_bytes(&[9u8; 32]) }
    fn near_pk(sk: &SigningKey) -> PublicKey {
        let mut v = vec![0u8]; // 0 = ED25519 curve tag
        v.extend_from_slice(sk.verifying_key().as_bytes());
        PublicKey::try_from(v).unwrap()
    }
    fn hex(b: &[u8]) -> String { b.iter().map(|x| format!("{:02x}", x)).collect() }

    /// What the off-chain guard does on ALLOW: sign the canonical message.
    fn sign_with(sk: &SigningKey, amount: u128, tin: &str, tout: &str, h: &str, nonce: u64, exp: u64) -> SignedVerdict {
        let m = verdict_message(contract().as_str(), "bot1", h, amount, tin, tout, exp, nonce);
        SignedVerdict { nonce: U64(nonce), expires_at_ns: U64(exp), signature: hex(&sk.sign(m.as_bytes()).to_bytes()) }
    }
    fn v(amount: u128, tin: &str, tout: &str, h: &str, nonce: u64) -> Option<SignedVerdict> {
        Some(sign_with(&guard_sk(), amount, tin, tout, h, nonce, T0 + 60_000_000_000))
    }
    /// Settle with a valid guard verdict (unique nonce derived from the intent hash).
    fn st(c: &mut IntentGuard, amount: u128, h: &str) -> SettleResult {
        let n = h.bytes().fold(17u64, |a, b| a.wrapping_mul(31).wrapping_add(b as u64));
        c.settle(U128(amount), "usdc".into(), "wnear".into(), h.into(), v(amount, "usdc", "wnear", h, n))
    }

    fn as_owner(ts: u64) {
        testing_env!(VMContextBuilder::new().current_account_id(contract()).predecessor_account_id(owner())
            .signer_account_id(owner()).block_timestamp(ts).build());
    }
    fn as_agent_key(pk: PublicKey, ts: u64) {
        testing_env!(VMContextBuilder::new().current_account_id(contract()).predecessor_account_id(contract())
            .signer_account_id(contract()).signer_account_pk(pk).block_timestamp(ts).build());
    }

    fn setup() -> IntentGuard {
        as_owner(0);
        let mut c = IntentGuard::new(owner(), Some(near_pk(&guard_sk())));
        c.register_agent("bot1".into(), U128(100), U128(250));
        let _ = c.add_agent_key("bot1".into(), agent_pk(), U128(250_000_000_000_000_000_000_000));
        c
    }

    // ------------------------------------------------------------ caps, kill switch, keys (v0.1)
    #[test]
    fn settle_within_caps_ok() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        let r = st(&mut c, 100, "h1");
        assert_eq!(r.agent, "bot1");
        assert_eq!(r.remaining_daily, U128(150));
        assert_eq!(c.get_policy("bot1".into()).unwrap().spent_in_window, U128(100));
    }

    #[test]
    #[should_panic(expected = "ERR_OVER_PER_TX_CAP")]
    fn over_per_tx_cap_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        st(&mut c, 101, "h");
    }

    #[test]
    #[should_panic(expected = "ERR_OVER_DAILY_CAP")]
    fn over_daily_cap_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        st(&mut c, 100, "1");
        st(&mut c, 100, "2");
        st(&mut c, 51, "3");
    }

    #[test]
    fn daily_window_resets() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        st(&mut c, 100, "1");
        st(&mut c, 100, "2");
        as_agent_key(agent_pk(), T0 + DAY_NS);
        let r = c.settle(U128(100), "usdc".into(), "wnear".into(), "3".into(),
            Some(sign_with(&guard_sk(), 100, "usdc", "wnear", "3", 3, T0 + DAY_NS + 1)));
        assert_eq!(r.remaining_daily, U128(150));
    }

    #[test]
    #[should_panic(expected = "ERR_KILL_SWITCH_ON")]
    fn kill_switch_blocks() {
        let mut c = setup();
        as_owner(1);
        c.set_kill_switch(true);
        as_agent_key(agent_pk(), T0);
        st(&mut c, 1, "h");
    }

    #[test]
    fn kill_switch_off_again_allows() {
        let mut c = setup();
        as_owner(1);
        c.set_kill_switch(true);
        c.set_kill_switch(false);
        as_agent_key(agent_pk(), T0);
        st(&mut c, 1, "h");
    }

    #[test]
    #[should_panic(expected = "ERR_AGENT_PAUSED")]
    fn paused_agent_blocked() {
        let mut c = setup();
        as_owner(1);
        c.set_agent_paused("bot1".into(), true);
        as_agent_key(agent_pk(), T0);
        st(&mut c, 1, "h");
    }

    #[test]
    #[should_panic(expected = "ERR_KEY_NOT_BOUND")]
    fn unbound_key_rejected() {
        let mut c = setup();
        as_agent_key(other_pk(), T0);
        st(&mut c, 1, "h");
    }

    #[test]
    #[should_panic(expected = "ERR_MUST_USE_AGENT_KEY")]
    fn external_caller_rejected() {
        let mut c = setup();
        as_owner(T0);
        st(&mut c, 1, "h");
    }

    #[test]
    #[should_panic(expected = "ERR_NOT_OWNER")]
    fn agent_cannot_flip_kill_switch() {
        let mut c = setup();
        as_agent_key(agent_pk(), 1);
        c.set_kill_switch(false);
    }

    #[test]
    #[should_panic(expected = "ERR_NOT_OWNER")]
    fn agent_cannot_raise_caps() {
        let mut c = setup();
        as_agent_key(agent_pk(), 1);
        c.set_caps("bot1".into(), U128(1_000_000), U128(1_000_000));
    }

    #[test]
    #[should_panic(expected = "ERR_PER_TX_CAP_ABOVE_DAILY_CAP")]
    fn invalid_caps_rejected() {
        as_owner(0);
        let mut c = IntentGuard::new(owner(), None);
        c.register_agent("x".into(), U128(10), U128(5));
    }

    #[test]
    fn key_binding_and_revoke() {
        let mut c = setup();
        assert_eq!(c.agent_for_key(agent_pk()), Some("bot1".into()));
        as_owner(1);
        let _ = c.revoke_agent_key(agent_pk());
        assert_eq!(c.agent_for_key(agent_pk()), None);
    }

    // ------------------------------------------------------------ signed verdicts (v0.2)
    #[test]
    #[should_panic(expected = "ERR_NO_VERDICT")]
    fn no_verdict_rejected_even_within_caps() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        c.settle(U128(10), "usdc".into(), "wnear".into(), "h".into(), None);
    }

    #[test]
    #[should_panic(expected = "ERR_BAD_SIG")]
    fn verdict_from_other_key_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        let bad = sign_with(&rogue_sk(), 10, "usdc", "wnear", "h", 1, T0 + 1_000);
        c.settle(U128(10), "usdc".into(), "wnear".into(), "h".into(), Some(bad));
    }

    #[test]
    #[should_panic(expected = "ERR_BAD_SIG")]
    fn tampered_amount_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        // guard approved 10, agent tries to settle 99 with the same signature
        c.settle(U128(99), "usdc".into(), "wnear".into(), "h".into(), v(10, "usdc", "wnear", "h", 1));
    }

    #[test]
    #[should_panic(expected = "ERR_BAD_SIG")]
    fn tampered_token_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        c.settle(U128(10), "usdc".into(), "attacker.near".into(), "h".into(), v(10, "usdc", "wnear", "h", 1));
    }

    #[test]
    #[should_panic(expected = "ERR_BAD_SIG")]
    fn tampered_intent_hash_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        c.settle(U128(10), "usdc".into(), "wnear".into(), "other".into(), v(10, "usdc", "wnear", "h", 1));
    }

    #[test]
    #[should_panic(expected = "ERR_BAD_SIG")]
    fn malformed_signature_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        let mut bad = v(10, "usdc", "wnear", "h", 1).unwrap();
        bad.signature = "zz".into();
        c.settle(U128(10), "usdc".into(), "wnear".into(), "h".into(), Some(bad));
    }

    #[test]
    #[should_panic(expected = "ERR_VERDICT_EXPIRED")]
    fn expired_verdict_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0 + 120_000_000_000); // 2 min later, verdict expired at +60 s
        c.settle(U128(10), "usdc".into(), "wnear".into(), "h".into(), v(10, "usdc", "wnear", "h", 1));
    }

    #[test]
    #[should_panic(expected = "ERR_VERDICT_TTL_TOO_LONG")]
    fn overlong_verdict_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        let long = sign_with(&guard_sk(), 10, "usdc", "wnear", "h", 1, T0 + MAX_VERDICT_TTL_NS + 1);
        c.settle(U128(10), "usdc".into(), "wnear".into(), "h".into(), Some(long));
    }

    #[test]
    #[should_panic(expected = "ERR_REPLAY")]
    fn replayed_verdict_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        let ok = v(10, "usdc", "wnear", "h", 42);
        c.settle(U128(10), "usdc".into(), "wnear".into(), "h".into(), ok.clone());
        assert!(c.is_nonce_used(U64(42)));
        c.settle(U128(10), "usdc".into(), "wnear".into(), "h".into(), ok);
    }

    #[test]
    #[should_panic(expected = "ERR_GUARD_KEY_NOT_SET")]
    fn no_guard_key_fails_closed() {
        as_owner(0);
        let mut c = IntentGuard::new(owner(), None);
        c.register_agent("bot1".into(), U128(100), U128(250));
        let _ = c.add_agent_key("bot1".into(), agent_pk(), U128(1));
        as_agent_key(agent_pk(), T0);
        st(&mut c, 10, "h");
    }

    #[test]
    #[should_panic(expected = "ERR_BAD_SIG")]
    fn rotated_guard_key_voids_old_verdicts() {
        let mut c = setup();
        as_owner(1);
        c.set_guard_key(near_pk(&rogue_sk()));
        assert_eq!(c.get_guard_key(), Some(near_pk(&rogue_sk())));
        as_agent_key(agent_pk(), T0);
        st(&mut c, 10, "h"); // signed by the old guard key
    }

    #[test]
    #[should_panic(expected = "ERR_NOT_OWNER")]
    fn agent_cannot_swap_guard_key() {
        let mut c = setup();
        as_agent_key(agent_pk(), 1);
        c.set_guard_key(near_pk(&rogue_sk()));
    }

    #[test]
    fn nonce_recorded_and_config_view() {
        let mut c = setup();
        as_agent_key(agent_pk(), T0);
        assert!(!c.is_nonce_used(U64(5)));
        c.settle(U128(10), "usdc".into(), "wnear".into(), "h".into(), v(10, "usdc", "wnear", "h", 5));
        assert!(c.is_nonce_used(U64(5)));
        let cfg = c.get_config();
        assert_eq!(cfg.settlements_total, 1);
        assert_eq!(cfg.guard_public_key, Some(near_pk(&guard_sk())));
        assert_eq!(cfg.max_verdict_ttl_ns, U64(MAX_VERDICT_TTL_NS));
        assert_eq!(c.list_agents().len(), 1);
    }

    #[test]
    fn verdict_message_is_canonical() {
        // The Python guard signs exactly these bytes (guard/tests/test_verdict.py checks the same vector).
        assert_eq!(
            verdict_message("guard.testnet", "bot1", "abc", 50_000_000, "usdc.near", "wrap.near", 1_700, 9),
            "intentguard-verdict-v1\nguard.testnet\nbot1\nabc\n50000000\nusdc.near\nwrap.near\n1700\n9"
        );
    }
}
