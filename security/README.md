# security/ — least-privilege layer

Версия: 1.1a (2026-10-01).
Назначение: deny-by-default для tool-вызовов агента.

## Файлы
- `tool_manifest.json` — реестр tools: kind, denied_patterns, enforce.
- `enforcer.py` — `check(tool, action, args)` + `require(tool, action, args)`.
- `__init__.py` — версия пакета.

## Как работает
1. `require("read_text", "fs_read", {"path": "..."})`.
2. Enforcer читает manifest.
3. Для `fs_read`: resolve пути → должен быть внутри `ai-hub/`, не в denied_patterns.
4. Deny → `PermissionError`. Allow → тихий return.

## Fail-open
Если manifest недоступен — allow + запись в `strategy/_security_log.jsonl`.
Fail-open временный. В s1.1b+ перейдём на fail-closed.

## Как добавить новый tool
1. Запись в `tool_manifest.json` → `tools.<name>`.
2. Если kind новый — handler в `_KIND_HANDLERS` в enforcer.py.
3. Обёртка tool: `_sec.require("<name>", "<kind>", args)`.

## Тест
`python3 security/enforcer.py --test`
