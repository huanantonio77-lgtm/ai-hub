# llm_cooldown.py (s94-2a) - classify HTTP 429 into rps/day/month and decide TTL.
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

TTL_RPS = 60
TTL_DAY = 6 * 3600
TTL_MONTH = 24 * 3600
LADDER = [1800, 7200, 21600, 86400]

DAY_MARKERS = ["per day", "daily", "day limit", "/day", "per-day"]
MONTH_MARKERS = ["per month", "monthly", "month limit", "/month", "per-month"]
RPS_MARKERS = ["per second", "rps", "requests per second", "/second", "rate limit"]
QUOTA_MARKERS = ["quota exceeded", "insufficient_quota", "out of quota"]


def _parse_retry_after(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        v = int(float(s))
        if v > 0:
            return v
    except Exception:
        pass
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        if delta > 0:
            return int(delta)
    except Exception:
        pass
    return None


def _classify_text(msg):
    if not msg:
        return None
    m = msg.lower()
    if any(x in m for x in MONTH_MARKERS):
        return "429_month"
    if any(x in m for x in DAY_MARKERS):
        return "429_day"
    if any(x in m for x in QUOTA_MARKERS):
        return "429_day"
    if any(x in m for x in RPS_MARKERS):
        return "429_rps"
    return None


def classify_429(headers, msg, prev_hits):
    if prev_hits is None or prev_hits < 0:
        prev_hits = 0
    ra_sec = None
    if headers:
        for k in ("Retry-After", "retry-after", "RETRY-AFTER"):
            if k in headers:
                ra_sec = _parse_retry_after(headers[k])
                break
    kind = _classify_text(msg)
    new_hits = prev_hits + 1
    if kind == "429_rps":
        ttl_kind = TTL_RPS
    elif kind == "429_day":
        ttl_kind = TTL_DAY
    elif kind == "429_month":
        ttl_kind = TTL_MONTH
    else:
        idx = min(prev_hits, len(LADDER) - 1)
        ttl_kind = LADDER[idx]
    if kind is None:
        kind = "429_unknown"
    if ra_sec is not None:
        if kind == "429_unknown":
            ttl = ra_sec
        else:
            ttl = max(ttl_kind, ra_sec)
    else:
        ttl = ttl_kind
    return kind, ttl, new_hits


def _selftest():
    from email.utils import format_datetime
    cases = []
    k, t, h = classify_429({"Retry-After": "120"}, "", 0)
    cases.append(("case1_ra_seconds", k, t, h, k == "429_unknown" and t == 120 and h == 1))
    fut = datetime.now(timezone.utc).timestamp() + 180
    dt = datetime.fromtimestamp(fut, tz=timezone.utc)
    k, t, h = classify_429({"Retry-After": format_datetime(dt)}, "", 0)
    cases.append(("case2_ra_httpdate", k, t, h, k == "429_unknown" and 170 <= t <= 190 and h == 1))
    k, t, h = classify_429({}, "daily limit reached", 0)
    cases.append(("case3_text_day", k, t, h, k == "429_day" and t == TTL_DAY and h == 1))
    k, t, h = classify_429({}, "Monthly quota exceeded", 0)
    cases.append(("case4_text_month", k, t, h, k == "429_month" and t == TTL_MONTH and h == 1))
    k, t, h = classify_429({}, "Rate limit exceeded", 0)
    cases.append(("case5_text_rps", k, t, h, k == "429_rps" and t == TTL_RPS and h == 1))
    k, t, h = classify_429({}, "", 0)
    cases.append(("case6_ladder_h0", k, t, h, k == "429_unknown" and t == 1800 and h == 1))
    k, t, h = classify_429({}, "", 1)
    cases.append(("case7_ladder_h1", k, t, h, k == "429_unknown" and t == 7200 and h == 2))
    k, t, h = classify_429({}, "", 2)
    cases.append(("case8_ladder_h2", k, t, h, k == "429_unknown" and t == 21600 and h == 3))
    k, t, h = classify_429({}, "", 5)
    cases.append(("case9_ladder_h5", k, t, h, k == "429_unknown" and t == 86400 and h == 6))
    k, t, h = classify_429({"Retry-After": "10"}, "daily limit reached", 0)
    cases.append(("case10_ra_shorter", k, t, h, k == "429_day" and t == TTL_DAY and h == 1))
    print("llm_cooldown selftest:")
    ok = 0
    for name, k, t, h, passed in cases:
        flag = "OK" if passed else "FAIL"
        print("  [" + flag + "] " + name + ": kind=" + k + " ttl=" + str(t) + " hits=" + str(h))
        if passed:
            ok += 1
    print("  passed " + str(ok) + "/" + str(len(cases)))
    return ok == len(cases)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    print("llm_cooldown: classify_429(headers, msg, prev_hits) -> (kind, ttl_sec, new_hits)")
