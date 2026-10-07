"""Free proxy pool: fetch, validate, pick by geo, rotate.

SOCKS5-aware. Uses Proxifly CDN. Caches live proxies in .runtime/.
"""
from __future__ import annotations
import json, ssl, socket, time, random
from pathlib import Path
from urllib.request import Request, urlopen
import certifi

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".runtime" / "proxy_pool.jsonl"
CACHE.parent.mkdir(parents=True, exist_ok=True)
GEO = ROOT / "self" / "geo" / "proxy_registry.json"

_SSL = ssl.create_default_context(cafile=certifi.where())
PROXIFLY_TPL = "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/{protocol}/data.json"

def fetch(protocol: str = "socks5") -> list:
    url = PROXIFLY_TPL.format(protocol=protocol)
    req = Request(url, headers={"User-Agent": "ai-hub/1.0"})
    with urlopen(req, timeout=20, context=_SSL) as r:
        return json.loads(r.read())

def _tcp_live(ip: str, port: int, timeout: float = 2.5) -> bool:
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False

def _socks5_handshake(ip: str, port: int, timeout: float = 4.0):
    """Minimal SOCKS5 CONNECT handshake. Returns True on success."""
    try:
        s = socket.create_connection((ip, int(port)), timeout=timeout)
        s.sendall(b"\x05\x01\x00")           # ver=5, nmethods=1, no-auth
        resp = s.recv(2)
        if len(resp) != 2 or resp[0] != 5 or resp[1] != 0:
            s.close(); return False
        # CONNECT to api.ipify.org:443
        host = b"api.ipify.org"
        req = b"\x05\x01\x00\x03" + bytes([len(host)]) + host + (443).to_bytes(2, "big")
        s.sendall(req)
        rep = s.recv(10)
        ok = len(rep) >= 2 and rep[1] == 0
        s.close()
        return ok
    except Exception:
        return False

def validate(entry: dict, socks: bool = True) -> bool:
    ip, port = entry.get("ip"), entry.get("port")
    if not ip or not port:
        return False
    if not _tcp_live(ip, int(port)):
        return False
    if socks and entry.get("protocol") == "socks5":
        return _socks5_handshake(ip, int(port))
    return True

def live_scan(entries: list, limit: int = 30, socks: bool = True) -> list:
    """TCP+handshake check on first N entries. Returns live list."""
    out = []
    for e in entries[:limit]:
        t0 = time.time()
        if validate(e, socks=socks):
            e = dict(e)
            e["latency_ms"] = int((time.time() - t0) * 1000)
            out.append(e)
    return out

def pick(geo_hint: str = None, prefer: list = None) -> dict | None:
    """Return fastest live proxy. Simple: reload cache, filter by country."""
    if not CACHE.exists():
        return None
    countries = set()
    if geo_hint and GEO.exists():
        try:
            g = json.loads(GEO.read_text())
            b = g.get("geo_bindings", {}).get(geo_hint, {})
            countries = set(b.get("preferred_countries", []))
        except Exception:
            pass
    pool = []
    for line in CACHE.read_text().splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        cc = (e.get("geolocation") or {}).get("country")
        if countries and cc not in countries:
            continue
        pool.append(e)
    if not pool:
        return None
    pool.sort(key=lambda e: e.get("latency_ms", 9999))
    return pool[0]

def save_live(live: list) -> None:
    with open(CACHE, "a") as f:
        for e in live:
            e["ts_saved"] = int(time.time())
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

def _real_ip_via(proxy: dict, timeout: float = 6.0) -> str | None:
    """Verify: get real exit IP through SOCKS5 proxy."""
    try:
        import socks  # PySocks optional
    except ImportError:
        return None
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, proxy["ip"], int(proxy["port"]))
        s.settimeout(timeout)
        s.connect(("api.ipify.org", 80))
        s.sendall(b"GET / HTTP/1.1\r\nHost: api.ipify.org\r\nConnection: close\r\n\r\n")
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if len(buf) > 4096:
                break
        s.close()
        body = buf.split(b"\r\n\r\n", 1)[-1].decode(errors="ignore").strip()
        return body if body and len(body) < 64 else None
    except Exception:
        return None

def smoke(n_check: int = 50, protocol: str = "socks5") -> None:
    print(f"fetching {protocol} list...")
    entries = fetch(protocol=protocol)
    print(f"  got {len(entries)} entries")
    print(f"scanning first {n_check} (TCP + SOCKS5 handshake)...")
    live = live_scan(entries, limit=n_check, socks=True)
    print(f"  live: {len(live)}/{n_check} ({100*len(live)//max(n_check,1)}%)")
    if not live:
        print("  WARN: no live proxies found in first batch")
        return
    save_live(live)
    print(f"  saved {len(live)} to {CACHE}")
    print("  top-3 by latency:")
    for e in sorted(live, key=lambda x: x.get("latency_ms", 9999))[:3]:
        cc = (e.get("geolocation") or {}).get("country", "?")
        print(f"    {e['ip']}:{e['port']}  cc={cc}  {e.get('latency_ms')}ms")

def http_get_via_socks5(proxy: dict, url: str, timeout: float = 10.0,
                        max_bytes: int = 8192) -> dict:
    """HTTP GET via SOCKS5. Pure stdlib. Returns {status, headers, body}."""
    from urllib.parse import urlparse
    u = urlparse(url)
    host = u.hostname
    port = u.port or (443 if u.scheme == "https" else 80)
    path = (u.path or "/") + (("?" + u.query) if u.query else "")

    # 1. TCP + SOCKS5 handshake
    s = socket.create_connection((proxy["ip"], int(proxy["port"])),
                                 timeout=timeout)
    s.sendall(b"\x05\x01\x00")
    if s.recv(2) != b"\x05\x00":
        s.close(); return {"status": 0, "error": "socks5 auth failed"}
    hb = host.encode()
    req = (b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb +
           port.to_bytes(2, "big"))
    s.sendall(req)
    resp = s.recv(10)
    if len(resp) < 2 or resp[1] != 0:
        s.close(); return {"status": 0, "error": "socks5 connect failed"}

    # 2. TLS if https
    if u.scheme == "https":
        ctx = ssl.create_default_context(cafile=certifi.where())
        try:
            s = ctx.wrap_socket(s, server_hostname=host)
        except Exception as e:
            s.close(); return {"status": 0, "error": f"tls: {e!r}"}

    # 3. HTTP request
    req = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
           f"User-Agent: Mozilla/5.0 ai-hub/1.0\r\n"
           f"Accept: application/json\r\nConnection: close\r\n\r\n").encode()
    s.sendall(req)

    buf = b""
    try:
        while len(buf) < max_bytes:
            chunk = s.recv(4096)
            if not chunk: break
            buf += chunk
    except socket.timeout:
        pass
    s.close()

    if b"\r\n\r\n" not in buf:
        return {"status": 0, "error": "no http response", "raw": buf[:200]}
    head, body = buf.split(b"\r\n\r\n", 1)
    try:
        status = int(head.split(b" ")[1])
    except Exception:
        status = 0
    return {"status": status, "bytes": len(body),
            "body_preview": body[:200].decode(errors="ignore")}
