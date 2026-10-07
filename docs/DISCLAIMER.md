# Disclaimer — ai-hub

**Last updated:** 2026-10-07 (s200).

## Educational / research use only

`ai-hub` is an educational and research project. It is a reference implementation of a self-improving autonomous agent. It is **not** a product, service, or tool intended for production use.

## No financial advice

Nothing in this repository, its code, output, documentation, or example data constitutes financial, investment, legal, or tax advice. The agent reads public market data (order books, oracle prices) and computes arithmetic differences between exchanges. These are technical measurements, not recommendations to buy, sell, or hold any asset.

## Read-only, no trading

In phase 1 the agent is strictly read-only:

- It does **not** place orders. `place_order` is a no-op.
- It does **not** hold private keys, seed phrases, exchange accounts, or API credentials.
- It does **not** connect to authenticated endpoints. Network calls go only to public REST/LCD endpoints of the listed DEX.
- It does **not** custody, transfer, or control any funds.

## No warranty

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. See [LICENSE](../LICENSE) for the full text. Use at your own risk.

## Market risk

Cryptocurrency markets are volatile and risky. Any code that interacts with them — even read-only scanners — can be misused. Do not deploy this agent as-is, in any form, against real funds. If you build on it, you are solely responsible for your own compliance, security, and risk management.

## Jurisdictional risk

Crypto regulations vary by jurisdiction. Running this software may be subject to local law. You are responsible for understanding and complying with applicable regulations in your jurisdiction.

## Privacy

This project does not collect, transmit, or store personal data. It runs entirely on the user's machine. The local Ollama LLM is used for research tasks; no prompts or outputs are sent to any third party.

## Contributing

By contributing, you agree that your contributions are licensed under the MIT license, and that you understand this project is educational.

## Contact

No official contact. See the repository's issue tracker for questions or bug reports.
