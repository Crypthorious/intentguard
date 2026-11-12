"""Signed guard verdicts (ed25519). The guard signs every ALLOW; the contract's `settle` verifies it.

Canonical message (UTF-8, newline-separated; identical to `verdict_message` in contract/src/lib.rs):

    intentguard-verdict-v1 \n <contract_id> \n <agent> \n <intent_hash> \n <amount> \n <token_in> \n <token_out> \n <expires_at_ns> \n <nonce>

The signer key is the guard's own key. It is NOT a NEAR account key and never signs a transaction.
Offline demo: a fresh key is generated per run. Live testnet demo: the key is read from a NEAR-style
key file outside the repo (~/.near-credentials/testnet/agent-keys/guard-verdict.json). Never logged."""
import json, os, secrets, time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

DOMAIN = "intentguard-verdict-v1"
DEFAULT_TTL_NS = 120 * 10**9            # 2 minutes; the contract refuses anything over 10 minutes
MAX_VERDICT_TTL_NS = 600 * 10**9
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b):
    n, out = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def b58decode(s):
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def verdict_message(contract, agent, intent_hash, amount, token_in, token_out, expires_at_ns, nonce):
    return "\n".join([DOMAIN, contract, agent, intent_hash, str(int(amount)), token_in, token_out,
                      str(int(expires_at_ns)), str(int(nonce))]).encode()


def near_pk_to_bytes(pk):
    if not pk.startswith("ed25519:"):
        raise ValueError("guard key must be ed25519")
    raw = b58decode(pk.split(":", 1)[1])
    if len(raw) != 32:
        raise ValueError("bad ed25519 public key length")
    return raw


class GuardSigner:
    def __init__(self, sk: Ed25519PrivateKey):
        self._sk = sk
        self.public_bytes = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    @classmethod
    def generate(cls):
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_seed(cls, seed32: bytes):
        return cls(Ed25519PrivateKey.from_private_bytes(seed32))

    @classmethod
    def from_key_file(cls, path):
        """NEAR key-file format: {"public_key": "ed25519:..", "private_key": "ed25519:<base58 64 bytes>"}."""
        with open(os.path.expanduser(path)) as f:
            sk = b58decode(json.load(f)["private_key"].split(":", 1)[1])
        return cls.from_seed(sk[:32])

    def save_key_file(self, path):
        seed = self._sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        os.makedirs(os.path.dirname(os.path.expanduser(path)), mode=0o700, exist_ok=True)
        fd = os.open(os.path.expanduser(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"public_key": self.public_key, "private_key": "ed25519:" + b58encode(seed + self.public_bytes)}, f)

    @property
    def public_key(self):
        return "ed25519:" + b58encode(self.public_bytes)

    def sign(self, contract, agent, intent_hash, amount, token_in, token_out, now_ns=None, ttl_ns=DEFAULT_TTL_NS, nonce=None):
        now_ns = time.time_ns() if now_ns is None else int(now_ns)
        exp = now_ns + int(ttl_ns)
        nonce = secrets.randbits(63) if nonce is None else int(nonce)
        sig = self._sk.sign(verdict_message(contract, agent, intent_hash, amount, token_in, token_out, exp, nonce))
        return {"nonce": str(nonce), "expires_at_ns": str(exp), "signature": sig.hex()}


def verify(public_bytes, contract, agent, intent_hash, amount, token_in, token_out, verdict):
    """Signature check only (freshness and replay are the contract's job). Returns True/False."""
    try:
        sig = bytes.fromhex(verdict["signature"])
        if len(sig) != 64:
            return False
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            sig, verdict_message(contract, agent, intent_hash, amount, token_in, token_out, verdict["expires_at_ns"], verdict["nonce"]))
        return True
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return False
