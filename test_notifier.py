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
        self.assertEqual(normalize_targets("morning_discord"), {"discord"})

    def test_webhook_morning_discord_routing(self):
        from unittest.mock import patch
        from webhooks import WebhookDispatcher

        dispatcher = WebhookDispatcher(
            ha_webhook_url="https://ha.example.com/webhook",
            discord_webhook_url="https://discord.example.com/default",
            morning_discord_webhook_url="https://discord.example.com/morning"
        )

        with patch.object(dispatcher, "_send_discord") as mock_discord, \
             patch.object(dispatcher, "_send_homeassistant") as mock_ha:
            
            changes = [{"hour": 1, "text": "M 1 Hr", "summary": "M 1 Hr"}]

            # Regular dispatch (is_morning=False) -> sends to default discord webhook
            dispatcher.dispatch_all(
                target_class="C4b",
                changes=changes,
                targets="haos,discord",
                is_morning=False
            )
            mock_discord.assert_called_once()
            self.assertEqual(mock_discord.call_args.kwargs.get("webhook_url"), "https://discord.example.com/default")
            mock_ha.assert_called_once()

            mock_discord.reset_mock()
            mock_ha.reset_mock()

            # Morning dispatch (is_morning=True) -> sends to separate morning discord webhook
            dispatcher.dispatch_all(
                target_class="C4b",
                changes=changes,
                targets="haos,discord",
                is_morning=True
            )
            mock_discord.assert_called_once()
            self.assertEqual(mock_discord.call_args.kwargs.get("webhook_url"), "https://discord.example.com/morning")
            mock_ha.assert_called_once()

    def test_webhook_morning_discord_fallback(self):
        from unittest.mock import patch
        from webhooks import WebhookDispatcher

        # No morning webhook configured -> should fall back to default discord webhook
        dispatcher = WebhookDispatcher(
            discord_webhook_url="https://discord.example.com/default",
            morning_discord_webhook_url=""
        )

        with patch.object(dispatcher, "_send_discord") as mock_discord:
            changes = [{"hour": 1, "text": "M 1 Hr", "summary": "M 1 Hr"}]
            dispatcher.dispatch_all(
                target_class="C4b",
                changes=changes,
                targets="discord",
                is_morning=True
            )
            mock_discord.assert_called_once()
            self.assertEqual(mock_discord.call_args.kwargs.get("webhook_url"), "https://discord.example.com/default")

    def test_webhook_only_morning_discord_configured(self):
        from unittest.mock import patch
        from webhooks import WebhookDispatcher

        # Only morning webhook configured
        dispatcher = WebhookDispatcher(
            discord_webhook_url="",
            morning_discord_webhook_url="https://discord.example.com/morning"
        )
        self.assertTrue(dispatcher.has_any_webhook())

        with patch.object(dispatcher, "_send_discord") as mock_discord:
            changes = [{"hour": 1, "text": "M 1 Hr", "summary": "M 1 Hr"}]
            # Regular dispatch does NOT send to Discord
            dispatcher.dispatch_all(
                target_class="C4b",
                changes=changes,
                targets="discord",
                is_morning=False
            )
            mock_discord.assert_not_called()

            # Morning dispatch sends to morning webhook
            dispatcher.dispatch_all(
                target_class="C4b",
                changes=changes,
                targets="discord",
                is_morning=True
            )
            mock_discord.assert_called_once()
            self.assertEqual(mock_discord.call_args.kwargs.get("webhook_url"), "https://discord.example.com/morning")

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

    def test_is_takes_place_relevant(self):
        # Target class C4b (grade 4, section b)
        self.assertFalse(self.client.is_takes_place_relevant("", "C4b"))
        self.assertFalse(self.client.is_takes_place_relevant("   ", "C4b"))
        # Unrelated classes or grades
        self.assertFalse(self.client.is_takes_place_relevant("Exkurze 1.A", "C4b"))
        self.assertFalse(self.client.is_takes_place_relevant("Exkurze C1a", "C4b"))
        self.assertFalse(self.client.is_takes_place_relevant("Sportovni den 2. rocnik", "C4b"))
        self.assertFalse(self.client.is_takes_place_relevant("Projekt A3", "C4b"))
        self.assertFalse(self.client.is_takes_place_relevant("Skolni kolo SOC v ucebne 12", "C4b"))
        # Target class mentioned directly or via alias
        self.assertTrue(self.client.is_takes_place_relevant("Exkurze C4b", "C4b"))
        self.assertTrue(self.client.is_takes_place_relevant("Exkurze 4.B do divadla", "C4b"))
        self.assertTrue(self.client.is_takes_place_relevant("Exkurze 4B", "C4b"))
        self.assertTrue(self.client.is_takes_place_relevant("Exkurze 1.A, 4.B, 2.C", "C4b"))
        # Target grade mentioned
        self.assertTrue(self.client.is_takes_place_relevant("Didakticke testy 4. rocniky", "C4b"))
        self.assertTrue(self.client.is_takes_place_relevant("Maturitni zkousky 4. rocnik", "C4b"))
        # Whole school cancellations
        self.assertTrue(self.client.is_takes_place_relevant("Reditelske volno", "C4b"))
        self.assertTrue(self.client.is_takes_place_relevant("Statni svatek", "C4b"))

    def test_extract_class_schedule_filters_irrelevant_takes_place(self):
        api_data = {
            "schedule": {
                "2026-10-08": {
                    "info": {"inWork": False},
                    "changes": {
                        "C1a": [{"text": "M 1 Hr"}],
                        "C4b": [None, None, {"text": "TP 21 Ms spoj."}]
                    },
                    "takesPlace": "Exkurze 1.A"
                },
                "2026-10-09": {
                    "info": {"inWork": False},
                    "changes": {
                        "C1a": [{"text": "CJ 2 Ku"}],
                        "C4b": []
                    },
                    "takesPlace": "Exkurze C4b"
                }
            }
        }
        res = self.client.extract_class_schedule(api_data, "C4b")
        # 2026-10-08 takesPlace was for 1.A, so it should be empty for C4b
        self.assertEqual(res["2026-10-08"]["takesPlace"], "")
        self.assertEqual(len(res["2026-10-08"]["changes"]), 1)
        self.assertEqual(res["2026-10-08"]["changes"][0]["hour"], 3)

        # 2026-10-09 takesPlace was for C4b, so it should be retained
        self.assertEqual(res["2026-10-09"]["takesPlace"], "Exkurze C4b")

    def test_diff_schedules_ignores_other_class_changes(self):
        old_state = {
            "2026-10-08": {
                "changes": [],
                "takesPlace": ""
            }
        }
        # In new state, an excursion for class 1.A appeared on the server, but nothing for C4b
        api_data = {
            "schedule": {
                "2026-10-08": {
                    "info": {"inWork": False},
                    "changes": {
                        "C1a": [{"text": "M 1 Hr"}],
                        "C4b": []
                    },
                    "takesPlace": "Exkurze 1.A"
                }
            }
        }
        new_state = self.client.extract_class_schedule(api_data, "C4b")
        diffs = self.client.diff_schedules(old_state, new_state)
        # Should be 0 diffs for C4b because neither lessons nor relevant takesPlace changed
        self.assertEqual(len(diffs), 0)

    def test_calculate_next_sync_delay(self):
        from datetime import datetime
        from jecna import calculate_next_sync_delay

        # Case 1: At 08:00:00 with 5 min interval, delay 15s -> next sync is at 08:00:15 (15 seconds)
        t1 = datetime(2026, 10, 15, 8, 0, 0)
        self.assertEqual(calculate_next_sync_delay(5, delay_seconds=15, now=t1), 15.0)

        # Case 2: At 08:00:10 (within delay window of 15s) -> 5 seconds remaining
        t2 = datetime(2026, 10, 15, 8, 0, 10)
        self.assertEqual(calculate_next_sync_delay(5, delay_seconds=15, now=t2), 5.0)

        # Case 3: At 08:00:20 (past delay window) -> next boundary is 08:05:00 + 15s = 08:05:15
        # Remaining: 280 seconds until 08:05 + 15 = 295 seconds
        t3 = datetime(2026, 10, 15, 8, 0, 20)
        self.assertEqual(calculate_next_sync_delay(5, delay_seconds=15, now=t3), 295.0)

        # Case 4: None or invalid schedule -> fallback to 15 min interval
        t4 = datetime(2026, 10, 15, 8, 0, 0)
        self.assertEqual(calculate_next_sync_delay(None, delay_seconds=15, now=t4), 15.0)
        self.assertEqual(calculate_next_sync_delay(0, delay_seconds=15, now=t4), 15.0)

    def test_check_and_send_morning_notification_weekends(self):
        from datetime import datetime
        from unittest.mock import MagicMock
        from main import check_and_send_morning_notification

        mock_dispatcher = MagicMock()
        # Saturday: 2026-10-17 07:00
        sat = datetime(2026, 10, 17, 7, 0)
        schedule = {
            "2026-10-17": {
                "changes": [{"hour": 1, "text": "M 1 Hr"}],
                "takesPlace": ""
            }
        }
        res = check_and_send_morning_notification(
            current_schedule=schedule,
            last_morning_date=None,
            webhook_dispatcher=mock_dispatcher,
            class_name="C4b",
            now=sat
        )
        mock_dispatcher.dispatch_all.assert_not_called()
        self.assertEqual(res, "2026-10-17")

    def test_check_and_send_morning_notification_no_entries_today(self):
        from datetime import datetime
        from unittest.mock import MagicMock
        from main import check_and_send_morning_notification

        mock_dispatcher = MagicMock()
        # Wednesday: 2026-10-14 07:00, changes for tomorrow only
        wed = datetime(2026, 10, 14, 7, 0)
        schedule = {
            "2026-10-15": {
                "changes": [{"hour": 1, "text": "M 1 Hr"}],
                "takesPlace": ""
            }
        }
        res = check_and_send_morning_notification(
            current_schedule=schedule,
            last_morning_date=None,
            webhook_dispatcher=mock_dispatcher,
            class_name="C4b",
            now=wed
        )
        mock_dispatcher.dispatch_all.assert_not_called()
        self.assertEqual(res, "2026-10-14")

    def test_check_and_send_morning_notification_sends_when_changes_exist(self):
        from datetime import datetime
        from unittest.mock import MagicMock
        from main import check_and_send_morning_notification

        mock_dispatcher = MagicMock()
        wed = datetime(2026, 10, 14, 7, 30)
        schedule = {
            "2026-10-14": {
                "changes": [{"hour": 2, "text": "CJ 2 Ku"}],
                "takesPlace": ""
            }
        }
        res = check_and_send_morning_notification(
            current_schedule=schedule,
            last_morning_date=None,
            webhook_dispatcher=mock_dispatcher,
            class_name="C4b",
            now=wed
        )
        mock_dispatcher.dispatch_all.assert_called_once()
        call_kwargs = mock_dispatcher.dispatch_all.call_args.kwargs
        self.assertTrue(call_kwargs.get("is_morning"))
        self.assertEqual(res, "2026-10-14")

    def test_check_and_send_morning_notification_outside_hours(self):
        from datetime import datetime
        from unittest.mock import MagicMock
        from main import check_and_send_morning_notification

        mock_dispatcher = MagicMock()
        schedule = {
            "2026-10-14": {
                "changes": [{"hour": 2, "text": "CJ 2 Ku"}],
                "takesPlace": ""
            }
        }
        # Too early: 04:30
        early = datetime(2026, 10, 14, 4, 30)
        res_early = check_and_send_morning_notification(
            current_schedule=schedule,
            last_morning_date=None,
            webhook_dispatcher=mock_dispatcher,
            class_name="C4b",
            now=early
        )
        mock_dispatcher.dispatch_all.assert_not_called()
        self.assertIsNone(res_early)

        # After noon: 13:00
        late = datetime(2026, 10, 14, 13, 0)
        res_late = check_and_send_morning_notification(
            current_schedule=schedule,
            last_morning_date=None,
            webhook_dispatcher=mock_dispatcher,
            class_name="C4b",
            now=late
        )
        mock_dispatcher.dispatch_all.assert_not_called()
        self.assertEqual(res_late, "2026-10-14")

if __name__ == "__main__":
    unittest.main()
