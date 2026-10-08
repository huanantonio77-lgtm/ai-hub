"""bonding_curve.py (s209) - pump.fun bonding curve price via getAccountInfo.

PDA: seeds=["bonding-curve", mint_pubkey] under PUMP_PROGRAM.
Layout: 8 disc + 5*u64 + bool (49 bytes classic).
Price (SOL per token unit) = virtualSolReserves / virtualTokenReserves.
"""
from __future__ import annotations
import base64, json, ssl, sys
from pathlib import Path
from urllib.request import Request, urlopen
import certifi
from solders.pubkey import Pubkey

ROOT = Path(__file__).resolve().parent.parent
RPC = "https://api.mainnet-beta.solana.com"
_SSL = ssl.create_default_context(cafile=certifi.where())
_UA = {"Content-Type": "application/json", "User-Agent": "ai-hub/1.0"}

PUMP_PROGRAM = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
BONDING_SEED = b"bonding-curve"


def derive_pda(mint: str) -> Pubkey:
    pda, _ = Pubkey.find_program_address(
        [BONDING_SEED, bytes(Pubkey.from_string(mint))],
        PUMP_PROGRAM,
    )
    return pda


def _rpc(method: str, params: list) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = Request(RPC, data=body, headers=_UA)
    with urlopen(req, timeout=12, context=_SSL) as r:
        return json.loads(r.read())


def fetch(mint: str) -> dict | None:
    pda = derive_pda(mint)
    r = _rpc("getAccountInfo", [str(pda), {"encoding": "base64"}])
    val = (r.get("result") or {}).get("value")
    if not val:
        return {"pda": str(pda), "error": "account not found"}
    raw = base64.b64decode(val["data"][0])
    if len(raw) < 49:
        return {"pda": str(pda), "raw_len": len(raw), "error": "short"}
    off = 8
    v_tok = int.from_bytes(raw[off:off+8], "little"); off += 8
    v_sol = int.from_bytes(raw[off:off+8], "little"); off += 8
    r_tok = int.from_bytes(raw[off:off+8], "little"); off += 8
    r_sol = int.from_bytes(raw[off:off+8], "little"); off += 8
    supply = int.from_bytes(raw[off:off+8], "little"); off += 8
    complete = bool(raw[off])
    price_sol = (v_sol / v_tok) if v_tok else 0.0
    return {
        "pda": str(pda),
        "v_token_reserves": v_tok,
        "v_sol_reserves": v_sol,
        "real_token_reserves": r_tok,
        "real_sol_reserves": r_sol,
        "token_total_supply": supply,
        "complete": complete,
        "price_sol_per_token": price_sol,
        "raw_len": len(raw),
    }


if __name__ == "__main__":
    mints = sys.argv[1:]
    if not mints:
        print("usage: python3 scripts/bonding_curve.py MINT [MINT...]")
        sys.exit(2)
    for m in mints:
        try:
            print(m, "->", fetch(m))
        except Exception as e:
            print(m, "ERR:", e)
