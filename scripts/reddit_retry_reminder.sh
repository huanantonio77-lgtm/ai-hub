#!/bin/bash
# One-shot: Reddit profile unlock reminder (24h after s202)
MSG="Reddit 24h unlock: настрой профиль (Display name, Avatar, Bio, 5 подписок) + 2-3 комментария. Цель karma >= 50."
osascript <<APPLESCRIPT
display notification "$MSG" with title "ai-hub: Reddit 24h retry" subtitle "Профиль разблокирован" sound name "Hero"
APPLESCRIPT
echo "$(date '+%Y-%m-%d %H:%M:%S') one-shot retry fired" >> /tmp/ai-hub-logs/reddit-reminder.log
sleep 5
launchctl bootout gui/$(id -u)/com.ai-hub.reddit-retry 2>/dev/null || true
