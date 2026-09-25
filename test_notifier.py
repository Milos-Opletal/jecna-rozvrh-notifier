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

    def test_czech_date_formatting(self):
        from datetime import datetime, timedelta
        from jecna import format_czech_date
        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")
        tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")

        today_fmt = format_czech_date(today_str)
        tomorrow_fmt = format_czech_date(tomorrow_str)

        self.assertTrue(today_fmt.startswith("Dnes ("))
        self.assertTrue(tomorrow_fmt.startswith("Zítra ("))

    def test_normalize_targets(self):
        from webhooks import normalize_targets
        self.assertEqual(normalize_targets("haos"), {"ha"})
        self.assertEqual(normalize_targets("haos,discord"), {"ha", "discord"})
        self.assertEqual(normalize_targets("all"), {"all"})
        self.assertEqual(normalize_targets(""), {"all"})
        self.assertEqual(normalize_targets(None), {"all"})
        self.assertEqual(normalize_targets("ntfy,telegram"), {"ntfy", "telegram"})

    def test_get_all_active_changes(self):
        from datetime import datetime, timedelta
        today_str = datetime.now().strftime("%Y-%m-%d")
        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        schedule = {
            today_str: {
                "changes": [{"hour": 1, "text": "TP odpadá"}],
                "takesPlace": ""
            },
            tomorrow_str: {
                "changes": [{"hour": 4, "text": "TV He(Lc)+"}],
                "takesPlace": "Exkurze"
            }
        }
        active = self.client.get_all_active_changes(schedule)
        self.assertEqual(len(active), 3)
        self.assertEqual(active[0]["hour"], 1)
        self.assertEqual(active[0]["text"], "TP odpadá")
        self.assertEqual(active[1]["hour"], 4)
        self.assertEqual(active[2]["type"], "takesPlace")

if __name__ == "__main__":
    unittest.main()
