"""verify.py — верификация ответа агента. Ловит галлюцинации.

Проверяет:
  1. URL из ответа → реальный <title> из HTML → сравнение с заявленным заголовком
  2. Числа (просмотры, проценты) → есть ли они в search_chunks
  3. При несовпадении — возвращает verdict: grounded / partial / hallucinated

Модуль автономный: ни от чего не зависит, можно дёргать из CLI.
"""
import re
import ssl
import urllib.request
from urllib.parse import urlparse

_UA = "Mozilla/5.0 (compatible; ai-hub-verify/1.0)"
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def extract_urls(text):
    """Все http(s) URL из текста, без хвостовых знаков препинания."""
    if not text:
        return []
    found = re.findall(r'https?://[^\s\)\]\,»"\'`]+', text)
    # срезаем хвостовые . , ; : )
    out = []
    for u in found:
        u = u.rstrip('.,;:)<>')
        if '<' in u or '>' in u:
            continue
        if len(u) > 15:
            out.append(u)
    return out


def _clean_title(t):
    """Приводим HTML-заголовок к сравнимому виду."""
    t = (t.replace("&#x2F;", "/").replace("&amp;", "&")
           .replace("&quot;", '"').replace("&#39;", "'")
           .replace("&laquo;", "«").replace("&raquo;", "»"))
    # отрезаем хвост " / Хабр" или " | Habr"
    t = re.split(r"\s*[/|]\s*", t)[0].strip()
    return t


def _fetch_title(url, timeout=12):
    """Реальный <title> страницы. None = недоступно (не галлюцинация)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            body = r.read(10000).decode("utf-8", "ignore")
        m = re.search(r"<title[^>]*>([^<]+)</title>", body, re.IGNORECASE)
        return _clean_title(m.group(1).strip()) if m else ""
    except Exception:
        return None


def _similarity(a, b):
    """Доля общих слов (простая мера)."""
    wa = set(re.findall(r'\w+', a.lower()))
    wb = set(re.findall(r'\w+', b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


_TRUSTED_DOMAINS = ("ainova.ooo", "github.com/ai-hub",
                   "github.com/salamkhalikov",
                   "api.tavily.com", "api.cohere.com", "api.cloudflare.com",
                   "api.openai.com", "api.mistral.ai", "openrouter.ai/api")


def _is_trusted(url):
    """netloc-match + path-prefix (s62). Заменяет substring-match."""
    try:
        parsed = urlparse(url or "")
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if not host:
        return False
    for d in _TRUSTED_DOMAINS:
        d = d.lower()
        if "/" in d:
            dom, _, sub = d.partition("/")
            if (host == dom or host.endswith("." + dom)) and path.startswith("/" + sub):
                return True
        else:
            if host == d or host.endswith("." + d):
                return True
    return False


def _find_claimed_title(text, url):
    """Заголовок статьи, СВЯЗАННЫЙ с этим URL.

    Возвращает None, если заголовок не удаётся надёжно связать.
    Строгие правила (иначе ложные срабатывания — «Источник:», «URL:»):

    1. markdown-ссылка [TITLE](url) — самый надёжный случай
    2. «TITLE» — url (в пределах 60 симв.)
    3. "TITLE" — url
    4. TITLE\nurl — заголовок строкой выше

    Окно 150 симв. до URL (а не 400) — иначе ловим заголовки секций.
    """
    idx = text.find(url)
    if idx == -1:
        return None
    window = text[max(0, idx - 200):idx]

    def _reject_url_like(s):
        """Отсев: URL, JSON-обломки, placeholder'ы — это не заголовок."""
        if not s:
            return None
        s = s.strip()
        if s.startswith(("http://", "https://")):
            return None
        s = s.lstrip("*-• ").strip()
        if s.startswith(("http://", "https://")):
            return None
        # JSON-обломки и служебные метки
        import re as _re2
        low = s.lower()
        for marker in ('"url"', "'url'", "url:", "url :", "ссылка:",
                       "источник:", "link:", "href", "просмотр:",
                       "заголовок:", "title:"):
            if marker in low:
                return None
        # Слишком короткое
        if len(s) < 8:
            return None
        # Начинается со служебного символа — обломок
        if s[:1] in ("'", '"', ":", ",", "}", "]"):
            return None
        # Только пунктуация/цифры/пробелы
        if not _re2.search(r"[A-Za-zА-Яа-яЁё]{3,}", s):
            return None
        return s

    # 1. markdown: [TITLE](url) — но проверим, что это реально в окне
    esc = url.replace("(", "\\(").replace(")", "\\)")
    m = re.search(
        r'\[([^\]\n]{5,200})\]\(' + esc + r'\)',
        text)
    if m:
        return _reject_url_like(m.group(1))

    # 2-3. «TITLE» рядом с URL (в пределах 60 симв. перед url)
    m = re.search(
        r'[«"]([^»"\n]{8,200})[»"]\s*[-—:]?\s*$',
        window[-80:])
    if m:
        return _reject_url_like(m.group(1))

    # 4. Заголовок на строке прямо перед URL (без маркеров списка/двоеточия)
    last_line = window.rstrip().split("\n")[-1].strip()
    if (8 <= len(last_line) <= 200
            and not last_line.endswith((":", "—", "-"))
            and not last_line.startswith(("*", "-", "**", "URL", "Источник", "Ссылк"))
            and "[" not in last_line):
        if not _is_placeholder(last_line):
            return _reject_url_like(last_line)

    return None


_PLACEHOLDERS = {"пример url", "url", "ссылка", "link", "источник",
                 "здесь", "here", "пример", "example", "source"}


def _is_placeholder(title):
    """True если это явный placeholder, а не настоящий заголовок."""
    t = title.strip().strip("«»\"'").lower()
    return t in _PLACEHOLDERS or len(t) < 5


def verify_urls(text, min_score=0.35):
    """Проверяет все URL: сверяет реальный title с заявленным."""
    issues, checked = [], []
    for url in set(extract_urls(text)):
        if _is_trusted(url):
            checked.append({"url": url, "status": "trusted"})
            continue
        real = _fetch_title(url)
        if real is None:
            checked.append({"url": url, "status": "unreachable"})
            continue
        if not real.strip():
            checked.append({"url": url, "status": "unverified",
                            "reason": "пустой <title>"})
            continue
        claimed = _find_claimed_title(text, url)
        if not claimed:
            checked.append({"url": url, "real_title": real,
                            "claimed": None, "status": "ok"})
            continue
        score = _similarity(claimed, real)
        # Снимаем ложные срабатывания: если claimed короче и содержится в real —
        # это не галлюцинация (например "AI NOVA" vs "AI Nova — AI-агенты...")
        ok = score >= min_score or (
            len(claimed) <= 30 and claimed.lower() in real.lower()
        )
        checked.append({
            "url": url, "real_title": real, "claimed": claimed,
            "score": round(score, 2),
            "status": "ok" if ok else "mismatch",
        })
        if not ok:
            issues.append({
                "kind": "url_title_mismatch",
                "url": url,
                "claimed": claimed[:150],
                "real": real[:150],
                "score": round(score, 2),
            })
    return checked, issues


# ---- s65: verify_sources — «по данным X» без URL ----
_SRC_TRIGGER = re.compile(
    r"(?:по\s+(?:данным|оценк[еи]|информации|исследованию|прогнозу|отч[её]ту|опросу|статистике)\s+"
    r"(?:(?:компании|агентства|института|центра)\s+)?"
    r"|согласно\s+(?:данным\s+|отч[её]ту\s+|исследованию\s+)?"
    r"|according\s+to\s+"
    r"|per\s+(?:report\s+by\s+|data\s+from\s+))"
    r'[*_«»"]{0,4}([А-ЯA-Z][^,\n;«»()*_"]{2,60})',
    re.IGNORECASE)
_SRC_GENERIC = re.compile(r"^(?:исследован|опрос|отч[её]т|компани|статистик|рынок|данн|report|study|market|data)", re.IGNORECASE)

def verify_numbers(text, search_chunks):
    """Числовые утверждения (%, часы, разы, деньги) → ищем в исходниках.

    Расширенный набор единиц (v4): проценты, время, разы, деньги, штуки.
    Если числа нет в search_chunks — это fabrication.
    """
    issues = []
    chunks = "\n".join(search_chunks or [])

    def norm(s):
        return re.sub(r'[^\d]', '', s)

    # Нормализованные источники: убираем ВСЁ кроме цифр.
    # Позволяет найти "50 000 ₽" в источнике как "50000".
    chunks_digits = norm(chunks)

    # Единицы, после которых число = факт (нельзя выдумывать)
    UNITS = (
        r"процент|%|просмотр|views?|человек|users?|"
        r"час|минут|день|дней|недел|месяц|"
        r"раз|раза|раз\b|"
        r"руб|₽|доллар|\$|usd|"
        r"клиент|заказ|заявк|товар|"
        r"тыс|млн|млрд|k\b|m\b"
    )
    pattern = (
        r'(\d[\d\s,\.]*[KkMmКк]?\+?)\s*'
        r'(' + UNITS + r')'
    )
    seen = set()
    for m in re.finditer(pattern, text, re.IGNORECASE):
        raw = m.group(1).strip()
        digits = norm(raw)
        if not digits or len(digits) < 1:
            continue
        # s72 P4: sklejka chisel cherez zapyatuyu -> proveryaem kazhdoe otdelno
        # Edge-guard: "100,000" (razryadnost) -> 2 chasti, vtoraya rovno 3 cifry
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        is_list = len(parts) > 1
        if is_list and len(parts) == 2 and re.fullmatch(r"\d{3}", parts[1]):
            is_list = False  # razryadnost, ne spisok
        if is_list:
            for part in parts:
                digits_p = norm(part)
                if not digits_p:
                    continue
                if len(digits_p) <= 1 and int(digits_p) < 10:
                    continue
                k = (part, m.group(2).lower())
                if k in seen:
                    continue
                seen.add(k)
                if part in chunks:
                    continue
                if digits_p in chunks_digits:
                    continue
                if part[-1] in "KkКк" and (digits_p + "000") in chunks_digits:
                    continue
                if part[-1] in "MmМм" and (digits_p + "000000") in chunks_digits:
                    continue
                stripped_p = digits_p.rstrip('0')
                if stripped_p and len(stripped_p) >= 2 and stripped_p in chunks_digits:
                    continue
                issues.append({
                    "kind": "number_not_in_sources",
                    "value": f"{part} {m.group(2)}",
                    "context": text[max(0, m.start() - 60):m.end() + 30]
                                  .replace("\n", " ")[:200],
                })
            continue
        key = (raw, m.group(2).lower())
        if key in seen:
            continue
        seen.add(key)

        # 1. Прямое совпадение (raw как есть) в sources
        if raw in chunks:
            continue
        # 1b. По цифрам без разделителей (универсально)
        if digits and digits in chunks_digits:
            continue
        # 2. Множители
        if raw[-1] in "KkКк" and ((digits + "000") in chunks_digits):
            continue
        if raw[-1] in "MmМм" and ((digits + "000000") in chunks_digits):
            continue
        # 3. Хвостовые нули
        stripped = digits.rstrip('0')
        if stripped and len(stripped) >= 2 and stripped in chunks_digits:
            continue
        # 4. Мелкие числа 1-9 игнорируем (общие утверждения типа "5 минут")
        if len(digits) <= 1 and int(digits) < 10:
            continue

        issues.append({
            "kind": "number_not_in_sources",
            "value": f"{raw} {m.group(2)}",
            "context": text[max(0, m.start() - 60):m.end() + 30]
                          .replace("\n", " ")[:200],
        })
    return issues


def verify_sources(text, search_chunks):
    """s65: «по данным X», «according to Y» без URL в ±200 симв.

    Ловит атрибуцию без верифицируемого URL рядом. Issues формат — как verify_numbers.
    """
    issues = []
    chunks_l = "\n".join(search_chunks or []).lower()
    seen = set()
    for m in _SRC_TRIGGER.finditer(text or ""):
        src_name = m.group(1).strip().rstrip(".,;:«»()")
        if not src_name or src_name in seen:
            continue
        low = src_name.lower()
        # E1: self-reference
        if low.startswith(("наш", "our")):
            continue
        # E2: generic без имени
        if _SRC_GENERIC.match(low):
            continue
        window = text[max(0, m.start() - 50): m.end() + 250]
        # E3: URL в окне
        if "http://" in window or "https://" in window:
            continue
        # E4: имя есть в источниках
        if low in chunks_l:
            continue
        # E5: trusted-домен в имени
        if any(d.lower() in low for d in _TRUSTED_DOMAINS):
            continue
        # E5b (s68): "API <Provider>" — tech-упоминание, не цитата
        if re.match(r"^api\s+[a-z]", low):
            continue
        seen.add(src_name)
        issues.append({
            "kind": "unnamed_source",
            "source": src_name,
            "context": window.replace("\n", " ")[:200],
        })
    return issues


_HEDGE_RE = re.compile(
    r"не работа(?:ет|л|ют)|не доступен|недоступен|"
    r"лагает|не могу (?:проверить|верифицировать)|"
    r"не удалось (?:проверить|верифицировать)|"
    r"не (?:проверял|проверяла|тестировал|тестировала)|"
    r"без (?:ключа|api|токена|vpn|подписк)|"
    r"требу[ею]т (?:ключ|api|токен|настройк|vpn|подписк)|"
    r"заблокирован|ограничен|не поддержива|"
    r"not work|unavailable|disabled|blocked|forbidden|"
    r"lags?\b|can(?:not|'t) (?:verify|check|test)|"
    r"unable to (?:verify|check|test)|"
    r"requires? (?:key|api|token|vpn|subscription)|"
    r"without (?:key|token|api|vpn)|"
    r"no api key|missing key|invalid key",
    re.IGNORECASE,
)


def verify_answer(answer_text, search_chunks=None, written_files=None,
                  check_urls=True, check_numbers=True,
                  provider_checks=None, system_marker_pat=None,
                  check_sources=True):
    """Главная точка входа. Возвращает dict с вердиктом."""
    issues = []
    urls = []
    hedged_skips = []
    # s62: scrub системных маркеров ([ПРОБЛЕМА: ...]) из answer_text
    if system_marker_pat and answer_text:
        answer_text = re.sub(system_marker_pat, "", answer_text)
    if check_urls and answer_text:
        urls, url_issues = verify_urls(answer_text)
        issues.extend(url_issues)

    if check_numbers and answer_text:
        issues.extend(verify_numbers(answer_text, search_chunks or []))

    if check_sources and answer_text:
        issues.extend(verify_sources(answer_text, search_chunks or []))

    # written_files — проверяем URL-мисматчи И числа (это то, что осядет в память)
    if written_files:
        for fp in written_files:
            try:
                body = open(fp, encoding="utf-8").read()
            except Exception:
                continue
            # s62: scrub системных маркеров и из содержимого файлов
            if system_marker_pat:
                body = re.sub(system_marker_pat, "", body)
            if check_urls:
                w_checked, w_issues = verify_urls(body)
                for it in w_issues:
                    it["file"] = fp
                issues.extend(w_issues)
                urls.extend(w_checked)
            if check_numbers:
                for it in verify_numbers(body, search_chunks or []):
                    it["file"] = fp
                    issues.append(it)
            if check_sources:
                for it in verify_sources(body, search_chunks or []):
                    it["file"] = fp
                    issues.append(it)

    # s61: unreachable URL → issue (с дедупом против provider_checks)
    if urls:
        _pc_urls = { (pc.get("url") or "").strip().lower()
                     for pc in (provider_checks or []) }
        for u in urls:
            if u.get("status") != "unreachable":
                continue
            _u = (u.get("url") or "").strip().lower()
            if _u and _u not in _pc_urls:
                issues.append({"kind": "url_unreachable",
                               "url": u.get("url")})

    # s61: cross-check с check_provider этого прогона
    if provider_checks and answer_text:
        t = answer_text.lower()
        for pc in provider_checks:
            if pc.get("ok"): continue
            n = (pc.get("name") or "").strip()
            u = (pc.get("url") or "").strip()
            needle = ""
            by = ""
            if n and n.lower() in t:
                needle = n.lower(); by = "name"
            elif u and u.lower() in t:
                needle = u.lower(); by = "url"
            if not needle:
                continue
            pos = t.find(needle)
            window = t[max(0, pos - 120): pos + len(needle) + 120]
            if _HEDGE_RE.search(window):
                hedged_skips.append({"provider": n or u, "by": by})
                continue
            issues.append({"kind":"self_contradiction","provider": n or u, "by": by})

    sc_count = sum(1 for i in issues if i.get("kind") == "self_contradiction")
    if not issues:
        verdict = "grounded"
    elif sc_count >= 2:
        verdict = "hallucinated"
    elif len(issues) <= 2:
        verdict = "partial"
    else:
        verdict = "hallucinated"

    return {
        "verdict": verdict,
        "count_issues": len(issues),
        "issues": issues,
        "urls_checked": urls,
        "hedged_skips": hedged_skips,
    }


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) < 2:
        print("usage: python3 verify.py <file.md> [<source.txt> ...]")
        sys.exit(1)
    body = open(sys.argv[1], encoding="utf-8").read()
    sources = []
    for p in sys.argv[2:]:
        try:
            sources.append(open(p, encoding="utf-8").read())
        except Exception:
            pass
    result = verify_answer(body, sources)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["verdict"] == "grounded" else 2)
