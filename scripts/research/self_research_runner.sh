#!/bin/bash
cd "$HOME/Desktop/ai-hub"
LOG="self/curator/self_research.log"
echo "=== $(date '+%F %T') start ===" >> "$LOG"
/usr/bin/python3 scripts/research/self_research.py --run --limit 3 >> "$LOG" 2>&1
echo "=== $(date '+%F %T') done rc=$? ===" >> "$LOG"
