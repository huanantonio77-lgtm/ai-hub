#!/usr/bin/env python3
# s177: tests for scripts/autonomous_apply.py (heuristic classify + draft).
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOD = ROOT / "scripts" / "autonomous_apply.py"


def _load():
    spec = importlib.util.spec_from_file_location("aa_t", str(MOD))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class AutonomousApplyS177(unittest.TestCase):

    def test_classify_gateway_is_apply(self):
        m = _load()
        rec = {"status": "pending",
               "title": "Gateway-level Enforcement of Quotas",
               "technique": "gateway-based metering"}
        a, r = m.classify_one(rec)
        self.assertEqual(a, "apply")

    def test_classify_provenance_is_reject(self):
        m = _load()
        rec = {"status": "pending",
               "title": "Quantum Provenance Contract",
               "technique": "provenance architecture"}
        a, r = m.classify_one(rec)
        self.assertEqual(a, "reject")

    def test_classify_skips_non_pending(self):
        m = _load()
        rec = {"status": "applied", "title": "x", "technique": "y"}
        a, r = m.classify_one(rec)
        self.assertEqual(a, "skip")

    def test_classify_uses_only_title_and_technique(self):
        m = _load()
        # problem says quota, but title/technique say provenance
        rec = {"status": "pending",
               "title": "Provenance Contract",
               "technique": "provenance",
               "problem": "api quota tracking",
               "source_query": "quota"}
        a, r = m.classify_one(rec)
        self.assertEqual(a, "reject")

    def test_design_skeleton_returns_module_name(self):
        m = _load()
        rec = {"title": "T", "technique": "Gateway Billing"}
        p = m.design_skeleton(rec, 0)
        self.assertIn("module_name", p)
        # s201: SESSION_TAG is dynamic (read from STATE.md), not hardcoded.
        self.assertTrue(p["module_name"].endswith("_" + m.SESSION_TAG))


if __name__ == "__main__":
    unittest.main()
