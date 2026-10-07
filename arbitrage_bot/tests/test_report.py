"""Тесты report.py — CSV/JSON/summary по виртуальным сделкам.

5 уровней verify (s151-r4):
  V1 POSITIVE   — summary на 2 сделках (1 closed + 1 aborted)
  V2 CSV        — заголовок + N строк, колонки == CSV_COLUMNS
  V3 JSON       — round-trip, summary совпадает, trades count == N
  V4 EMPTY      — пустой список → count=0, CSV только заголовок
  V5 NEG-format — CSV: у всех строк одинаковое число колонок;
                  JSON валидный и trades — list of dict
"""

import csv
import io
import json
import unittest

from arbitrage_bot.app.execution.state_machine import VirtualTrade
from arbitrage_bot.app.monitoring.report import (
    CSV_COLUMNS,
    summary,
    to_csv,
    to_json,
    trade_to_dict,
    trades_to_dicts,
)


def _mk_closed() -> VirtualTrade:
    t = VirtualTrade("BTC/USDT", target_size=1.0)
    t.on_fill("buy", "A", 100.0, 0.4)
    t.on_fill("buy", "A", 100.1, 0.6)
    t.on_fill("sell", "B", 100.5, 0.7)
    t.on_fill("sell", "B", 100.6, 0.3)
    t.close()
    return t


def _mk_aborted() -> VirtualTrade:
    t = VirtualTrade("ETH/USDT", target_size=1.0)
    t.on_fill("buy", "A", 100.0, 0.5)
    t.abort("sell_leg_timeout")
    return t


class TestReportPositive(unittest.TestCase):
    """V1 POSITIVE — summary по 2 сделкам."""

    def test_summary(self):
        s = summary([_mk_closed(), _mk_aborted()])
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["closed"], 1)
        self.assertEqual(s["aborted"], 1)
        self.assertAlmostEqual(s["total_pnl_abs"], 0.47, places=8)
        self.assertAlmostEqual(s["avg_pnl_abs"], 0.235, places=8)


class TestReportCsv(unittest.TestCase):
    """V2 CSV — заголовок + N строк, колонки == CSV_COLUMNS."""

    def test_csv_shape(self):
        out = to_csv([_mk_closed(), _mk_aborted()])
        reader = csv.reader(io.StringIO(out))
        rows = list(reader)
        self.assertEqual(len(rows), 3)  # header + 2
        self.assertEqual(rows[0], CSV_COLUMNS)
        for r in rows[1:]:
            self.assertEqual(len(r), len(CSV_COLUMNS))


class TestReportJson(unittest.TestCase):
    """V3 JSON — round-trip, summary совпадает, trades count == N."""

    def test_json_roundtrip(self):
        d = json.loads(to_json([_mk_closed(), _mk_aborted()]))
        self.assertEqual(d["summary"]["count"], 2)
        self.assertEqual(len(d["trades"]), 2)
        self.assertAlmostEqual(d["summary"]["total_pnl_abs"], 0.47, places=8)


class TestReportEmpty(unittest.TestCase):
    """V4 EMPTY — пустой список: count=0, CSV = только заголовок."""

    def test_empty(self):
        s = summary([])
        self.assertEqual(s["count"], 0)
        self.assertEqual(s["total_pnl_abs"], 0.0)
        out = to_csv([])
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], CSV_COLUMNS)


class TestReportNegFormat(unittest.TestCase):
    """V5 NEG-format — все CSV-строки одинаковой ширины; JSON валиден."""

    def test_well_formed(self):
        trades = [_mk_closed(), _mk_aborted(), VirtualTrade("SOL/USDT", target_size=1.0)]
        out = to_csv(trades)
        rows = list(csv.reader(io.StringIO(out)))
        widths = {len(r) for r in rows}
        self.assertEqual(widths, {len(CSV_COLUMNS)})
        # JSON — валидный, trades — list[dict]
        d = json.loads(to_json(trades))
        self.assertIsInstance(d["trades"], list)
        self.assertTrue(all(isinstance(x, dict) for x in d["trades"]))
        self.assertEqual(len(d["trades"]), 3)
        # trade_to_dict для пустой сделки не падает
        empty = VirtualTrade("XRP/USDT", target_size=0.0 or 1.0)
        d0 = trade_to_dict(empty)
        self.assertEqual(d0["state"], "IDLE")
        self.assertIsNone(d0["vwap_buy"])


if __name__ == "__main__":
    unittest.main()
