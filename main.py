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
from jecna import JecnaClient
from webhooks import WebhookDispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("JecnaNotifier")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "900"))
CLASS_NAME = os.getenv("CLASS_NAME", "C4b").strip() or "C4b"
SUBSTITUTION_API_URL = os.getenv("SUBSTITUTION_API_URL", "https://jecnarozvrh.jzitnik.dev/versioned/v3").strip()
STATE_FILE = os.getenv("STATE_FILE_PATH", "/data/state.json")
ALERT_ON_STARTUP = os.getenv("ALERT_ON_STARTUP", "false").lower() in ("true", "1", "yes")

# Behavior options
REPEAT_ALL_CHANGES = os.getenv("REPEAT_ALL_CHANGES", "true").lower() in ("true", "1", "yes")

# Morning notification options
MORNING_NOTIFICATION_ENABLED = os.getenv("MORNING_NOTIFICATION_ENABLED", "true").lower() in ("true", "1", "yes")
MORNING_NOTIFICATION_TIME = os.getenv("MORNING_NOTIFICATION_TIME", "07:00").strip() or "07:00"
MORNING_NOTIFICATION_TARGETS = os.getenv("MORNING_NOTIFICATION_TARGETS", "all").strip() or "all"
MORNING_NOTIFICATION_ONLY_IF_CHANGES = os.getenv("MORNING_NOTIFICATION_ONLY_IF_CHANGES", "true").lower() in ("true", "1", "yes")

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
    class_name: str
) -> str | None:
    if not MORNING_NOTIFICATION_ENABLED:
        return last_morning_date

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # Already sent today
    if last_morning_date == today_str:
        return last_morning_date

    # Parse target morning time (HH:MM)
    try:
        parts = MORNING_NOTIFICATION_TIME.split(":")
        target_hour = int(parts[0])
        target_minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        target_hour, target_minute = 7, 0

    current_minutes = now.hour * 60 + now.minute
    target_minutes = target_hour * 60 + target_minute

    # Only send at or after the scheduled time, but before 12:00 noon
    if current_minutes < target_minutes or now.hour >= 12:
        return last_morning_date

    # Filter for today's entries only
    today_data = current_schedule.get(today_str, {})
    today_changes = today_data.get("changes", [])
    today_takes_place = today_data.get("takesPlace", "").strip()
    has_entries = bool(today_changes or today_takes_place)

    if not has_entries and MORNING_NOTIFICATION_ONLY_IF_CHANGES:
        logger.info("Morning check (%s): No substitutions for today. Skipping morning notification.", today_str)
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

    title = f"☀️ Ranní přehled rozvrhu ({class_name})"
    if has_entries:
        body = f"☀️ Dobré ráno! Dnešní přehled změn v rozvrhu ({formatted_today}):\n" + "\n".join(f"• {c['summary']}" for c in morning_items)
    else:
        body = f"☀️ Dobré ráno! Dnes ({formatted_today}) nemáte v mimořádném rozvrhu žádné změny, platí stálý rozvrh."

    logger.info("☀️ Sending morning notification to targets '%s'...", MORNING_NOTIFICATION_TARGETS)
    webhook_dispatcher.dispatch_all(
        target_class=class_name,
        changes=morning_items,
        custom_title=title,
        custom_message=body,
        targets=MORNING_NOTIFICATION_TARGETS
    )

    return today_str

def main():
    global CLASS_NAME
    logger.info("==================================================")
    logger.info("🚀 Ječná Mimořádný Rozvrh Notifier Starting")
    logger.info("==================================================")
    logger.info("Check interval: %d seconds (%d minutes)", CHECK_INTERVAL, CHECK_INTERVAL // 60)
    logger.info("Monitored class: %s", CLASS_NAME)
    logger.info("Repeat all changes on update: %s", REPEAT_ALL_CHANGES)
    logger.info("Morning notification: %s (time: %s, targets: %s)", MORNING_NOTIFICATION_ENABLED, MORNING_NOTIFICATION_TIME, MORNING_NOTIFICATION_TARGETS)
    logger.info("State file: %s", STATE_FILE)
    logger.info("API URL: %s", SUBSTITUTION_API_URL)

    jecna_client = JecnaClient(api_url=SUBSTITUTION_API_URL)
    webhook_dispatcher = WebhookDispatcher()

    if not webhook_dispatcher.has_any_webhook():
        logger.warning("⚠️ No webhooks are currently configured! Set HOMEASSISTANT_WEBHOOK_URL, DISCORD_WEBHOOK_URL, NTFY_URL, etc.")
    else:
        logger.info("Configured webhooks: HA=%s, Discord=%s, Telegram=%s, ntfy=%s, Slack=%s, Generic=%s",
            bool(webhook_dispatcher.ha_webhook_url),
            bool(webhook_dispatcher.discord_webhook_url),
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
        try:
            logger.info("Fetching latest substitution schedule for class '%s'...", CLASS_NAME)
            raw_data = jecna_client.fetch_substitutions()

            if raw_data:
                current_schedule = jecna_client.extract_class_schedule(raw_data, CLASS_NAME)
                status_info = raw_data.get("status", {})
                logger.info("Fetched schedule successfully (last updated on server: %s)", status_info.get("lastUpdated", "unknown"))

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
                        logger.info("✅ No changes detected for class %s. Everything is up to date.", CLASS_NAME)

                # Check and send morning notification if time has arrived
                last_morning_date = check_and_send_morning_notification(
                    current_schedule=current_schedule,
                    last_morning_date=last_morning_date,
                    webhook_dispatcher=webhook_dispatcher,
                    class_name=CLASS_NAME
                )
                save_state(schedule_state, notified_history, last_morning_date)

            else:
                logger.warning("Could not retrieve data from substitution server. Will retry next interval.")

        except Exception as e:
            logger.error("Error during check cycle: %s", e, exc_info=True)

        logger.info("Sleeping for %d seconds (next check in %d mins)...\n", CHECK_INTERVAL, CHECK_INTERVAL // 60)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
