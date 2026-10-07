#!/bin/bash
# Daily Reddit karma-ramp reminder (14:00 MSK)
MSG="Reddit u/More-Character-6188 (karma ramp): 2-3 комментария в r/LocalLLaMA / r/algotrading / r/MachineLearning. Без ссылок, без self-promo. Цель karma >= 50."
osascript <<APPLESCRIPT
display notification "$MSG" with title "ai-hub: Reddit reminder" subtitle "14:00 MSK" sound name "Ping"
APPLESCRIPT
echo "$(date '+%Y-%m-%d %H:%M:%S') daily reminder fired" >> /tmp/ai-hub-logs/reddit-reminder.log
