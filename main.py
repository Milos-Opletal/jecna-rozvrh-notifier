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

def make_fingerprint(item: dict) -> str:
    """Generate a unique fingerprint for a change to prevent duplicate notifications."""
    date = item.get("date", "")
    hour = item.get("hour", 0)
    change_type = item.get("type", "new")
    text = item.get("text", "")
    return f"{date}#{hour}#{change_type}#{text}"

def load_state() -> tuple[dict | None, set[str]]:
    """
    Loads saved schedule state and previously notified history fingerprints.
    Supports both legacy state.json (plain dict of dates) and v2 format.
    """
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if "version" in data and "schedule" in data:
                    return data.get("schedule", {}), set(data.get("notified_history", []))
                else:
                    # Legacy v1 format migration (dict of date -> day_info)
                    history = set()
                    for d, day_info in data.items():
                        for ch in day_info.get("changes", []):
                            history.add(f"{d}#{ch.get('hour', 0)}#new#{ch.get('text', '')}")
                        if day_info.get("takesPlace"):
                            history.add(f"{d}#0#takesPlace#{day_info.get('takesPlace')}")
                    return data, history
        except Exception as e:
            logger.error("Failed to read state file '%s': %s", STATE_FILE, e)
    return None, set()

def save_state(schedule: dict, notified_history: set[str]):
    """Saves schedule and history, automatically pruning entries older than 14 days."""
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
            "schedule": schedule,
            "notified_history": sorted(pruned_history)
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Failed to save state to '%s': %s", STATE_FILE, e)

def main():
    global CLASS_NAME
    logger.info("==================================================")
    logger.info("🚀 Ječná Mimořádný Rozvrh Notifier Starting")
    logger.info("==================================================")
    logger.info("Check interval: %d seconds (%d minutes)", CHECK_INTERVAL, CHECK_INTERVAL // 60)
    logger.info("State file: %s", STATE_FILE)
    logger.info("API URL: %s", SUBSTITUTION_API_URL)

    jecna_client = JecnaClient(api_url=SUBSTITUTION_API_URL)
    webhook_dispatcher = WebhookDispatcher()

    logger.info("Monitored class: %s", CLASS_NAME)

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
    schedule_state, notified_history = load_state()
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
                    save_state(schedule_state, notified_history)
                    is_first_run = False
                    logger.info("✅ Baseline state primed with %d existing entries. No old notifications will be sent.", len(notified_history))

                    if ALERT_ON_STARTUP:
                        logger.info("ALERT_ON_STARTUP is enabled, but entries are already recorded in baseline.")
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

                            webhook_dispatcher.dispatch_all(CLASS_NAME, fresh_diffs)
                        else:
                            logger.info("ℹ️ Schedule changed, but all changes were already previously notified. No duplicate notification sent.")

                        schedule_state = current_schedule
                        save_state(schedule_state, notified_history)
                    else:
                        logger.info("✅ No changes detected for class %s. Everything is up to date.", CLASS_NAME)
            else:
                logger.warning("Could not retrieve data from substitution server. Will retry next interval.")

        except Exception as e:
            logger.error("Error during check cycle: %s", e, exc_info=True)

        logger.info("Sleeping for %d seconds (next check in %d mins)...\n", CHECK_INTERVAL, CHECK_INTERVAL // 60)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
