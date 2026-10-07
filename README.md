# ai-hub

Self-improving autonomous agent on pure Python stdlib + local Ollama. Read-only. No API keys. No frameworks.

> **Disclaimer:** Educational / research project. Read-only. No trading. No financial advice. No private keys. Use at your own risk. See [docs/DISCLAIMER.md](docs/DISCLAIMER.md).

## What it does

- **Autonomous 24/7 loop** — self-daemon scans 7 DEX (Hyperliquid, dYdX, Paradex, Orca, Raydium, GMX, Injective) for cross-exchange arbitrage, writes stats, runs daily research.
- **Self-healing** — 27 healers, CORE sign 14/14, 0 drift, 0 regression, auto-extraction of lessons from failures.
- **Self-research** — pulls papers and articles, extracts trading rules, keeps rolling 30-day stats in `SELF_TRADING.md`.
- **Zero cloud** — local Ollama (qwen2.5-coder:3b + bge-m3). No LLM API keys in runtime. Network only to public DEX REST/LCD endpoints.

## Quickstart (2 min)

    git clone <repo> ~/Desktop/ai-hub && cd ~/Desktop/ai-hub
    python3 scripts/research/self_daemon.py &

Full setup (Ollama, pre-flight, first scan): [docs/QUICKSTART.md](docs/QUICKSTART.md).

## Status (s200, 2026-10-07)

| Metric | Value |
|---|---|
| CORE sign | 14 / 14 valid |
| Features / checks / alive | 163 / 167 / 163 |
| Healers | 27 |
| Drift / regression / unresolved | 0 / 0 / 0 |
| Lessons (total / indexed / embedded) | 9292 / 296 / 297 |
| Tests | 210 / 213 |
| Sources / DEX live | 7 / 7 |
| Self-axes (Autonomy / Self-service / Self-learning / Self-diagnostics) | 100 / 100 / 100 / 100 |

## Live output (pre-flight)

    $ python3 scripts/preflight.py
    [1] verify_core      : {'valid': True, 'checked': 14}
    [2] self_daemon PID  : 98586 (alive)
    [3] agent_daemon PID : 40626 (alive)
    [4] index / embed    : 296 / 297 (sync)
    [5] STATE            : s200 -> s201
    pre-flight: OK

## Philosophy

    Self-service -> Self-diagnostics -> Self-improvement -> Autonomy
                                  |
                                  v
                  Trading ONLY on DEX (read-only, phase 1)
                                  |
                                  v
                  (now) Open-source packaging -> community feedback

The agent must first serve and diagnose itself, learn autonomously, and only then think about products. Marketing comes last.

## Architecture

4 self-axes, daemon loop, healers, R1-R5 rules: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT — see [LICENSE](LICENSE). No warranty.
