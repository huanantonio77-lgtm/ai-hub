import json, os, hashlib

state_file = 'strategy/_tasks/state.json'
os.makedirs('strategy/_tasks', exist_ok=True)

# state привязан к хэшу текста задачи. Новые тексты = новые ключи = все open.
m = json.load(open('memory.json', encoding='utf-8'))
tasks = m.get('next_actions', [])
print(f'Задач в очереди: {len(tasks)}')

# Старым ключам (если совпадут) — сбросим в open, но тексты другие — не совпадут.
if os.path.exists(state_file):
    st = json.load(open(state_file, encoding='utf-8'))
    print(f'Было state: {len(st)} записей — оставляю, ключи не пересекутся')
else:
    st = {}
    json.dump(st, open(state_file, 'w', encoding='utf-8'), indent=2)
    print('state.json создан (пустой)')

# Показать ключи задач (первые 8 символов хэша) — убедиться, что все новые
print()
print('=== Ключи новых задач ===')
for i, t in enumerate(tasks, 1):
    key = hashlib.md5(t.encode()).hexdigest()[:12]
    old = st.get(key, {})
    print(f'  {i}. {key}  status={old.get("status", "open")}  attempts={old.get("attempts", 0)}')
