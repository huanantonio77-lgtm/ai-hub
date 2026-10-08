#!/usr/bin/env python3
"""flow_analysis.py - Phase 2: enrich market_flow.jsonl with current state + socials."""
import json, sys, time, pathlib, statistics, ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
import certifi

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLOW = ROOT / ".runtime" / "market_flow.jsonl"
OUT = ROOT / ".runtime" / "flow_analysis.jsonl"
REP = ROOT / ".runtime" / "flow_analysis_report.txt"
CTX = ssl.create_default_context(cafile=certifi.where())
UA = {"User-Agent": "Mozilla/5.0 ai-hub/1.0"}

sys.path.insert(0, str(ROOT / "scripts"))
from bonding_curve import fetch as bc_fetch


def fetch_socials(uri):
    if not uri:
        return {"twitter": "", "telegram": "", "website": ""}
    try:
        with urlopen(Request(uri, headers=UA), timeout=8, context=CTX) as r:
            d = json.loads(r.read())
        return {"twitter": d.get("twitter", "") or "", "telegram": d.get("telegram", "") or "", "website": d.get("website", "") or ""}
    except Exception:
        return {"twitter": "", "telegram": "", "website": ""}


def enrich(rec):
    mint = rec["mint"]
    out = dict(rec)
    out["v_sol_now"] = None
    out["growth"] = None
    out["complete"] = None
    out["age_min"] = None
    try:
        bc = bc_fetch(mint)
        if bc and "v_sol_reserves" in bc:
            vs = float(bc["v_sol_reserves"])
            if vs > 1e6:
                vs = vs / 1e9
            out["v_sol_now"] = vs
            iv = float(rec.get("vSol", 0) or 0)
            if iv > 0:
                out["growth"] = (vs / iv) ** 2 - 1.0
            out["complete"] = bool(bc.get("complete"))
    except Exception:
        pass
    out.update(fetch_socials(rec.get("uri", "")))
    out["age_min"] = (time.time() - rec["ts"]) / 60.0
    return out


def main():
    if not FLOW.exists():
        print("no flow file")
        return
    recs = [json.loads(l) for l in FLOW.read_text().splitlines() if l.strip()]
    seen = {}
    for r in recs:
        seen[r["mint"]] = r
    items = list(seen.values())
    print("unique mints:", len(items))
    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(enrich, r): r["mint"] for r in items}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                results.append(f.result())
            except Exception as e:
                print("err:", e)
            if i % 25 == 0:
                print("  progress:", i, "/", len(items))
    with OUT.open("w") as fh:
        for r in results:
            fh.write(json.dumps(r) + chr(10))

    P = []
    def w(s): P.append(s)
    w("=== FLOW ANALYSIS (" + str(len(results)) + " tokens) ===")
    valid = [r for r in results if r.get("growth") is not None]
    w("with growth: " + str(len(valid)) + "/" + str(len(results)))
    if valid:
        grew = [r for r in valid if r["growth"] > 0.05]
        flat = [r for r in valid if -0.05 <= r["growth"] <= 0.05]
        rug = [r for r in valid if r["growth"] < -0.05]
        w("  GREW (>+5%): " + str(len(grew)) + " (" + str(round(len(grew)/len(valid)*100, 1)) + "%)")
        w("  flat:        " + str(len(flat)) + " (" + str(round(len(flat)/len(valid)*100, 1)) + "%)")
        w("  RUG (<-5%):  " + str(len(rug)) + " (" + str(round(len(rug)/len(valid)*100, 1)) + "%)")
        avg = statistics.mean(r["growth"] for r in valid) * 100
        med = statistics.median(r["growth"] for r in valid) * 100
        w("  avg growth:  " + str(round(avg, 1)) + "%")
        w("  median:      " + str(round(med, 1)) + "%")
    tw = sum(1 for r in results if r.get("twitter"))
    tg = sum(1 for r in results if r.get("telegram"))
    ws = sum(1 for r in results if r.get("website"))
    w("")
    w("socials: twitter=" + str(tw) + " telegram=" + str(tg) + " website=" + str(ws))
    if valid:
        w("")
        w("growth by age bucket:")
        for lo, hi in [(0,2),(2,5),(5,10),(10,60)]:
            g = [r for r in valid if lo <= r["age_min"] < hi]
            if g:
                a = statistics.mean(r["growth"] for r in g) * 100
                w("  age [" + str(lo) + "," + str(hi) + ") min: n=" + str(len(g)) + " avg=" + str(round(a,1)) + "%")
        w("")
        w("growth by dev tier:")
        for lo, hi in [(0,1),(1,2),(2,5),(5,1000)]:
            g = [r for r in valid if lo <= r.get("dev_buy", 0) < hi]
            if g:
                a = statistics.mean(r["growth"] for r in g) * 100
                wc = sum(1 for r in g if r["growth"] > 0.05)
                w("  dev [" + str(lo) + "," + str(hi) + "): n=" + str(len(g)) + " avg=" + str(round(a,1)) + "% grew=" + str(wc) + "/" + str(len(g)))
        w("")
        w("growth by twitter:")
        for has in (True, False):
            g = [r for r in valid if bool(r.get("twitter")) == has]
            if g:
                a = statistics.mean(r["growth"] for r in g) * 100
                wc = sum(1 for r in g if r["growth"] > 0.05)
                w("  tw=" + str(has) + ": n=" + str(len(g)) + " avg=" + str(round(a,1)) + "% grew=" + str(wc) + "/" + str(len(g)))
        w("")
        w("top 10 growers:")
        for r in sorted(valid, key=lambda x: -x["growth"])[:10]:
            mint_s = r["mint"][:12]
            sym = str(r.get("symbol", ""))[:10]
            dev = r.get("dev_buy", 0)
            age = r["age_min"]
            gr = r["growth"] * 100
            hastw = "Y" if r.get("twitter") else "N"
            w("  " + mint_s + "... sym=" + sym + " dev=" + str(round(dev,2)) + " age=" + str(round(age,1)) + "m growth=" + str(round(gr)) + "% tw=" + hastw)
    w("")
    w("raw: " + str(OUT))
    txt = chr(10).join(P)
    print(txt)
    REP.write_text(txt)


if __name__ == "__main__":
    main()
