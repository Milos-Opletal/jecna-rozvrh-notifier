#!/usr/bin/env python3
import os
import sys
import time
import json
import logging
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from datetime import datetime
from jecna import JecnaClient, calculate_next_sync_delay
from webhooks import WebhookDispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("JecnaNotifier")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
SYNC_DELAY_SECONDS = int(os.getenv("SYNC_DELAY_SECONDS", "15"))
CLASS_NAME = os.getenv("CLASS_NAME", "C4b").strip() or "C4b"
SUBSTITUTION_API_URL = os.getenv("SUBSTITUTION_API_URL", "https://jecnarozvrh.jzitnik.dev/versioned/v3").strip()
STATE_FILE = os.getenv("STATE_FILE_PATH", "/data/state.json")
ALERT_ON_STARTUP = os.getenv("ALERT_ON_STARTUP", "false").lower() in ("true", "1", "yes")

# Behavior options
REPEAT_ALL_CHANGES = os.getenv("REPEAT_ALL_CHANGES", "true").lower() in ("true", "1", "yes")

# Morning notification options
MORNING_NOTIFICATION_ENABLED = os.getenv("MORNING_NOTIFICATION_ENABLED", "true").lower() in ("true", "1", "yes")
MORNING_NOTIFICATION_TARGETS = os.getenv("MORNING_NOTIFICATION_TARGETS", "all").strip() or "all"

def make_fingerprint(item: dict) -> str:
    """Generate a unique fingerprint for a change to prevent duplicate notifications."""
    date = item.get("date", "")
    hour = item.get("hour", 0)
    change_type = item.get("type", "new")
    text = item.get("text", "")
    return f"{date}#{hour}#{change_type}#{text}"

def load_state() -> tuple[dict | None, set[str], str | None]:
    """
    Loads saved schedule state, previously notified history fingerprints,
    and the date of the last sent morning notification.
    """
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if "version" in data and "schedule" in data:
                    return (
                        data.get("schedule", {}),
                        set(data.get("notified_history", [])),
                        data.get("last_morning_notification_date")
                    )
                else:
                    # Legacy v1 format migration (dict of date -> day_info)
                    history = set()
                    for d, day_info in data.items():
                        for ch in day_info.get("changes", []):
                            history.add(f"{d}#{ch.get('hour', 0)}#new#{ch.get('text', '')}")
                        if day_info.get("takesPlace"):
                            history.add(f"{d}#0#takesPlace#{day_info.get('takesPlace')}")
                    return data, history, None
        except Exception as e:
            logger.error("Failed to read state file '%s': %s", STATE_FILE, e)
    return None, set(), None

def save_state(schedule: dict, notified_history: set[str], last_morning_date: str | None = None):
    """Saves schedule, history, and last morning notification date."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        today = datetime.now().date()
        pruned_history = []
        for fp in notified_history:
            parts = fp.split("#")
            if parts and len(parts) >= 1:
                try:
                    d = datetime.strptime(parts[0], "%Y-%m-%d").date()
                    if (today - d).days > 14:
                        continue
                except Exception:
                    pass
            pruned_history.append(fp)

        data = {
            "version": 2,
            "last_updated": datetime.now().isoformat(),
            "last_morning_notification_date": last_morning_date,
            "schedule": schedule,
            "notified_history": sorted(pruned_history)
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Failed to save state to '%s': %s", STATE_FILE, e)

def check_and_send_morning_notification(
    current_schedule: dict,
    last_morning_date: str | None,
    webhook_dispatcher: WebhookDispatcher,
    class_name: str,
    now: datetime | None = None
) -> str | None:
    if not MORNING_NOTIFICATION_ENABLED:
        return last_morning_date

    if now is None:
        now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # Already sent today
    if last_morning_date == today_str:
        return last_morning_date

    # Do not send morning notifications on weekends (Saturday / Sunday)
    if now.weekday() >= 5:
        return today_str

    # Morning window: 05:00 to 11:59 local time
    if now.hour < 5:
        return last_morning_date
    if now.hour >= 12:
        return today_str

    # Filter for today's entries only
    today_data = current_schedule.get(today_str, {})
    today_changes = today_data.get("changes", [])
    today_takes_place = today_data.get("takesPlace", "").strip()
    has_entries = bool(today_changes or today_takes_place)

    # Do not send notification in the morning if nothing will happen today
    if not has_entries:
        logger.info("Morning check (%s): Nothing happening today for class %s. Skipping morning notification.", today_str, class_name)
        return today_str

    from jecna import format_czech_date
    formatted_today = format_czech_date(today_str)
    morning_items = []
    for ch in today_changes:
        morning_items.append({
            "date": today_str,
            "formatted_date": formatted_today,
            "hour": ch.get("hour", 0),
            "type": "morning",
            "text": ch.get("text", ""),
            "summary": f"{formatted_today} ({ch.get('hour', 0)}. hodina): {ch.get('text', '')}"
        })
    if today_takes_place:
        morning_items.append({
            "date": today_str,
            "formatted_date": formatted_today,
            "hour": 0,
            "type": "takesPlace",
            "text": today_takes_place,
            "summary": f"{formatted_today} (Oznámení dne): {today_takes_place}"
        })

    title = f"Ranní přehled rozvrhu ({class_name})"
    body = f"Dobré ráno! Dnešní přehled změn v rozvrhu ({formatted_today}):\n" + "\n".join(f"• {c['summary']}" for c in morning_items)

    logger.info("Sending morning notification to targets '%s'...", MORNING_NOTIFICATION_TARGETS)
    webhook_dispatcher.dispatch_all(
        target_class=class_name,
        changes=morning_items,
        custom_title=title,
        custom_message=body,
        targets=MORNING_NOTIFICATION_TARGETS,
        is_morning=True
    )

    return today_str

def main():
    global CLASS_NAME
    logger.info("==================================================")
    logger.info("🚀 Ječná Mimořádný Rozvrh Notifier Starting")
    logger.info("==================================================")
    now_local = datetime.now().astimezone()
    tz_name = now_local.tzname() or "UTC"
    utc_offset = now_local.strftime("%z")
    logger.info("Container local time: %s (%s, UTC%s)", now_local.strftime("%Y-%m-%d %H:%M:%S"), tz_name, utc_offset)
    logger.info("API sync: dynamic schedule with %d seconds delay after official API updates (fallback: %ds)", SYNC_DELAY_SECONDS, CHECK_INTERVAL)
    logger.info("Monitored class: %s", CLASS_NAME)
    logger.info("Repeat all changes on update: %s", REPEAT_ALL_CHANGES)
    logger.info("Morning notification: enabled=%s (targets: %s, sent on morning sync only if changes exist today)",
                MORNING_NOTIFICATION_ENABLED, MORNING_NOTIFICATION_TARGETS)
    logger.info("State file: %s", STATE_FILE)
    logger.info("API URL: %s", SUBSTITUTION_API_URL)

    jecna_client = JecnaClient(api_url=SUBSTITUTION_API_URL)
    webhook_dispatcher = WebhookDispatcher()

    if not webhook_dispatcher.has_any_webhook():
        logger.warning("⚠️ No webhooks are currently configured! Set HOMEASSISTANT_WEBHOOK_URL, DISCORD_WEBHOOK_URL, NTFY_URL, etc.")
    else:
        logger.info("Configured webhooks: HA=%s, Discord=%s, MorningDiscord=%s, Telegram=%s, ntfy=%s, Slack=%s, Generic=%s",
            bool(webhook_dispatcher.ha_webhook_url),
            bool(webhook_dispatcher.discord_webhook_url),
            bool(webhook_dispatcher.morning_discord_webhook_url),
            bool(webhook_dispatcher.telegram_token),
            bool(webhook_dispatcher.ntfy_url),
            bool(webhook_dispatcher.slack_webhook_url),
            bool(webhook_dispatcher.generic_webhook_url)
        )

    # Initial state check
    schedule_state, notified_history, last_morning_date = load_state()
    is_first_run = (schedule_state is None)

    if not is_first_run:
        logger.info("Loaded existing state: %d dates, %d historical notified changes.", len(schedule_state), len(notified_history))

    while True:
        sleep_duration = float(CHECK_INTERVAL)
        try:
            logger.info("Fetching latest substitution schedule for class '%s'...", CLASS_NAME)
            raw_data = jecna_client.fetch_substitutions()

            if raw_data:
                current_schedule = jecna_client.extract_class_schedule(raw_data, CLASS_NAME)
                status_info = raw_data.get("status", {})
                server_schedule = status_info.get("currentUpdateSchedule")
                logger.info("Fetched schedule successfully (last updated on server: %s, server interval: %s min)",
                            status_info.get("lastUpdated", "unknown"), server_schedule)

                sleep_duration = calculate_next_sync_delay(server_schedule, delay_seconds=SYNC_DELAY_SECONDS)

                if is_first_run:
                    logger.info("Baseline initialization: Priming current known schedule (%d dates tracked for %s).", len(current_schedule), CLASS_NAME)
                    # Record all existing items into notified_history so they are never treated as new
                    for d, day_info in current_schedule.items():
                        for ch in day_info.get("changes", []):
                            notified_history.add(f"{d}#{ch.get('hour', 0)}#new#{ch.get('text', '')}")
                        if day_info.get("takesPlace"):
                            notified_history.add(f"{d}#0#takesPlace#{day_info.get('takesPlace')}")

                    schedule_state = current_schedule
                    save_state(schedule_state, notified_history, last_morning_date)
                    is_first_run = False
                    logger.info("✅ Baseline state primed with %d existing entries. No old notifications will be sent.", len(notified_history))
                else:
                    diffs = jecna_client.diff_schedules(schedule_state, current_schedule)
                    if diffs:
                        # Filter out any diffs that were already notified in the past
                        fresh_diffs = []
                        for d in diffs:
                            fp = make_fingerprint(d)
                            if fp in notified_history:
                                logger.info("⏭️ Skipping already known/notified change: %s", d["summary"])
                            else:
                                fresh_diffs.append(d)
                                notified_history.add(fp)

                        if fresh_diffs:
                            logger.info("🔥 Detected %d genuinely NEW change(s) in mimořádný rozvrh for class %s!", len(fresh_diffs), CLASS_NAME)
                            for d in fresh_diffs:
                                logger.info("   -> %s", d["summary"])

                            if REPEAT_ALL_CHANGES:
                                # When sending, include all currently active changes (repeat everything)
                                all_active = jecna_client.get_all_active_changes(current_schedule)
                                cancelled_items = [d for d in fresh_diffs if d.get("type") == "cancelled"]

                                items_to_send = cancelled_items + all_active
                                if not items_to_send and cancelled_items:
                                    items_to_send = cancelled_items

                                title = f"🔔 Mimořádný rozvrh ({CLASS_NAME})"
                                if len(items_to_send) == 1:
                                    body_msg = f"Zjištěna změna v rozvrhu:\n• {items_to_send[0]['summary']}"
                                else:
                                    body_msg = f"Zjištěna změna v rozvrhu! Aktuální přehled změn ({len(items_to_send)}):\n" + "\n".join(f"• {c['summary']}" for c in items_to_send)

                                webhook_dispatcher.dispatch_all(
                                    target_class=CLASS_NAME,
                                    changes=items_to_send,
                                    custom_title=title,
                                    custom_message=body_msg
                                )
                            else:
                                webhook_dispatcher.dispatch_all(CLASS_NAME, fresh_diffs)
                        else:
                            logger.info("ℹ️ Schedule changed, but all changes were already previously notified. No duplicate notification sent.")

                        schedule_state = current_schedule
                        save_state(schedule_state, notified_history, last_morning_date)
                    else:
                        logger.info("No changes detected for class %s. Everything is up to date.", CLASS_NAME)

                # Check and send morning notification
                last_morning_date = check_and_send_morning_notification(
                    current_schedule=current_schedule,
                    last_morning_date=last_morning_date,
                    webhook_dispatcher=webhook_dispatcher,
                    class_name=CLASS_NAME
                )
                save_state(schedule_state, notified_history, last_morning_date)

            else:
                logger.warning("Could not retrieve data from substitution server. Will retry in %d seconds.", CHECK_INTERVAL)
                sleep_duration = float(CHECK_INTERVAL)

        except Exception as e:
            logger.error("Error during check cycle: %s", e, exc_info=True)
            sleep_duration = float(CHECK_INTERVAL)

        logger.info("Next sync in %.1f seconds (~%.1f mins)...\n", sleep_duration, sleep_duration / 60)
        time.sleep(sleep_duration)

if __name__ == "__main__":
    main()
