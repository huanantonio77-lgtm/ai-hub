"""reflect.py — рефлексия агента.
ПОСТФИЛЬТР: проверяем, что каждое новое утверждение есть в свежих данных.
Если LLM выдумал компанию/инструмент — отбрасываем.
"""
import sys, json, re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from llm_call import llm
from memory import mem

STRATEGY = ROOT / "strategy"
PRODUCTS = STRATEGY / "products"

SYSTEM = """Ты — рефлексия ИИ-агента AI NOVA (ainova.ooo).

Тебе дают ТЕКУЩУЮ ПАМЯТЬ и СВЕЖИЕ ДАННЫЕ.

Возвращаешь СТРОГО JSON:
{
  "new_learnings": [{"insight": "...", "importance": "high|medium|low", "confidence": "high|medium|low"}],
  "updated_competitor_groups": [],
  "new_open_questions": ["..."],
  "resolved_questions": [],
  "uncertainties": ["что НЕ проверено / в чём сомнения"],
  "contradictions": ["какой источник противоречит другому / моему выводу"],
  "positioning_update": null,
  "next_actions": ["конкретное проверяемое действие"]
}

ПРАВИЛА:
- Используй ТОЛЬКО факты из блока СВЕЖИЕ ДАННЫЕ.
- НЕ добавляй новые имена компаний/сервисов, которых нет в свежих данных.
- Поле uncertainties ОБЯЗАТЕЛЬНО. Если сомнений нет — впиши ["нет существенных пробелов"].
- Поле contradictions ОБЯЗАТЕЛЬНО. Если противоречий нет — впиши ["противоречий не найдено"].
- confidence: high — подтверждено 2+ источниками; medium — 1 источник; low — догадка.
- next_actions: 1-5 КОНКРЕТНЫХ проверяемых действий. Не пиши "продолжать мониторить".
- Если нечего добавить — пустые массивы (кроме uncertainties и contradictions).
"""



REQUIRED_FIELDS = ("new_learnings", "new_open_questions", "next_actions",
                   "uncertainties", "contradictions")


def _parse_json(resp):
    """Парсит JSON из ответа LLM. None при неудаче."""
    if not resp:
        return None
    try:
        return json.loads(resp)
    except Exception:
        m = re.search(r'\{.*\}', resp, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None


def _missing_fields(parsed):
    return [f for f in REQUIRED_FIELDS if f not in parsed]


def gather_context():
    """Только СВОДКИ, не полные файлы — чтобы влезть в контекст 120b (~8K токенов)."""
    chunks = []

    # competitors-report: берём только раздел 9 (вывод для ainova)
    rep = PRODUCTS / "competitors/competitors-report.md"
    if rep.exists():
        txt = rep.read_text(encoding="utf-8")
        idx = txt.find("## 9. ВЫВОД ДЛЯ ainova")
        if idx > 0:
            chunks.append("=== competitors-report (вывод) ===\n" + txt[idx:idx+3500])
        else:
            chunks.append("=== competitors-report ===\n" + txt[-3000:])

    # модули: только статусы и краткая сводка
    mod = PRODUCTS / "ainova-modules.md"
    if mod.exists():
        txt = mod.read_text(encoding="utf-8")
        idx = txt.find("## СВОДКА ПО СТАТУСАМ")
        if idx > 0:
            chunks.append("=== ainova-modules (сводка) ===\n" + txt[idx:idx+1500])

    # сегменты: только таблица приоритетов
    seg = PRODUCTS / "ainova-segments.md"
    if seg.exists():
        txt = seg.read_text(encoding="utf-8")
        idx = txt.find("## ПРИОРИТЕТ ДЛЯ ainova")
        if idx > 0:
            chunks.append("=== ainova-segments (приоритет) ===\n" + txt[idx:idx+1200])

    # каналы: только очередь захода
    ch = PRODUCTS / "ainova-free-channels-FINAL.md"
    if ch.exists():
        txt = ch.read_text(encoding="utf-8")
        idx = txt.find("## ОЧЕРЕДЬ ЗАХОДА")
        if idx > 0:
            chunks.append("=== ainova-free-channels (очередь) ===\n" + txt[idx:idx+1000])

    return "\n\n".join(chunks)


def extract_proper_nouns(text):
    """Грубо вытаскиваем все слова с заглавной буквы длиной 3+ (латиница/кириллица)."""
    words = re.findall(r"\b[A-ZА-Я][a-zA-Zа-яА-Я0-9\-\.]{2,}\b", text)
    return {w.lower() for w in words}


def is_grounded(insight, fresh_text):
    """True если в инсайте все Proper Noun есть в fresh_text.
    Если хоть одно имя собственное не найдено — False (галлюцинация)."""
    insight_nouns = extract_proper_nouns(insight)
    if not insight_nouns:
        return True  # нет имён — оставляем (общие утверждения)
    fresh_nouns = extract_proper_nouns(fresh_text)
    # Игнорируем совсем общие слова
    STOPWORDS = {
        "россия", "россий", "российский", "russia", "russian",
        "малый", "средний", "крупный", "бизнес", "компания",
        "рынок", "сегмент", "канал", "площадка", "статья", "vc",
        "habr", "reddit", "telegram", "google", "yandex", "яндекс",
        "ниша", "цена", "стоимость", "клиент", "аудитория",
    }
    suspicious = insight_nouns - fresh_nouns - STOPWORDS
    # Разрешаем 1-2 случайных совпадения — оставляем только если подозрительных <= 1
    return len(suspicious) <= 1


def reflect():
    print("1. Грузим память...")
    current = json.dumps(mem.data, ensure_ascii=False, indent=2)[:5000]
    print(f"   памяти: {len(current)} символов")

    print("2. Собираем свежие данные...")
    fresh = gather_context()
    print(f"   данных: {len(fresh)} символов")

    print("3. Отправляем в LLM...")
    user = (
        "=== ТЕКУЩАЯ ПАМЯТЬ ===\n" + current + "\n\n"
        "=== СВЕЖИЕ ДАННЫЕ ===\n" + fresh + "\n\n"
        "Верни JSON по формату. Только факты из свежих данных."
    )
    resp = llm(SYSTEM, user, want_json=True)
    parsed = _parse_json(resp)
    if parsed is None:
        print("   LLM не ответил или не-JSON.")
        return None

    missing = _missing_fields(parsed)
    if missing:
        print(f"   Не хватает полей: {missing}. Повторный запрос...")
        retry_user = (
            user + "\n\n=== ПОВТОР ===\n"
            "Прошлый ответ был неполным. Обязательно верни ВСЕ поля: "
            + ", ".join(REQUIRED_FIELDS) + ".\n"
            "Особое внимание: uncertainties, contradictions."
        )
        resp2 = llm(SYSTEM, retry_user, want_json=True)
        parsed2 = _parse_json(resp2)
        if parsed2:
            for f in missing:
                if f in parsed2:
                    parsed[f] = parsed2[f]
            still = _missing_fields(parsed)
            if still:
                print(f"   Всё равно не хватает: {still}. Продолжаю с тем, что есть.")
        else:
            print("   Повтор не удался, продолжаю с неполным ответом.")

    print("4. Постфильтр (антигаллюцинации)...")

    added_learnings = 0
    rejected_learnings = 0
    existing_insights = [x.get("insight", "") for x in mem.get("learnings", [])]
    for l in parsed.get("new_learnings", []) or []:
        ins = (l.get("insight") or "").strip()
        if not ins:
            continue
        if any(ins.lower() in e.lower() or e.lower() in ins.lower() for e in existing_insights):
            continue
        if not is_grounded(ins, fresh):
            rejected_learnings += 1
            print(f"   [ОТКЛОНЕНО] {ins[:90]}...")
            continue
        mem.append("learnings", {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "session": mem.get("session", 16),
            "insight": ins,
            "importance": l.get("importance", "medium"),
        })
        added_learnings += 1

    added_q = 0
    rejected_q = 0
    for q in parsed.get("new_open_questions", []) or []:
        q = (q or "").strip()
        if not q:
            continue
        if q in mem.get("open_questions", []):
            continue
        if not is_grounded(q, fresh):
            rejected_q += 1
            print(f"   [ОТКЛОНЁН ВОПРОС] {q[:90]}...")
            continue
        mem.append("open_questions", q)
        added_q += 1

    resolved = parsed.get("resolved_questions", []) or []
    if resolved:
        old = mem.get("open_questions", [])
        new = [q for q in old if not any(r.lower() in q.lower() for r in resolved)]
        mem.update("open_questions", new)

    # Позиционирование НЕ обновляем автоматически — это стратегическое решение.
    # Если LLM предложит — сохраняем в отдельное поле, не трогая слоган.
    pos = parsed.get("positioning_update")
    if pos and isinstance(pos, str) and len(pos) < 300:
        mem.update("positioning.slogan_proposal", pos)

    # Группы конкурентов — тоже постфильтр
    added_groups = 0
    rejected_groups = 0
    groups = parsed.get("updated_competitor_groups", []) or []
    if groups:
        existing = mem.get("market.competitor_groups", [])
        existing_names = {g.get("group") for g in existing}
        for g in groups:
            name = g.get("group", "")
            if name in existing_names:
                continue
            # Проверка: имена конкурентов в группе должны быть в свежих данных
            names = g.get("names", []) or []
            if names and not any(n.lower() in fresh.lower() for n in names):
                rejected_groups += 1
                print(f"   [ОТКЛОНЕНА ГРУППА] {name}")
                continue
            existing.append(g)
            added_groups += 1
        mem.update("market.competitor_groups", existing)

    next_actions = parsed.get("next_actions", []) or []
    if next_actions:
        mem.update("next_actions", next_actions)

    uncertainties = parsed.get("uncertainties") or []
    contradictions = parsed.get("contradictions") or []
    if uncertainties or contradictions:
        mem.update("uncertainties_latest", {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "session": mem.get("session", 16),
            "uncertainties": uncertainties[:10],
            "contradictions": contradictions[:10],
        })

    audit_dir = STRATEGY / "reflections"
    try:
        audit_dir.mkdir(exist_ok=True)
        audit_file = audit_dir / ("reflect_" + datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".json")
        audit_file.write_text(json.dumps({
            "date": datetime.now().isoformat(),
            "learnings_added": added_learnings,
            "learnings_rejected": rejected_learnings,
            "questions_added": added_q,
            "uncertainties": uncertainties,
            "contradictions": contradictions,
            "next_actions": next_actions,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"   audit: {audit_file.name}")
    except Exception as e:
        print(f"   audit fail: {e}")

    mem.update("session", mem.get("session", 16) + 1)

    print(f"   уроков: +{added_learnings} (отклонено {rejected_learnings})")
    print(f"   вопросов: +{added_q} (отклонено {rejected_q})")
    print(f"   competitor-групп: +{added_groups} (отклонено {rejected_groups})")
    print(f"   next_actions: {len(next_actions)}")
    print(f"   uncertainties: {len(uncertainties)}")
    print(f"   contradictions: {len(contradictions)}")
    return parsed


if __name__ == "__main__":
    reflect()
    print()
    print(mem.summary())
