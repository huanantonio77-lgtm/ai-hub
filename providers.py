"""
providers.py — единый доступ к реестру ИИ-провайдеров.
Читает providers_registry.json. НЕ трогает orchestrator.py.
Используется: add_provider.py, health_check.py, будущими скриптами.
"""
import json
from pathlib import Path

AI_HUB = Path.home() / "Desktop" / "ai-hub"
REGISTRY_FILE = AI_HUB / "providers_registry.json"


def load() -> dict:
    if not REGISTRY_FILE.exists():
        return {"providers": {}}
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"providers.py: не смог прочитать реестр: {e}")
        return {"providers": {}}


def save(data: dict) -> None:
    REGISTRY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def all_providers() -> dict:
    return load().get("providers", {})


def get(provider: str) -> dict | None:
    return all_providers().get(provider)


def add_model(provider: str, model: str) -> tuple:
    """Добавляет модель в provider.models. Возвращает (ok, msg)."""
    data = load()
    provs = data.get("providers", {})
    if provider not in provs:
        return False, f"провайдер '{provider}' не найден в реестре"
    models = provs[provider].setdefault("models", [])
    if model in models:
        return False, f"модель '{model}' уже есть у {provider}"
    models.append(model)
    save(data)
    return True, f"добавлено: {provider}/{model}"


def remove_model(provider: str, model: str) -> tuple:
    """Удаляет модель. Возвращает (ok, msg)."""
    data = load()
    provs = data.get("providers", {})
    if provider not in provs:
        return False, f"провайдер '{provider}' не найден"
    models = provs[provider].get("models", [])
    if model not in models:
        return False, f"модели '{model}' нет у {provider}"
    models.remove(model)
    provs[provider]["models"] = models
    save(data)
    return True, f"удалено: {provider}/{model}"


def add_provider(name: str, api_type: str, api_url: str, key_file: str) -> tuple:
    """Добавляет нового провайдера-скелет. Возвращает (ok, msg)."""
    data = load()
    provs = data.setdefault("providers", {})
    if name in provs:
        return False, f"провайдер '{name}' уже есть"
    provs[name] = {
        "label": name,
        "api_type": api_type,
        "api_url": api_url,
        "key_file": key_file,
        "models": [],
        "limits_ref": name,
        "_added_by": "add_provider.py",
    }
    save(data)
    return True, f"добавлен провайдер: {name} (API type: {api_type})"


def remove_provider(name: str) -> tuple:
    data = load()
    provs = data.get("providers", {})
    if name not in provs:
        return False, f"провайдера '{name}' нет"
    del provs[name]
    save(data)
    return True, f"удалён провайдер: {name}"


def report() -> str:
    """Краткая сводка по реестру."""
    provs = all_providers()
    if not provs:
        return "Реестр пуст."
    lines = [f"=== Провайдеры в реестре: {len(provs)} ==="]
    for name, p in provs.items():
        n_models = len(p.get("models", []))
        lines.append(
            f"  {name:12} | {p.get('api_type','?'):18} | моделей: {n_models:2} | {p.get('label','')}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
