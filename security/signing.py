"""security/signing.py - Ed25519 sign/verify для immutable core (s88-1.6a)."""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization

def _silent(tag, e):
    """s104-2: emit silent except to errors.jsonl (K1 emission)."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        log = Path(__file__).resolve().parent.parent / ".cache" / "system" / "errors.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "kind": "silent", "where": "signing.py",
               "detail": tag + ": " + type(e).__name__ + ": " + str(e)[:100]}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


ROOT = Path(__file__).resolve().parent.parent
SEC_DIR = ROOT / "security"
KEYS_DIR = SEC_DIR / "keys"
PUBKEY = KEYS_DIR / "agent_ed25519.pub"
PRIVKEY = ROOT / ".secrets" / "agent_ed25519.key"
MANIFEST = SEC_DIR / "_core_manifest.json"

CORE_FILES = [
    "orchestrator.py",
    "security/signing.py",
    "self_apply.py",
    "session_verify.py",
    "catchup.py",
    "limits.py",
    "security/enforcer.py",
    "security/audit.py",
    "strategy/00_rules.md",
    "strategy/_features.json",
    "curator.py",
    "grounding.py",
    "grounding_audit.py",
    "self_description.py",
]


def _sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fingerprint(pub_bytes):
    return "sha256:" + hashlib.sha256(pub_bytes).hexdigest()[:32]


def load_privkey():
    if not PRIVKEY.exists():
        raise FileNotFoundError("privkey not found: " + str(PRIVKEY))
    data = PRIVKEY.read_bytes()
    return Ed25519PrivateKey.from_private_bytes(data)


def load_pubkey():
    if not PUBKEY.exists():
        raise FileNotFoundError("pubkey not found: " + str(PUBKEY))
    data = PUBKEY.read_bytes()
    return Ed25519PublicKey.from_public_bytes(data)


def keygen():
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    PRIVKEY.parent.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    PRIVKEY.write_bytes(priv_bytes)
    try:
        PRIVKEY.chmod(0o600)
    except Exception as _e:
        _silent("chmod_privkey", _e)
    PUBKEY.write_bytes(pub_bytes)
    return _fingerprint(pub_bytes)


def sign_file(path, priv):
    rel = str(Path(path).relative_to(ROOT))
    sha = _sha256_file(ROOT / rel)
    sig = priv.sign(sha.encode("utf-8")).hex()
    return {"sha256": sha, "sig": sig}


def sign_core():
    priv = load_privkey()
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    files = {}
    missing = []
    for rel in CORE_FILES:
        p = ROOT / rel
        if not p.exists():
            missing.append(rel)
            continue
        files[rel] = sign_file(p, priv)
    m = {
        "version": 1,
        "created": datetime.now().isoformat(timespec="seconds"),
        "pubkey_fingerprint": _fingerprint(pub_bytes),
        "files": files,
    }
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    return {"signed": len(files), "missing": missing}


def verify_core():
    if not MANIFEST.exists():
        return {"valid": False, "reason": "no manifest"}
    if not PUBKEY.exists():
        return {"valid": False, "reason": "no pubkey"}
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as e:
        return {"valid": False, "reason": "bad manifest json: " + str(e)[:80]}
    try:
        pub = load_pubkey()
    except Exception as e:
        return {"valid": False, "reason": "load pubkey fail: " + str(e)[:80]}
    files = m.get("files", {})
    bad = []
    for rel, meta in files.items():
        p = ROOT / rel
        if not p.exists():
            bad.append({"file": rel, "reason": "missing"})
            continue
        sha_now = _sha256_file(p)
        if sha_now != meta.get("sha256"):
            bad.append({"file": rel, "reason": "hash mismatch"})
            continue
        try:
            pub.verify(bytes.fromhex(meta["sig"]), sha_now.encode("utf-8"))
        except Exception:
            bad.append({"file": rel, "reason": "bad signature"})
    if bad:
        return {"valid": False, "reason": "tampered", "bad": bad, "checked": len(files)}
    return {"valid": True, "checked": len(files)}
