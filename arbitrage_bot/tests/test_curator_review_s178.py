import subprocess, unittest
from pathlib import Path

# tests живут в arbitrage_bot/tests/, project root на 2 уровня выше
ROOT = Path(__file__).resolve().parent.parent.parent
PROPS = ROOT / "self/curator/SELF_PROPOSALS.jsonl"

class TestCuratorReview(unittest.TestCase):
    def test_review_in_help(self):
        r = subprocess.run(["python3", "curator.py", "--help"],
                           capture_output=True, text=True, cwd=ROOT, timeout=30)
        self.assertIn("--review", r.stdout)

    def test_review_eof_safe(self):
        before = PROPS.read_text(encoding="utf-8")
        r = subprocess.run(["python3", "curator.py", "--classify", "--review"],
                           capture_output=True, text=True, cwd=ROOT,
                           stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-200:])
        after = PROPS.read_text(encoding="utf-8")
        self.assertEqual(before, after, "EOF review must not modify proposals")

    def test_review_filters_skip(self):
        """s179 P5: review must not print skip records."""
        r = subprocess.run(["python3", "curator.py", "--classify", "--review"],
                           capture_output=True, text=True, cwd=ROOT,
                           stdin=subprocess.DEVNULL, timeout=120)
        self.assertIn("--- review", r.stdout)
        after = r.stdout.split("--- review", 1)[1]
        self.assertNotIn("skip | not pending", after,
                         "review must filter skip records")

    def test_review_prints_header(self):
        r = subprocess.run(["python3", "curator.py", "--classify", "--review"],
                           capture_output=True, text=True, cwd=ROOT,
                           stdin=subprocess.DEVNULL, timeout=120)
        self.assertIn("review", r.stdout.lower())

if __name__ == "__main__":
    unittest.main()
