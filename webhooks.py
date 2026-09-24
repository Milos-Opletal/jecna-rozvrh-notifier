import os
import logging
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

class WebhookDispatcher:
    def __init__(self):
        self.session = requests.Session()
        self.ha_webhook_url = os.getenv("HOMEASSISTANT_WEBHOOK_URL", "").strip()
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.ntfy_url = os.getenv("NTFY_URL", "").strip()
        self.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
        self.generic_webhook_url = os.getenv("GENERIC_WEBHOOK_URL", "").strip()

    def has_any_webhook(self) -> bool:
        return any([
            self.ha_webhook_url,
            self.discord_webhook_url,
            (self.telegram_token and self.telegram_chat_id),
            self.ntfy_url,
            self.slack_webhook_url,
            self.generic_webhook_url
        ])

    def dispatch_all(self, target_class: str, changes: list[dict]):
        if not changes:
            return

        title = f"Mimořádný rozvrh ({target_class})"
        if len(changes) == 1:
            body_message = changes[0]["summary"]
        else:
            body_message = f"Zjištěno {len(changes)} nových změn:\n" + "\n".join(f"• {c['summary']}" for c in changes)

        payload_base = {
            "event": "jecna_substitution_change",
            "title": title,
            "message": body_message,
            "class": target_class,
            "count": len(changes),
            "changes": changes,
            "timestamp": datetime.now().isoformat()
        }

        # 1. Home Assistant Webhook
        if self.ha_webhook_url:
            self._send_homeassistant(payload_base)

        # 2. Discord Webhook
        if self.discord_webhook_url:
            self._send_discord(title, body_message, target_class, changes)

        # 3. Telegram
        if self.telegram_token and self.telegram_chat_id:
            self._send_telegram(title, changes)

        # 4. ntfy.sh Push Notification
        if self.ntfy_url:
            self._send_ntfy(title, body_message)

        # 5. Slack Webhook
        if self.slack_webhook_url:
            self._send_slack(title, body_message)

        # 6. Generic Webhook
        if self.generic_webhook_url:
            self._send_generic(payload_base)

    def _send_homeassistant(self, payload: dict):
        try:
            logger.info("Sending Home Assistant webhook notification...")
            res = self.session.post(self.ha_webhook_url, json=payload, timeout=10)
            logger.info("Home Assistant webhook response: HTTP %d", res.status_code)
        except Exception as e:
            logger.error("Failed to send Home Assistant webhook: %s", e)

    def _send_discord(self, title: str, message: str, target_class: str, changes: list[dict]):
        try:
            logger.info("Sending Discord webhook notification...")
            fields = []
            for c in changes[:25]:  # Discord embed max fields
                date_display = c.get("formatted_date") or c.get("date")
                field_title = f"📅 {date_display} ({c['hour']}. hodina)" if c.get("hour", 0) > 0 else f"📢 {date_display}"
                field_value = (c.get("text") or "Změna v rozvrhu").strip()
                # Ensure Discord limits: name <= 256, value <= 1024
                fields.append({
                    "name": field_title[:256],
                    "value": field_value[:1024] if field_value else "Bez popisu",
                    "inline": False
                })

            discord_payload = {
                "username": "Ječná Mimořádný Rozvrh",
                "embeds": [
                    {
                        "title": f"🔔 {title}",
                        "color": 0x3498DB,
                        "description": f"Byla zjištěna nová suplování pro třídu **{target_class}**:",
                        "fields": fields,
                        "footer": {
                            "text": "SPŠE Ječná • Automatická kontrola"
                        },
                        "timestamp": datetime.now().astimezone().isoformat()
                    }
                ]
            }
            res = self.session.post(self.discord_webhook_url, json=discord_payload, timeout=10)
            logger.info("Discord webhook response: HTTP %d", res.status_code)
            if res.status_code >= 400:
                logger.warning("Discord embed rejected (HTTP %d: %s). Trying plain text fallback...", res.status_code, res.text)
                fallback_payload = {
                    "username": "Ječná Mimořádný Rozvrh",
                    "content": f"🔔 **{title}**\n{message}"
                }
                fallback_res = self.session.post(self.discord_webhook_url, json=fallback_payload, timeout=10)
                logger.info("Discord plain text fallback response: HTTP %d", fallback_res.status_code)
        except Exception as e:
            logger.error("Failed to send Discord webhook: %s", e)

    def _send_telegram(self, title: str, changes: list[dict]):
        try:
            logger.info("Sending Telegram message...")
            lines = [f"🔔 *{title}*\n"]
            for c in changes:
                lines.append(f"• `{c['summary']}`")
            text = "\n".join(lines)

            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown"
            }
            res = self.session.post(url, json=payload, timeout=10)
            logger.info("Telegram response: HTTP %d", res.status_code)
        except Exception as e:
            logger.error("Failed to send Telegram message: %s", e)

    def _send_ntfy(self, title: str, message: str):
        try:
            logger.info("Sending ntfy push notification to %s...", self.ntfy_url)
            res = self.session.post(
                self.ntfy_url,
                data=message.encode("utf-8"),
                headers={
                    "Title": title.encode("utf-8"),
                    "Priority": "high",
                    "Tags": "warning,school,calendar"
                },
                timeout=10
            )
            logger.info("ntfy response: HTTP %d", res.status_code)
        except Exception as e:
            logger.error("Failed to send ntfy push notification: %s", e)

    def _send_slack(self, title: str, message: str):
        try:
            logger.info("Sending Slack webhook notification...")
            res = self.session.post(
                self.slack_webhook_url,
                json={"text": f"🔔 *{title}*\n{message}"},
                timeout=10
            )
            logger.info("Slack response: HTTP %d", res.status_code)
        except Exception as e:
            logger.error("Failed to send Slack webhook: %s", e)

    def _send_generic(self, payload: dict):
        try:
            logger.info("Sending Generic webhook notification...")
            res = self.session.post(self.generic_webhook_url, json=payload, timeout=10)
            logger.info("Generic webhook response: HTTP %d", res.status_code)
        except Exception as e:
            logger.error("Failed to send Generic webhook: %s", e)
