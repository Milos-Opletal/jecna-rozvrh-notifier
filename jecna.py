import logging
import re
import requests

logger = logging.getLogger(__name__)

class JecnaClient:
    def __init__(self, api_url: str = "https://jecnarozvrh.jzitnik.dev/versioned/v3"):
        self.api_url = api_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/html, */*"
        })

    def get_student_class_from_login(self, username: str, password: str) -> str:
        """
        Logs into spsejecna.cz to retrieve the student's class name (e.g. 'C4b').
        """
        try:
            logger.info("Connecting to SPŠE Ječná portal to detect student class...")
            # Step 1: GET login page to obtain token
            res = self.session.get("https://www.spsejecna.cz/user/login", timeout=15)
            token_match = re.search(r'name=["\']token["\']\s+value=["\']([^"\']+)["\']', res.text)
            token = token_match.group(1) if token_match else None

            # Step 2: POST credentials
            post_data = {"user": username, "pass": password}
            if token:
                post_data["token"] = token

            login_res = self.session.post("https://www.spsejecna.cz/user/login", data=post_data, timeout=15)

            # Step 3: Parse student class
            # Profile page contains: <span class="value">4.B</span> or link to /trida/4.B
            class_patterns = [
                r'class="value">([1-4]\.[A-Za-z0-9]+)</span>',
                r'/trida/([1-4]\.[A-Za-z0-9]+)',
                r'class="user-profile".*?([1-4]\.[A-Za-z0-9]+)'
            ]
            for pattern in class_patterns:
                m = re.search(pattern, login_res.text, re.DOTALL)
                if m:
                    raw_class = m.group(1).strip()
                    # e.g. "4.B" or "4.B (obor C)" -> convert to "C4b" or keep normalized
                    # In Ječná rozvrh API, classes are typically named like "C4b", "A1a", "E3"
                    norm = self._normalize_class_name(raw_class)
                    logger.info("Found student class '%s' (normalized: '%s')", raw_class, norm)
                    return norm

            logger.warning("Could not parse student class from profile page, falling back to C4b")
        except Exception as e:
            logger.error("Error logging in to SPŠE Ječná portal: %s", e)

        return "C4b"

    def _normalize_class_name(self, raw: str) -> str:
        """
        Normalizes class string:
        e.g. '4.B' -> check if it maps to C4b / A4b etc. or strips dot '4B'
        """
        clean = re.sub(r'[^A-Za-z0-9]', '', raw)
        return clean

    def fetch_substitutions(self) -> dict | None:
        """
        Fetches the latest mimořádný rozvrh JSON from jecnarozvrh server.
        """
        try:
            res = self.session.get(self.api_url, timeout=20)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            logger.error("Failed to fetch substitutions from %s: %s", self.api_url, e)
            return None

    def extract_class_schedule(self, api_data: dict, target_class: str) -> dict:
        """
        Extracts substitution entries for target_class across all dates.
        Returns: {
            "2026-09-24": {
                "changes": [ {"hour": 1, "text": "2/2 TP 21 (Ad) odpadá"}, ... ],
                "takesPlace": "...",
                "inWork": false
            }
        }
        """
        class_schedule = {}
        schedule_map = api_data.get("schedule", {})
        norm_target = self._normalize_class_name(target_class).lower()

        for date, day_data in schedule_map.items():
            changes_by_class = day_data.get("changes", {})

            matched_key = None
            for key in changes_by_class.keys():
                if self._normalize_class_name(key).lower() == norm_target:
                    matched_key = key
                    break

            changes_list = []
            if matched_key and changes_by_class[matched_key]:
                for hour_idx, item in enumerate(changes_by_class[matched_key]):
                    if item and isinstance(item, dict) and item.get("text"):
                        clean_text = " ".join(item.get("text").split())
                        changes_list.append({
                            "hour": hour_idx + 1,
                            "text": clean_text
                        })

            takes_place = day_data.get("takesPlace", "") or ""
            class_schedule[date] = {
                "changes": changes_list,
                "takesPlace": takes_place.strip(),
                "inWork": day_data.get("info", {}).get("inWork", False)
            }

        return class_schedule

    def diff_schedules(self, old_state: dict, new_state: dict) -> list[dict]:
        """
        Finds differences between old schedule state and new schedule state.
        Returns a list of change objects.
        """
        diffs = []

        for date, new_day in new_state.items():
            old_day = old_state.get(date)

            if not old_day:
                # Brand new date discovered
                for ch in new_day["changes"]:
                    diffs.append({
                        "date": date,
                        "hour": ch["hour"],
                        "type": "new",
                        "text": ch["text"],
                        "summary": f"{date} ({ch['hour']}. hodina): {ch['text']}"
                    })
                if new_day["takesPlace"]:
                    diffs.append({
                        "date": date,
                        "hour": 0,
                        "type": "takesPlace",
                        "text": new_day["takesPlace"],
                        "summary": f"{date}: {new_day['takesPlace']}"
                    })
                continue

            old_changes = {c["hour"]: c["text"] for c in old_day.get("changes", [])}
            new_changes = {c["hour"]: c["text"] for c in new_day.get("changes", [])}

            all_hours = sorted(set(old_changes.keys()) | set(new_changes.keys()))
            for h in all_hours:
                old_t = old_changes.get(h)
                new_t = new_changes.get(h)

                if new_t and not old_t:
                    diffs.append({
                        "date": date,
                        "hour": h,
                        "type": "new",
                        "text": new_t,
                        "summary": f"{date} ({h}. hodina): {new_t}"
                    })
                elif new_t and old_t and new_t != old_t:
                    diffs.append({
                        "date": date,
                        "hour": h,
                        "type": "changed",
                        "old_text": old_t,
                        "text": new_t,
                        "summary": f"{date} ({h}. hodina): {old_t} -> {new_t}"
                    })
                elif old_t and not new_t:
                    diffs.append({
                        "date": date,
                        "hour": h,
                        "type": "cancelled",
                        "old_text": old_t,
                        "summary": f"{date} ({h}. hodina): Změna zrušena ({old_t})"
                    })

            old_tp = old_day.get("takesPlace", "").strip()
            new_tp = new_day.get("takesPlace", "").strip()
            if new_tp and new_tp != old_tp:
                diffs.append({
                    "date": date,
                    "hour": 0,
                    "type": "takesPlace",
                    "text": new_tp,
                    "summary": f"{date} (Oznámení dne): {new_tp}"
                })

        return diffs
