"""security/audit.py - hash-chain audit log (s88-1.5, v0.1.0).

Append-only log with SHA-256 chain. Tamper-evident.
"""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path


def canonical_json(d):
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _read_records(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            out.append({"__parse_error__": line[:120]})
    return out


def _last_prev_hash(records):
    if not records:
        return "genesis"
    last = records[-1]
    if "hash" in last:
        return last["hash"]
    return _sha256(canonical_json(last))


def append(entry, path):
    """Returns entry with prev_hash + hash added. Does NOT write to file."""
    records = _read_records(path)
    prev_hash = _last_prev_hash(records)
    entry = dict(entry)
    entry["prev_hash"] = prev_hash
    payload = dict(entry)
    payload.pop("hash", None)
    entry["hash"] = _sha256(prev_hash + canonical_json(payload))
    return entry


def verify_chain(path):
    records = _read_records(path)
    chained = 0
    pre_chain = 0
    prev_hash = None
    for idx, rec in enumerate(records):
        if "__parse_error__" in rec:
            return {"valid": False, "broken_at": idx, "reason": "parse error"}
        if "hash" not in rec:
            pre_chain += 1
            prev_hash = None
            continue
        if prev_hash is None:
            prev_hash = rec.get("prev_hash", "genesis")
        if rec.get("prev_hash") != prev_hash:
            return {"valid": False, "broken_at": idx, "reason": "prev_hash mismatch"}
        payload = dict(rec)
        payload.pop("hash", None)
        expected = _sha256(rec["prev_hash"] + canonical_json(payload))
        if expected != rec["hash"]:
            return {"valid": False, "broken_at": idx, "reason": "hash mismatch"}
        prev_hash = rec["hash"]
        chained += 1
    return {"valid": True, "chained": chained, "pre_chain": pre_chain}


def _selftest():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "log.jsonl"
        for i in range(3):
            e = append({"ts": "2026-10-01T0" + str(i) + ":00:00", "i": i}, f)
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(e, ensure_ascii=False) + chr(10))
        r1 = verify_chain(f)
        print("test1 (3 chained): " + str(r1))
        lines = f.read_text(encoding="utf-8").splitlines()
        tampered = lines[:]
        t1 = json.loads(tampered[1])
        t1["i"] = 999
        tampered[1] = json.dumps(t1, ensure_ascii=False)
        f.write_text(chr(10).join(tampered) + chr(10), encoding="utf-8")
        r2 = verify_chain(f)
        print("test2 (tampered): " + str(r2))
        f.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        r3 = verify_chain(f)
        print("test3 (restored): " + str(r3))
        f.write_text("", encoding="utf-8")
        r4 = verify_chain(f)
        print("test4 (empty): " + str(r4))
        ok = (r1.get("valid") and r1.get("chained") == 3) and (not r2.get("valid")) and (r3.get("valid")) and (r4.get("valid"))
        print("---")
        print("selftest passed=" + str(ok))
        return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", metavar="PATH")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.verify:
        r = verify_chain(args.verify)
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r.get("valid") else 1
    print("usage: python3 security/audit.py --verify PATH | --selftest")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# x
