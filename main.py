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

from jecna import JecnaClient
from webhooks import WebhookDispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("JecnaNotifier")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "900"))
JECNA_USERNAME = os.getenv("JECNA_USERNAME", "").strip()
JECNA_PASSWORD = os.getenv("JECNA_PASSWORD", "").strip()
CLASS_NAME = os.getenv("CLASS_NAME", "").strip()
SUBSTITUTION_API_URL = os.getenv("SUBSTITUTION_API_URL", "https://jecnarozvrh.jzitnik.dev/versioned/v3").strip()
STATE_FILE = os.getenv("STATE_FILE_PATH", "/data/state.json")
ALERT_ON_STARTUP = os.getenv("ALERT_ON_STARTUP", "false").lower() in ("true", "1", "yes")

def load_state() -> dict | None:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to read state file '%s': %s", STATE_FILE, e)
    return None

def save_state(state: dict):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
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

    # Determine student class
    if not CLASS_NAME or CLASS_NAME.lower() == "auto":
        if JECNA_USERNAME and JECNA_PASSWORD:
            logger.info("Auto-detecting student class for user '%s'...", JECNA_USERNAME)
            CLASS_NAME = jecna_client.get_student_class_from_login(JECNA_USERNAME, JECNA_PASSWORD)
        else:
            logger.warning("Neither CLASS_NAME nor JECNA_USERNAME/PASSWORD provided. Defaulting to C4b.")
            CLASS_NAME = "C4b"

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
    state = load_state()
    is_first_run = (state is None)

    while True:
        try:
            logger.info("Fetching latest substitution schedule for class '%s'...", CLASS_NAME)
            raw_data = jecna_client.fetch_substitutions()

            if raw_data:
                current_schedule = jecna_client.extract_class_schedule(raw_data, CLASS_NAME)
                status_info = raw_data.get("status", {})
                logger.info("Fetched schedule successfully (last updated on server: %s)", status_info.get("lastUpdated", "unknown"))

                if is_first_run:
                    logger.info("First run: Priming initial baseline state (%d dates tracked for %s).", len(current_schedule), CLASS_NAME)
                    save_state(current_schedule)
                    state = current_schedule
                    is_first_run = False

                    if ALERT_ON_STARTUP:
                        initial_diffs = []
                        for d, day_info in current_schedule.items():
                            for ch in day_info["changes"]:
                                initial_diffs.append({
                                    "date": d,
                                    "hour": ch["hour"],
                                    "type": "new",
                                    "text": ch["text"],
                                    "summary": f"{d} ({ch['hour']}. hodina): {ch['text']}"
                                })
                        if initial_diffs:
                            logger.info("ALERT_ON_STARTUP is enabled: sending notification for %d existing entries", len(initial_diffs))
                            webhook_dispatcher.dispatch_all(CLASS_NAME, initial_diffs)
                else:
                    diffs = jecna_client.diff_schedules(state, current_schedule)
                    if diffs:
                        logger.info("🔥 Detected %d change(s) in mimořádný rozvrh for class %s!", len(diffs), CLASS_NAME)
                        for d in diffs:
                            logger.info("   -> %s", d["summary"])

                        webhook_dispatcher.dispatch_all(CLASS_NAME, diffs)
                        save_state(current_schedule)
                        state = current_schedule
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
