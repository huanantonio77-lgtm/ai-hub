#!/bin/bash
# Daily Reddit karma-ramp reminder (14:00 MSK)
MSG="Reddit karma ramp: 2-3 комментария (r/LocalLLaMA / r/algotrading). Цель karma >= 50. Когда >= 50 — постить оба репо."
osascript <<APPLESCRIPT
display notification "$MSG" with title "ai-hub: Reddit reminder" subtitle "14:00 MSK" sound name "Ping"
APPLESCRIPT
echo "$(date '+%Y-%m-%d %H:%M:%S') daily reminder fired" >> /tmp/ai-hub-logs/reddit-reminder.log
