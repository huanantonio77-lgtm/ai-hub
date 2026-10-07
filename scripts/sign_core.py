"""scripts/sign_core.py - CLI для Ed25519 подписей immutable core (s88-1.6a)."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from security import signing


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="generate keypair")
    ap.add_argument("--sign", action="store_true", help="sign all CORE_FILES")
    ap.add_argument("--verify", action="store_true", help="verify manifest")
    args = ap.parse_args(argv)

    if args.init:
        if signing.PRIVKEY.exists():
            print("privkey already exists: " + str(signing.PRIVKEY))
            return 1
        fp = signing.keygen()
        print("pubkey fingerprint: " + fp)
        print("privkey: " + str(signing.PRIVKEY))
        print("pubkey:  " + str(signing.PUBKEY))
        return 0

    if args.sign:
        r = signing.sign_core()
        print("signed=" + str(r["signed"]))
        if r["missing"]:
            print("missing=" + str(r["missing"]))
        print("manifest: " + str(signing.MANIFEST))
        return 0

    if args.verify:
        r = signing.verify_core()
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r.get("valid") else 1

    print("usage: python3 scripts/sign_core.py --init | --sign | --verify")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
