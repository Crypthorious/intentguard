"""SIMULATED copy of the on-chain IntentGuard contract (contract/src/lib.rs), same rules and error strings.
Used by the demo when no testnet account is configured. Raising ContractError == the NEAR tx would panic.
v0.2: `settle` also requires a fresh, unused ed25519 guard verdict (see verdict.py), in the same order as lib.rs."""
from . import verdict as V

DAY_NS = 86_400_000_000_000


class ContractError(Exception):
    pass


class ContractSim:
    def __init__(self, owner, guard_public_key=None, contract="guard.sim.testnet"):
        self.owner, self.kill_switch, self.agents, self.key_to_agent, self.next_id = owner, False, {}, {}, 0
        self.contract, self.guard_public_key, self.used_nonces = contract, guard_public_key, set()
        self.events = []

    def set_guard_key(self, caller, public_key):
        self._owner(caller)
        V.near_pk_to_bytes(public_key)
        self.guard_public_key = public_key

    def get_config(self):
        return {"owner": self.owner, "kill_switch": self.kill_switch, "guard_public_key": self.guard_public_key,
                "max_verdict_ttl_ns": str(V.MAX_VERDICT_TTL_NS), "verdict_domain": V.DOMAIN,
                "settlements_total": self.next_id, "version": "0.2.0-sim"}

    def _owner(self, caller):
        if caller != self.owner:
            raise ContractError("ERR_NOT_OWNER")

    def register_agent(self, caller, agent, per_tx_cap, daily_cap, now_ns=0):
        self._owner(caller)
        if per_tx_cap > daily_cap:
            raise ContractError("ERR_PER_TX_CAP_ABOVE_DAILY_CAP")
        self.agents[agent] = {"per_tx_cap": per_tx_cap, "daily_cap": daily_cap, "spent_in_window": 0,
                              "window_start_ns": now_ns, "paused": False, "settlements": 0}

    def add_agent_key(self, caller, agent, pk):
        self._owner(caller)
        if agent not in self.agents:
            raise ContractError("ERR_UNKNOWN_AGENT")
        self.key_to_agent[pk] = agent

    def set_kill_switch(self, caller, on):
        self._owner(caller)
        self.kill_switch = bool(on)

    def get_policy(self, agent):
        return dict(self.agents[agent]) if agent in self.agents else None

    def settle(self, signer_pk, amount, token_in, token_out, intent_hash, now_ns, verdict=None):
        agent = self.key_to_agent.get(signer_pk)
        if agent is None:
            raise ContractError("ERR_KEY_NOT_BOUND")
        if self.kill_switch:
            raise ContractError("ERR_KILL_SWITCH_ON")
        if amount <= 0:
            raise ContractError("ERR_ZERO_AMOUNT")
        p = self.agents[agent]
        if p["paused"]:
            raise ContractError("ERR_AGENT_PAUSED")
        if amount > p["per_tx_cap"]:
            raise ContractError("ERR_OVER_PER_TX_CAP")
        if verdict is None:
            raise ContractError("ERR_NO_VERDICT")
        if self.guard_public_key is None:
            raise ContractError("ERR_GUARD_KEY_NOT_SET")
        exp, nonce = int(verdict["expires_at_ns"]), int(verdict["nonce"])
        if now_ns > exp:
            raise ContractError("ERR_VERDICT_EXPIRED")
        if exp - now_ns > V.MAX_VERDICT_TTL_NS:
            raise ContractError("ERR_VERDICT_TTL_TOO_LONG")
        if nonce in self.used_nonces:
            raise ContractError("ERR_REPLAY")
        if not V.verify(V.near_pk_to_bytes(self.guard_public_key), self.contract, agent, intent_hash, amount,
                        token_in, token_out, verdict):
            raise ContractError("ERR_BAD_SIG")
        if now_ns - p["window_start_ns"] >= DAY_NS:
            p["window_start_ns"], p["spent_in_window"] = now_ns, 0
        if p["spent_in_window"] + amount > p["daily_cap"]:
            raise ContractError("ERR_OVER_DAILY_CAP")
        p["spent_in_window"] += amount
        p["settlements"] += 1
        self.used_nonces.add(nonce)
        sid = self.next_id
        self.next_id += 1
        ev = {"event": "settle", "agent": agent, "id": sid, "amount": amount, "token_in": token_in,
              "token_out": token_out, "intent_hash": intent_hash, "verdict_nonce": str(nonce)}
        self.events.append(ev)
        return {"agent": agent, "settlement_id": sid, "amount": amount, "remaining_daily": p["daily_cap"] - p["spent_in_window"]}
