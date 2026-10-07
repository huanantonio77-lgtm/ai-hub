"""s172-T: verify --balance flag in arbitrage_bot.sim (trading step).

Закрывает s154-r0: явный $1000 paper-run через CLI.
R1-R5: без сети, subprocess с timeout, детерминированный stdout.
"""
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class TestSimBalance(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "arbitrage_bot.sim", *args],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_v1_stage8_default_balance(self):
        # default --balance = 100000.0 -> result: initial=100000.00
        r = self._run("--stage8-demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("initial=100000.00", r.stdout)

    def test_v2_stage8_balance_override(self):
        # s154-r0: явный $1000 через CLI (LiveSession paper-run).
        r = self._run("--stage8-demo", "--balance", "1000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("initial=1000.00", r.stdout)

    def test_v3_scan_demo_accepts_balance_flag(self):
        # --scan-demo принимает --balance (без initial= в stdout, exit 0).
        r = self._run("--scan-demo", "--balance", "1000")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
