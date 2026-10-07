#!/usr/bin/env bash
# safe_run.sh — s110 A8-актуатор.
# Оборачивает `pbpaste | bash`, ретраит при fork: Resource temporarily unavailable.
# Правило s109-0e: скрипт начинается с проверки $BASH_VERSION.
# Правило s109-0d: НЕТ exit в верхнем уровне.
#
# Использование:
#   pbpaste | safe_run.sh > /tmp/out.log 2>&1; tail -40 /tmp/out.log
#
# Каждое fork-событие пишется в self/healers/fork_watch.jsonl через fork_watch.py --record.

if [ -z "$BASH_VERSION" ]; then
  echo "safe_run.sh: требует bash (запусти через 'bash safe_run.sh')" >&2
else
  ROOT="${AI_HUB_ROOT:-$(pwd)}"
  JOURNAL="$ROOT/self/healers/fork_watch.jsonl"
  TMPBODY="$(mktemp -t safe_run_body.XXXXXX)"
  cat > "$TMPBODY"

  MAX_TRIES=3
  SLEEP_SECS=(20 40 60)
  ATTEMPT=0
  DONE=0

  while [ "$ATTEMPT" -lt "$MAX_TRIES" ] && [ "$DONE" -eq 0 ]; do
    ATTEMPT=$((ATTEMPT+1))
    echo "--- safe_run: попытка $ATTEMPT/$MAX_TRIES ---"
    ERRLOG="$(mktemp -t safe_run_err.XXXXXX)"
    bash "$TMPBODY" 2> "$ERRLOG"
    RC=$?
    if grep -q "fork: Resource temporarily unavailable" "$ERRLOG"; then
      echo "[safe_run] fork-ошибка обнаружена (attempt=$ATTEMPT)"
      # записать событие — вызываем fork_watch.py record (fail-open)
      if [ -f "$ROOT/fork_watch.py" ]; then
        python3 "$ROOT/fork_watch.py" --record --rc="$RC" --attempt="$ATTEMPT" 2>/dev/null || true
      fi
      if [ "$ATTEMPT" -lt "$MAX_TRIES" ]; then
        SL="${SLEEP_SECS[$((ATTEMPT-1))]}"
        echo "[safe_run] сплю ${SL}с и повторяю..."
        sleep "$SL"
      fi
    else
      cat "$ERRLOG" >&2
      DONE=1
    fi
    rm -f "$ERRLOG"
  done

  rm -f "$TMPBODY"
  if [ "$DONE" -eq 0 ]; then
    echo "[safe_run] ВСЕ $MAX_TRIES попытки исчерпаны — fork-storm"
    if [ -f "$ROOT/fork_watch.py" ]; then
      python3 "$ROOT/fork_watch.py" --record --rc=125 --attempt="$MAX_TRIES" --exhausted 2>/dev/null || true
    fi
  fi
fi
