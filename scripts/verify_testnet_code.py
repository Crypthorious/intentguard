#!/usr/bin/env python3
"""Read-only check: the committed wasm is the code on the testnet contract.

Default: v0.2 (signed verdicts), build/intentguard-v0.2.wasm vs guard2.intentguard-5821c5.testnet.
`--v1`: the original v0.1 build/intentguard.wasm vs guard.intentguard-5821c5.testnet (still live, unchanged).

Uses the public NEAR testnet RPC. No credentials, no signatures, no state changes.
Prints public view results only.
"""
import base64
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

V1 = "--v1" in sys.argv
RPC = os.environ.get("NEAR_TESTNET_RPC", "https://rpc.testnet.near.org")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if V1:
    CONTRACT = os.environ.get("INTENTGUARD_CONTRACT", "guard.intentguard-5821c5.testnet")
    WASM_PATH = os.path.join(ROOT, "build", "intentguard.wasm")
    EXPECTED_SHA256 = "a27e10243060b99ceb447ed3755a811ae70dcae0f2ff2cb322ed5a40932d0ca8"
    EXPECTED_CODE_HASH = "BwJYCHzNavSTyr462q3xFXTUr9NgP2bR6uUXXMmmfj3V"
else:
    CONTRACT = os.environ.get("INTENTGUARD_CONTRACT", "guard2.intentguard-5821c5.testnet")
    WASM_PATH = os.path.join(ROOT, "build", "intentguard-v0.2.wasm")
    EXPECTED_SHA256 = "deb22a07f3c32bc4bae37613ad344c7a6a4d4c383d887404a021bf4f6cb67904"
    EXPECTED_CODE_HASH = "FzK5Y6nKKCW1ZqiLcgSoA8h4vXQYSZCWwKV2ASx196No"

ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = ALPH[r] + out
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break
    return "1" * pad + out


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": "intentguard", "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json", "User-Agent": "intentguard-verify"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["result"]


def view(method_name, args):
    result = rpc("query", {
        "request_type": "call_function",
        "finality": "final",
        "account_id": CONTRACT,
        "method_name": method_name,
        "args_base64": base64.b64encode(json.dumps(args).encode()).decode(),
    })
    raw = bytes(result["result"])
    return json.loads(raw.decode() or "null")


def main():
    print("utc", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    print("contract", CONTRACT)
    print("rpc", RPC)
    local = open(WASM_PATH, "rb").read()
    local_sha = hashlib.sha256(local).hexdigest()
    local_b58 = b58(hashlib.sha256(local).digest())
    print("local_wasm_bytes", len(local))
    print("local_sha256", local_sha)
    print("local_code_hash", local_b58)
    code = rpc("query", {"request_type": "view_code", "finality": "final", "account_id": CONTRACT})
    remote = base64.b64decode(code["code_base64"])
    print("remote_code_hash", code.get("hash"))
    print("remote_wasm_bytes", len(remote))
    print("bytes_equal", remote == local)
    print("sha256_matches_deploy_record", local_sha == EXPECTED_SHA256)
    print("code_hash_matches_deploy_record", code.get("hash") == EXPECTED_CODE_HASH == local_b58)
    print("get_owner", json.dumps(view("get_owner", {})))
    print("is_killed", json.dumps(view("is_killed", {})))
    print("get_policy_bot1", json.dumps(view("get_policy", {"agent": "bot1"})))
    if not V1:
        print("get_guard_key", json.dumps(view("get_guard_key", {})))
    ok = remote == local and local_sha == EXPECTED_SHA256 and code.get("hash") == EXPECTED_CODE_HASH
    print("RESULT", "OK" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("RESULT ERROR", type(exc).__name__, str(exc)[:300])
        sys.exit(1)
