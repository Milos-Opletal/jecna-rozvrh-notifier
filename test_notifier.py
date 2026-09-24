import unittest
from jecna import JecnaClient

class TestJecnaNotifier(unittest.TestCase):
    def setUp(self):
        self.client = JecnaClient()

    def test_class_normalization(self):
        self.assertEqual(self.client._normalize_class_name("4.B"), "4B")
        self.assertEqual(self.client._normalize_class_name("C4b"), "C4b")

    def test_diff_detection(self):
        old_state = {
            "2026-09-25": {
                "changes": [
                    {"hour": 1, "text": "M 1 Hr(Zn)"}
                ],
                "takesPlace": ""
            }
        }
        new_state = {
            "2026-09-25": {
                "changes": [
                    {"hour": 1, "text": "M 1 Hr(Zn)"},
                    {"hour": 4, "text": "A 21 Ho(Lc) spoj."}
                ],
                "takesPlace": "Exkurze"
            }
        }

        diffs = self.client.diff_schedules(old_state, new_state)
        self.assertEqual(len(diffs), 2)

        lesson_diff = next(d for d in diffs if d["type"] == "new")
        self.assertEqual(lesson_diff["hour"], 4)
        self.assertEqual(lesson_diff["text"], "A 21 Ho(Lc) spoj.")

        tp_diff = next(d for d in diffs if d["type"] == "takesPlace")
        self.assertEqual(tp_diff["text"], "Exkurze")

    def test_diff_cancelled(self):
        old_state = {
            "2026-09-25": {
                "changes": [
                    {"hour": 1, "text": "TV odpadá"}
                ],
                "takesPlace": ""
            }
        }
        new_state = {
            "2026-09-25": {
                "changes": [],
                "takesPlace": ""
            }
        }

        diffs = self.client.diff_schedules(old_state, new_state)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["type"], "cancelled")

    def test_deduplication_fingerprint(self):
        from main import make_fingerprint
        item = {
            "date": "2026-09-25",
            "hour": 4,
            "type": "new",
            "text": "A 21 Ho(Lc) spoj."
        }
        fp = make_fingerprint(item)
        self.assertEqual(fp, "2026-09-25#4#new#A 21 Ho(Lc) spoj.")

if __name__ == "__main__":
    unittest.main()
