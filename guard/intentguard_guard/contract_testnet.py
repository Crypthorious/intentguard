"""LIVE backend: same interface as ContractSim, but talks to the deployed IntentGuard contract on NEAR TESTNET.
Views go to the public testnet RPC; transactions are signed by near-cli-rs (`near`) with keys from
~/.near-credentials (owner: legacy keychain; agent: function-call key file limited to `settle`).
Never prints key material. Testnet only: refuses any account id not ending in .testnet."""
import base64, json, os, re, shutil, subprocess, urllib.request

from .contract_sim import ContractError

RPC = os.environ.get("NEAR_TESTNET_RPC", "https://rpc.testnet.near.org")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class ContractTestnet:
    def __init__(self, owner, contract, agent_key_file, near_bin=None):
        for a in (owner, contract):
            if not a.endswith(".testnet"):
                raise ValueError(f"testnet only, refusing {a}")
        self.owner, self.contract, self.agent_key_file = owner, contract, os.path.expanduser(agent_key_file)
        self.near = near_bin or shutil.which("near") or os.path.expanduser("~/.cargo/bin/near")
        self.txs = []  # (label, tx_hash, ok)

    # ------------------------------------------------------------ views (RPC)
    def _view(self, method, args):
        body = {"jsonrpc": "2.0", "id": "ig", "method": "query", "params": {
            "request_type": "call_function", "finality": "final", "account_id": self.contract,
            "method_name": method, "args_base64": base64.b64encode(json.dumps(args).encode()).decode()}}
        req = urllib.request.Request(RPC, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "intentguard-demo"})
        r = json.load(urllib.request.urlopen(req, timeout=20))
        if "error" in r or "error" in r.get("result", {}):
            raise RuntimeError(f"view {method} failed: {r.get('error') or r['result']['error']}")
        return json.loads(bytes(r["result"]["result"]).decode() or "null")

    @property
    def kill_switch(self):
        return bool(self._view("is_killed", {}))

    def get_policy(self, agent):
        p = self._view("get_policy", {"agent": agent})
        if p is None:
            return None
        return {k: (int(v) if k in ("per_tx_cap", "daily_cap", "spent_in_window") else v) for k, v in p.items()}

    def agent_for_key(self, pk):
        return self._view("agent_for_key", {"public_key": pk})

    def get_config(self):
        return self._view("get_config", {})

    @property
    def guard_public_key(self):
        return self._view("get_guard_key", {})

    def agent_public_key(self):
        with open(self.agent_key_file) as f:
            return json.load(f)["public_key"]

    # ------------------------------------------------------------ transactions (near-cli)
    def _run(self, method, args, signer, sign_with, label):
        cmd = [self.near, "contract", "call-function", "as-transaction", self.contract, method, "json-args", json.dumps(args),
               "prepaid-gas", "50 Tgas", "attached-deposit", "0 NEAR", "sign-as", signer, "network-config", "testnet"] + sign_with + ["send"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        out = _ANSI.sub("", r.stdout + "\n" + r.stderr)
        m = re.search(r"Transaction ID: (\w+)", out)
        h = m.group(1) if m else None
        err = re.search(r"(ERR_[A-Z_]+)", out)
        if r.returncode != 0 or err or "panicked" in out:
            self.txs.append((label, h, False))
            raise ContractError(err.group(1) if err else "TX_FAILED (see near-cli output)")
        self.txs.append((label, h, True))
        m = re.search(r"Function execution return value[^\n]*:\s*\n(.*?)(?:\n\s*\n|\Z)", out, re.S)
        val = None
        try:
            val = json.loads(r.stdout.strip())
            m = None
        except ValueError:
            pass
        if m:
            txt = m.group(1).strip().replace("│", "").strip()
            try:
                val = json.loads(txt)
            except ValueError:
                val = txt or None
        return val, h

    def _owner_tx(self, method, args, label):
        return self._run(method, args, self.owner, ["sign-with-legacy-keychain"], label)

    # ------------------------------------------------------------ ContractSim-compatible API
    def register_agent(self, caller, agent, per_tx_cap, daily_cap, now_ns=0):
        # caller is ignored: always signed by the owner account; re-registering resets the 24h window.
        self._owner_tx("register_agent", {"agent": agent, "per_tx_cap": str(per_tx_cap), "daily_cap": str(daily_cap)}, f"register_agent {agent}")

    def add_agent_key(self, caller, agent, pk=None, allowance_yocto=250 * 10**21):
        pk = pk or self.agent_public_key()
        if self.agent_for_key(pk) == agent:
            return  # already bound on chain
        self._owner_tx("add_agent_key", {"agent": agent, "public_key": pk, "allowance_yocto": str(allowance_yocto)}, f"add_agent_key {agent}")

    def set_kill_switch(self, caller, on):
        self._owner_tx("set_kill_switch", {"on": bool(on)}, f"set_kill_switch {bool(on)}")

    def set_guard_key(self, caller, public_key):
        if self.guard_public_key == public_key:
            return
        self._owner_tx("set_guard_key", {"public_key": public_key}, "set_guard_key")

    def settle(self, signer_pk, amount, token_in, token_out, intent_hash, now_ns=None, verdict=None, label=None):
        # signer_pk and now_ns ignored: signed with the agent's function-call key file (key limited to `settle`);
        # the chain uses its own block time for the verdict expiry check.
        args = {"amount": str(amount), "token_in": token_in, "token_out": token_out, "intent_hash": intent_hash}
        if verdict is not None:
            args["verdict"] = verdict
        val, h = self._run("settle", args, self.contract, ["sign-with-access-key-file", self.agent_key_file], label or f"settle {amount}")
        if isinstance(val, dict):
            val = {k: (int(v) if k in ("amount", "remaining_daily") else v) for k, v in val.items()}
            val["tx"] = h
        return val
