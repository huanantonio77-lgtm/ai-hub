# Quickstart — ai-hub

Get from zero to first autonomous scan in ~10 minutes. No pip install required — pure Python stdlib + local Ollama.

## Prerequisites

- macOS or Linux (tested on macOS 13+)
- Python 3.10+ (stdlib only, no pip deps)
- Ollama installed and running locally

Install Ollama:

    curl -fsSL https://ollama.com/install.sh | sh

Pull the two required models:

    ollama pull qwen2.5-coder:3b
    ollama pull bge-m3

Verify Ollama:

    ollama list

## Clone

    git clone <repo> ~/Desktop/ai-hub
    cd ~/Desktop/ai-hub

## Pre-flight (5 checks)

Run the 5-check pre-flight to make sure CORE is healthy:

    python3 -c "from security.signing import verify_core; print(verify_core())"
    pgrep -fl self_daemon.py
    pgrep -fl agent_daemon.py
    python3 -c "import json; d=json.load(open('knowledge/lessons_index.json')); print('index:', len(d) if isinstance(d,list) else len(d.get('entries',d)))"
    cat self/curator/STATE.md

Expected: `valid: True (14/14)`, both PIDs alive, index count matches, STATE shows last session.

## First scan

Run the DEX arbitrage scanner once (read-only, no orders placed):

    python3 scripts/arbitrage_scan.py --apply --write-stats

Check the report:

    cat self/curator/ARBITRAGE_REPORT.md
    cat self/curator/SELF_TRADING.md

## Start the daemon (24/7 autonomous)

    nohup python3 scripts/research/self_daemon.py > /tmp/self_daemon.log 2>&1 &

## Healthcheck (all 7 DEX)

    python3 scripts/exchange_healthcheck.py

Expected: 7 lines like `### hyperliquid (ok)`, `### injective (ok)`, each with a `latency` value. Total ~15 s.

## Verify daemon is running

    pgrep -fl self_daemon.py
    tail -20 /tmp/self_daemon.log

The daemon scans every ~2 h, runs trading research once per day, and rolls 30-day stats once per day. Markers live in `self/curator/.trading_research_last` and `self/curator/.stats_last`.

## Troubleshooting

- `verify_core` invalid → check `security/` files were not modified by hand.
- DEX returns 403 → some DEX need a User-Agent header; the clients set it, do not strip.
- No orders ever placed → expected. `place_order` is a no-op in phase 1 (read-only).
- Ollama timeouts → check `ollama list` shows both models; large lessons rebuild can take 9-15 min, that is normal.

## Next steps

- Read [ARCHITECTURE.md](ARCHITECTURE.md) for the 4 self-axes and R1-R5 rules.
- Read [DISCLAIMER.md](DISCLAIMER.md) — this project is educational.
- See [PRODUCT.md](PRODUCT.md) for the roadmap and community direction.
