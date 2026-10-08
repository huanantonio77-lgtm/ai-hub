"""Dev reputation: getSignaturesForAddress on dev wallets of recent mints."""
import json, time, ssl, certifi, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / ".runtime" / "dev_reputation.jsonl"
RPC = "https://api.mainnet-beta.solana.com"
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
ctx = ssl.create_default_context(cafile=certifi.where())

def rpc_call(method, params, timeout=10):
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params
    }).encode()
    req = urllib.request.Request(RPC, data=payload, headers=UA)
    r = urllib.request.urlopen(req, timeout=timeout, context=ctx)
    return json.loads(r.read())

def dev_score(dev_pubkey, limit=100):
    try:
        resp = rpc_call("getSignaturesForAddress",
                        [dev_pubkey, {"limit": limit}])
        if "error" in resp:
            return {"dev": dev_pubkey, "error": str(resp["error"])[:120]}
        sigs = resp.get("result", [])
        n = len(sigs)
        # classify
        if n == 0:
            bucket = "new_dev"
        elif n <= 5:
            bucket = "occasional"
        elif n <= 30:
            bucket = "active"
        else:
            bucket = "serial"
        oldest = sigs[-1].get("blockTime") if sigs else None
        newest = sigs[0].get("blockTime") if sigs else None
        span_days = None
        if oldest and newest:
            span_days = round((newest - oldest) / 86400.0, 2)
        return {
            "dev": dev_pubkey,
            "total_sigs": n,
            "bucket": bucket,
            "oldest_ts": oldest,
            "newest_ts": newest,
            "span_days": span_days,
        }
    except urllib.error.HTTPError as e:
        return {"dev": dev_pubkey, "error": "HTTP " + str(e.code)}
    except Exception as e:
        return {"dev": dev_pubkey, "error": type(e).__name__ + ": " + str(e)[:80]}

def main():
    # load unique devs from recent mints
    seen, devs = set(), []
    with open(ROOT / ".runtime" / "mint_watch.jsonl") as f:
        for L in f:
            d = json.loads(L)
            dv = d.get("dev")
            if dv and dv not in seen:
                seen.add(dv)
                devs.append({"dev": dv, "symbol": d.get("symbol")})
            if len(devs) >= 10:
                break
    print("=== dev_reputation: " + str(len(devs)) + " unique devs ===")
    results = []
    for i, x in enumerate(devs):
        rep = dev_score(x["dev"])
        rep["symbol"] = x["symbol"]
        rep["checked_ts"] = int(time.time())
        print("  [" + str(i+1) + "/" + str(len(devs)) + "] " +
              str(x["symbol"])[:12].ljust(12) + " " +
              str(rep.get("bucket", "ERR")).ljust(11) + " " +
              "sigs=" + str(rep.get("total_sigs", "-")) + " " +
              "span=" + str(rep.get("span_days", "-")) + "d")
        results.append(rep)
        with open(JOURNAL, "a") as f:
            f.write(json.dumps(rep) + "\n")
        time.sleep(0.7)  # public RPC rate limit

    # summary
    from collections import Counter
    buckets = Counter(r.get("bucket", "err") for r in results)
    print("\n=== summary ===")
    for b, n in buckets.most_common():
        print("  " + b.ljust(12) + " " + str(n))
    print("  journal: " + str(JOURNAL))

if __name__ == "__main__":
    main()
