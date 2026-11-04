//! IntentGuard on-chain policy contract (testnet only).
//!
//! The human owner registers an AI trading agent with a per-transaction cap and a rolling
//! 24h cap, and installs a *function-call access key* on this contract account that may only call
//! `settle`. The agent signs `settle` with that key; the contract identifies the agent by
//! `env::signer_account_pk()` and rejects any settlement that would exceed a cap, or when the
//! global kill switch / the agent's own pause flag is on. Even an agent process that bypasses the
//! off-chain guard cannot spend past these limits.
//!
//! SIMULATED: `settle` records the approved intent and emits a NEP-297 event; it does NOT forward
//! the signed intent to `intents.near` (verifier). That hand-off is marked TODO(intents) below.
use near_sdk::json_types::U128;
use near_sdk::store::{IterableMap, LookupMap};
use near_sdk::{
    env, near, require, AccountId, Allowance, BorshStorageKey, NearToken, PanicOnDefault, Promise,
    PublicKey,
};

const DAY_NS: u64 = 86_400_000_000_000;

#[near(serializers = [borsh])]
#[derive(BorshStorageKey)]
enum Key {
    Agents,
    KeyToAgent,
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
}

#[near]
impl IntentGuard {
    #[init]
    pub fn new(owner: AccountId) -> Self {
        Self {
            owner,
            kill_switch: false,
            agents: IterableMap::new(Key::Agents),
            key_to_agent: LookupMap::new(Key::KeyToAgent),
            next_settlement_id: 0,
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
        env::log_str(&format!("EVENT_JSON:{{\"standard\":\"intentguard\",\"version\":\"0.1.0\",\"event\":\"kill_switch\",\"data\":{{\"on\":{}}}}}", on));
    }

    pub fn set_agent_paused(&mut self, agent: String, paused: bool) {
        self.assert_owner();
        let p = self.agents.get_mut(&agent).unwrap_or_else(|| env::panic_str("ERR_UNKNOWN_AGENT"));
        p.paused = paused;
    }

    // ---------------------------------------------------------------- agent entry point
    /// Called by the agent with its function-call key (predecessor == this contract,
    /// signer_account_pk == the bound key). Panics (tx fails, nothing recorded) on any violation.
    pub fn settle(&mut self, amount: U128, token_in: String, token_out: String, intent_hash: String) -> SettleResult {
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
        if now.saturating_sub(p.window_start_ns) >= DAY_NS {
            p.window_start_ns = now;
            p.spent_in_window = U128(0);
        }
        let new_spent = p.spent_in_window.0.checked_add(amount.0).unwrap_or_else(|| env::panic_str("ERR_OVERFLOW"));
        require!(new_spent <= p.daily_cap.0, "ERR_OVER_DAILY_CAP");
        p.spent_in_window = U128(new_spent);
        p.settlements += 1;
        let remaining = U128(p.daily_cap.0 - new_spent);
        self.next_settlement_id += 1;
        env::log_str(&format!(
            "EVENT_JSON:{{\"standard\":\"intentguard\",\"version\":\"0.1.0\",\"event\":\"settle\",\"data\":{{\"agent\":\"{}\",\"id\":{},\"amount\":\"{}\",\"token_in\":\"{}\",\"token_out\":\"{}\",\"intent_hash\":\"{}\"}}}}",
            agent, id, amount.0, token_in, token_out, intent_hash
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::testing_env;

    fn owner() -> AccountId { "human.testnet".parse().unwrap() }
    fn contract() -> AccountId { "guard.testnet".parse().unwrap() }
    fn agent_pk() -> PublicKey { "ed25519:6E8sCci9badyRkXb3JoRpBj5p8C6Tw41ELDZoiihKEtp".parse().unwrap() }
    fn other_pk() -> PublicKey { "ed25519:DcA2MzgpJbrUATQLLceocVckhhAqrkingax4oJ9kZ847".parse().unwrap() }

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
        let mut c = IntentGuard::new(owner());
        c.register_agent("bot1".into(), U128(100), U128(250));
        let _ = c.add_agent_key("bot1".into(), agent_pk(), U128(250_000_000_000_000_000_000_000));
        c
    }

    #[test]
    fn settle_within_caps_ok() {
        let mut c = setup();
        as_agent_key(agent_pk(), 1);
        let r = c.settle(U128(100), "usdc".into(), "wnear".into(), "h1".into());
        assert_eq!(r.agent, "bot1");
        assert_eq!(r.remaining_daily, U128(150));
        assert_eq!(c.get_policy("bot1".into()).unwrap().spent_in_window, U128(100));
    }

    #[test]
    #[should_panic(expected = "ERR_OVER_PER_TX_CAP")]
    fn over_per_tx_cap_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), 1);
        c.settle(U128(101), "usdc".into(), "wnear".into(), "h".into());
    }

    #[test]
    #[should_panic(expected = "ERR_OVER_DAILY_CAP")]
    fn over_daily_cap_rejected() {
        let mut c = setup();
        as_agent_key(agent_pk(), 1);
        c.settle(U128(100), "a".into(), "b".into(), "1".into());
        c.settle(U128(100), "a".into(), "b".into(), "2".into());
        c.settle(U128(51), "a".into(), "b".into(), "3".into());
    }

    #[test]
    fn daily_window_resets() {
        let mut c = setup();
        as_agent_key(agent_pk(), 1);
        c.settle(U128(100), "a".into(), "b".into(), "1".into());
        c.settle(U128(100), "a".into(), "b".into(), "2".into());
        as_agent_key(agent_pk(), 1 + DAY_NS);
        let r = c.settle(U128(100), "a".into(), "b".into(), "3".into());
        assert_eq!(r.remaining_daily, U128(150));
    }

    #[test]
    #[should_panic(expected = "ERR_KILL_SWITCH_ON")]
    fn kill_switch_blocks() {
        let mut c = setup();
        as_owner(1);
        c.set_kill_switch(true);
        as_agent_key(agent_pk(), 2);
        c.settle(U128(1), "a".into(), "b".into(), "h".into());
    }

    #[test]
    fn kill_switch_off_again_allows() {
        let mut c = setup();
        as_owner(1);
        c.set_kill_switch(true);
        c.set_kill_switch(false);
        as_agent_key(agent_pk(), 2);
        c.settle(U128(1), "a".into(), "b".into(), "h".into());
    }

    #[test]
    #[should_panic(expected = "ERR_AGENT_PAUSED")]
    fn paused_agent_blocked() {
        let mut c = setup();
        as_owner(1);
        c.set_agent_paused("bot1".into(), true);
        as_agent_key(agent_pk(), 2);
        c.settle(U128(1), "a".into(), "b".into(), "h".into());
    }

    #[test]
    #[should_panic(expected = "ERR_KEY_NOT_BOUND")]
    fn unbound_key_rejected() {
        let mut c = setup();
        as_agent_key(other_pk(), 1);
        c.settle(U128(1), "a".into(), "b".into(), "h".into());
    }

    #[test]
    #[should_panic(expected = "ERR_MUST_USE_AGENT_KEY")]
    fn external_caller_rejected() {
        let mut c = setup();
        as_owner(1);
        c.settle(U128(1), "a".into(), "b".into(), "h".into());
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
        let mut c = IntentGuard::new(owner());
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
}
