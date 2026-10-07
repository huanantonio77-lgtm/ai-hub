"""test_learning_rules_s179 — parser tests (P2.4)."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from scripts.learning_rules import load_rules


class TestLearningRules(unittest.TestCase):
    def test_load_rules_shape(self):
        r = load_rules()
        self.assertIsNotNone(r)
        keys = ("apply_techniques", "apply_fields", "reject_words",
                "defer_words", "defer_confidence")
        for k in keys:
            self.assertIn(k, r)
        self.assertEqual(r["defer_confidence"], 0.6)

    def test_reject_and_defer_clean(self):
        r = load_rules()
        self.assertNotIn("reject", r["reject_words"])
        self.assertNotIn("defer", r["defer_words"])
        self.assertNotIn("confidence", r["defer_words"])
        self.assertIn("provenance", r["reject_words"])
        self.assertIn("protocol", r["defer_words"])

    def test_hyphen_tokens_and_fallback(self):
        r = load_rules()
        self.assertIn("rate-limit", r["apply_techniques"])
        self.assertIn("provider-adapter", r["apply_techniques"])
        self.assertIsNone(load_rules("/nonexistent/x.md"))


if __name__ == "__main__":
    unittest.main()
