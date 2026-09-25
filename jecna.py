import logging
import re
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

def format_czech_date(date_str: str) -> str:
    """
    Formats YYYY-MM-DD into friendly Czech text, e.g.:
    - 'Dnes (čt 24.9.)'
    - 'Zítra (pá 25.9.)'
    - 'Pondělí (po 28.9.)'
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        diff_days = (dt - today).days

        day_abbrs = ["po", "út", "st", "čt", "pá", "so", "ne"]
        day_names = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]

        weekday = dt.weekday()
        abbr = day_abbrs[weekday]
        date_short = f"{dt.day}.{dt.month}."

        if diff_days == 0:
            prefix = "Dnes"
        elif diff_days == 1:
            prefix = "Zítra"
        elif diff_days == 2:
            prefix = "Pozítří"
        elif diff_days == -1:
            prefix = "Včera"
        else:
            prefix = day_names[weekday]

        return f"{prefix} ({abbr} {date_short})"
    except Exception:
        return date_str

class JecnaClient:
    def __init__(self, api_url: str = "https://jecnarozvrh.jzitnik.dev/versioned/v3"):
        self.api_url = api_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/html, */*"
        })

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
        Returns a list of change objects with friendly Czech date formatting.
        """
        diffs = []

        for date, new_day in new_state.items():
            formatted_date = format_czech_date(date)
            old_day = old_state.get(date)

            if not old_day:
                # Brand new date discovered
                for ch in new_day["changes"]:
                    diffs.append({
                        "date": date,
                        "formatted_date": formatted_date,
                        "hour": ch["hour"],
                        "type": "new",
                        "text": ch["text"],
                        "summary": f"{formatted_date} ({ch['hour']}. hodina): {ch['text']}"
                    })
                if new_day["takesPlace"]:
                    diffs.append({
                        "date": date,
                        "formatted_date": formatted_date,
                        "hour": 0,
                        "type": "takesPlace",
                        "text": new_day["takesPlace"],
                        "summary": f"{formatted_date} (Oznámení dne): {new_day['takesPlace']}"
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
                        "formatted_date": formatted_date,
                        "hour": h,
                        "type": "new",
                        "text": new_t,
                        "summary": f"{formatted_date} ({h}. hodina): {new_t}"
                    })
                elif new_t and old_t and new_t != old_t:
                    diffs.append({
                        "date": date,
                        "formatted_date": formatted_date,
                        "hour": h,
                        "type": "changed",
                        "old_text": old_t,
                        "text": new_t,
                        "summary": f"{formatted_date} ({h}. hodina): {old_t} -> {new_t}"
                    })
                elif old_t and not new_t:
                    diffs.append({
                        "date": date,
                        "formatted_date": formatted_date,
                        "hour": h,
                        "type": "cancelled",
                        "old_text": old_t,
                        "summary": f"{formatted_date} ({h}. hodina): Změna zrušena ({old_t})"
                    })

            old_tp = old_day.get("takesPlace", "").strip()
            new_tp = new_day.get("takesPlace", "").strip()
            if new_tp and new_tp != old_tp:
                diffs.append({
                    "date": date,
                    "formatted_date": formatted_date,
                    "hour": 0,
                    "type": "takesPlace",
                    "text": new_tp,
                    "summary": f"{formatted_date} (Oznámení dne): {new_tp}"
                })

        return diffs

    def get_all_active_changes(self, schedule: dict) -> list[dict]:
        """
        Returns all active changes from schedule for today and upcoming dates.
        Sorted chronologically by date and hour.
        """
        today = datetime.now().date()
        active_list = []

        for date_str in sorted(schedule.keys()):
            try:
                d_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if d_date < today:
                    continue  # Do not include past dates
            except Exception:
                pass

            day_info = schedule.get(date_str, {})
            formatted_date = format_czech_date(date_str)

            for ch in day_info.get("changes", []):
                active_list.append({
                    "date": date_str,
                    "formatted_date": formatted_date,
                    "hour": ch.get("hour", 0),
                    "type": "active",
                    "text": ch.get("text", ""),
                    "summary": f"{formatted_date} ({ch.get('hour', 0)}. hodina): {ch.get('text', '')}"
                })

            tp = day_info.get("takesPlace", "").strip()
            if tp:
                active_list.append({
                    "date": date_str,
                    "formatted_date": formatted_date,
                    "hour": 0,
                    "type": "takesPlace",
                    "text": tp,
                    "summary": f"{formatted_date} (Oznámení dne): {tp}"
                })

        return active_list
