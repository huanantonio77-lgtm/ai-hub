"""own_stream.py (s213) - Rule 12: own primary data stream.
Primary: Helius accountSubscribe on pump.fun bonding-curve PDAs.
Create-source: PumpPortal subscribeNewToken (working, free).
API matches TradeStream.
"""
import asyncio, json, ssl, time, base64, struct, pathlib, certifi
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
import websockets
from solders.pubkey import Pubkey

ROOT = pathlib.Path(__file__).resolve().parent.parent
WINDOW_S = 60
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
V_SOL_OFFSET = 16
INCIDENTS = ROOT / ".runtime" / "vendor_incidents.jsonl"

def _incident(vendor, symptom, action="none"):
    try:
        INCIDENTS.parent.mkdir(parents=True, exist_ok=True)
        with INCIDENTS.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "vendor": vendor, "symptom": str(symptom)[:200], "action": action}) + chr(10))
    except Exception:
        pass

def derive_bonding_curve_pda(mint_str):
    program = Pubkey.from_string(PUMP_PROGRAM)
    mint = Pubkey.from_string(mint_str)
    pda, _ = Pubkey.find_program_address([b"bonding-curve", bytes(mint)], program)
    return str(pda)

@dataclass
class MintState:
    v_sol: float = 0.0
    events: deque = field(default_factory=deque)

class SolanaStream:
    def __init__(self, pumpportal_api_key, on_new_token=None, rpc_ws_url=None):
        if rpc_ws_url is None:
            _env = {}
            for _l in (ROOT / '.env').read_text().splitlines():
                if '=' in _l and not _l.startswith('#'):
                    _k, _v = _l.split('=', 1)
                    _env[_k.strip()] = _v.strip()
            _http = _env.get('HELIUS_RPC') or _env.get('CHAINSTACK_RPC') or _env.get('QUICKNODE_RPC')
            rpc_ws_url = _http.replace('https://', 'wss://').replace('http://', 'ws://')
        self.rpc_ws_url = rpc_ws_url
        self.pp_api_key = pumpportal_api_key
        self.on_new_token = on_new_token
        self._states = {}
        self._pda_to_mint = {}
        self._sub_to_mint = {}
        self._subscribed = set()
        self._pending_client_subs = {}
        self._ws = None
        self._pp_ws = None
        self._task = None
        self._pp_task = None
        self._running = False
        self._next_sub_id = 1

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_helius())
        self._pp_task = asyncio.create_task(self._run_pp())
        for _ in range(20):
            await asyncio.sleep(0.5)
            if self._ws is not None:
                return
        raise RuntimeError("Helius WS not ready in 10s")

    async def stop(self):
        self._running = False
        for t in (self._task, self._pp_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    async def _run_helius(self):
        ctx = ssl.create_default_context(cafile=certifi.where())
        while self._running:
            try:
                async with websockets.connect(self.rpc_ws_url, ssl=ctx, ping_interval=30, ping_timeout=60) as ws:
                    self._ws = ws
                    for mint in list(self._subscribed):
                        await self._send_account_sub(mint)
                    async for msg in ws:
                        if not self._running:
                            break
                        try:
                            d = json.loads(msg)
                        except Exception:
                            continue
                        self._handle_helius(d)
            except Exception as e:
                if self._running:
                    print("[solana_stream] helius ws err:", e)
                    _incident("helius_ws", e, "reconnect")
                    await asyncio.sleep(5)

    async def _run_pp(self):
        ctx = ssl.create_default_context(cafile=certifi.where())
        url = "wss://pumpportal.fun/api/data?api-key=" + self.pp_api_key
        while self._running:
            try:
                async with websockets.connect(url, ssl=ctx, ping_interval=30, ping_timeout=60) as ws:
                    self._pp_ws = ws
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    async for msg in ws:
                        if not self._running:
                            break
                        try:
                            d = json.loads(msg)
                        except Exception:
                            continue
                        if d.get("txType") == "create" and self.on_new_token:
                            try:
                                import inspect as _insp
                                if _insp.iscoroutinefunction(self.on_new_token):
                                    await self.on_new_token(d)
                                else:
                                    self.on_new_token(d)
                            except Exception as e:
                                print("[solana_stream] on_new err:", e)
            except Exception as e:
                if self._running:
                    print("[solana_stream] pp ws err:", e)
                    _incident("pumpportal_creates", e, "reconnect")
                    await asyncio.sleep(5)

    async def _send_account_sub(self, mint):
        try:
            pda = derive_bonding_curve_pda(mint)
            self._pda_to_mint[pda] = mint
            sub_id = self._next_sub_id
            self._next_sub_id += 1
            self._pending_client_subs[sub_id] = mint
            req = {"jsonrpc": "2.0", "id": sub_id, "method": "accountSubscribe", "params": [pda, {"encoding": "base64", "commitment": "confirmed"}]}
            await self._ws.send(json.dumps(req))
        except Exception as e:
            print("[solana_stream] sub err", mint[:12] + ":", e)

    async def subscribe_token(self, mint):
        if mint in self._subscribed:
            return
        self._subscribed.add(mint)
        self._states.setdefault(mint, MintState())
        if self._ws is not None:
            await self._send_account_sub(mint)

    async def unsubscribe_token(self, mint):
        self._subscribed.discard(mint)

    def _handle_helius(self, d):
        if "id" in d and "result" in d and d.get("id") in self._pending_client_subs:
            mint = self._pending_client_subs.pop(d["id"])
            self._sub_to_mint[d["result"]] = mint
            return
        if d.get("method") != "accountNotification":
            return
        params = d.get("params", {})
        sub_id = params.get("subscription")
        mint = self._sub_to_mint.get(sub_id)
        if not mint:
            return
        value = params.get("result", {}).get("value", {})
        data_field = value.get("data")
        if not isinstance(data_field, list) or len(data_field) < 1:
            return
        try:
            raw = base64.b64decode(data_field[0])
        except Exception:
            return
        if len(raw) < V_SOL_OFFSET + 8:
            return
        v_sol_lamports = struct.unpack_from("<Q", raw, V_SOL_OFFSET)[0]
        v_sol = v_sol_lamports / 1e9
        st = self._states.setdefault(mint, MintState())
        now = time.time()
        if st.v_sol > 0:
            delta = v_sol - st.v_sol
            if abs(delta) > 1e-9:
                st.events.append((now, delta))
        st.v_sol = v_sol

    def stats_for(self, mint, window_s=WINDOW_S):
        st = self._states.get(mint)
        if st is None:
            return None
        cutoff = time.time() - window_s
        while st.events and st.events[0][0] < cutoff:
            st.events.popleft()
        buy_sol = sum(e[1] for e in st.events if e[1] > 0)
        sell_sol = sum(-e[1] for e in st.events if e[1] < 0)
        total = buy_sol + sell_sol
        net = (buy_sol - sell_sol) / total if total > 0 else 0.0
        buy_count = sum(1 for e in st.events if e[1] > 0)
        sell_count = sum(1 for e in st.events if e[1] < 0)
        return {"buy_count": buy_count, "sell_count": sell_count, "buy_sol": buy_sol, "sell_sol": sell_sol, "unique_buyers": buy_count, "unique_sellers": sell_count, "net_pressure": net, "total_events": len(st.events), "v_sol_now": st.v_sol}
