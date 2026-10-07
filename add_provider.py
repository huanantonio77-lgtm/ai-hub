#!/usr/bin/env python3
"""
add_provider.py — CLI для управления реестром ИИ-провайдеров.

Команды:
  list                                  — показать всех провайдеров и модели
  show <provider>                       — подробности одного провайдера
  add-model <provider> <model>          — добавить модель
  remove-model <provider> <model>       — удалить модель
  add-provider <name> --type <type> --url <url>
                                        — добавить нового провайдера
  remove-provider <name>                — удалить провайдера

Типы API: openai_compatible | cohere | cloudflare | gemini
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import providers as P


def cmd_list(args) -> int:
    print(P.report())
    return 0


def cmd_show(args) -> int:
    p = P.get(args.provider)
    if not p:
        print(f"Провайдер '{args.provider}' не найден")
        return 1
    import json
    print(json.dumps(p, ensure_ascii=False, indent=2))
    return 0


def cmd_add_model(args) -> int:
    ok, msg = P.add_model(args.provider, args.model)
    print(msg)
    return 0 if ok else 1


def cmd_remove_model(args) -> int:
    ok, msg = P.remove_model(args.provider, args.model)
    print(msg)
    return 0 if ok else 1


def cmd_add_provider(args) -> int:
    key_file = args.key_file or f".secrets/providers/{args.name}.txt"
    ok, msg = P.add_provider(args.name, args.type, args.url or "", key_file)
    print(msg)
    if ok:
        print()
        print("Что делать дальше:")
        print(f"  1. Положи ключ в файл: {key_file}")
        print(f"  2. Добавь лимиты в provider_limits.json под именем '{args.name}'")
        print(f"  3. Добавь модели: python3 add_provider.py add-model {args.name} <model>")
        print(f"  4. Скажи ассистенту — он встроит провайдера в orchestrator")
    return 0 if ok else 1


def cmd_remove_provider(args) -> int:
    ok, msg = P.remove_provider(args.name)
    print(msg)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Управление реестром провайдеров ai-hub.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    sp = sub.add_parser("show")
    sp.add_argument("provider")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("add-model")
    sp.add_argument("provider")
    sp.add_argument("model")
    sp.set_defaults(func=cmd_add_model)

    sp = sub.add_parser("remove-model")
    sp.add_argument("provider")
    sp.add_argument("model")
    sp.set_defaults(func=cmd_remove_model)

    sp = sub.add_parser("add-provider")
    sp.add_argument("name")
    sp.add_argument("--type", required=True,
                    choices=["openai_compatible", "cohere", "cloudflare", "gemini"])
    sp.add_argument("--url", default="")
    sp.add_argument("--key-file", dest="key_file", default="")
    sp.set_defaults(func=cmd_add_provider)

    sp = sub.add_parser("remove-provider")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_remove_provider)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
