import json
import os
import csv
import io
import threading
from datetime import datetime

class DatabaseManager:
    """
    Manages JSON-based database operations for the Forest Protection System.
    Handles counters (fallen trees, logged trees, fire incidents, ultrasonic entries)
    and detailed timestamped event logs in a thread-safe manner.
    Supports filtering by date, event type, search keywords, and CSV exports.
    """
    def __init__(self, db_path="data/forest_database.json"):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(script_dir) if os.path.basename(script_dir) == "python_backend" else script_dir

        # Prioritaskan pencarian file database yang ada di root atau python_backend
        if not os.path.isabs(db_path):
            candidate_root = os.path.join(root_dir, db_path)
            candidate_local = os.path.join(script_dir, db_path)
            if os.path.exists(candidate_root):
                self.db_path = candidate_root
            elif os.path.exists(candidate_local):
                self.db_path = candidate_local
            else:
                self.db_path = candidate_root
        else:
            self.db_path = db_path

        self.lock = threading.Lock()
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        if not os.path.exists(self.db_path):
            default_data = {
                "counters": {
                    "pohon_jatuh_alami": 0,
                    "pohon_ditebang": 0,
                    "insiden_api": 0,
                    "objek_masuk_ultrasonik": 0
                },
                "events": [],
                "system_status": {
                    "esp32_cam_connected": False,
                    "esp32_main_connected": False,
                    "fire_extinguish_mode": "AUTO",
                    "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            }
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(default_data, f, indent=2)

    def get_all(self):
        with self.lock:
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[DB ERROR] Failed to read database: {e}")
                return {"counters": {}, "events": [], "system_status": {}}

    def increment_counter(self, counter_name, step=1):
        with self.lock:
            data = self._read_unlocked()
            if counter_name in data["counters"]:
                data["counters"][counter_name] += step
            else:
                data["counters"][counter_name] = step
            data["system_status"]["last_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._write_unlocked(data)
            return data["counters"][counter_name]

    def log_event(self, event_type, description, zone="N/A", details=None):
        """
        Log an incident or sensor event into the database.
        event_type: 'POHON_JATUH_ALAMI', 'POHON_DITEBANG', 'API_TERDETEKSI', 'OBJEK_ULTRASONIK', 'SYSTEM'
        """
        with self.lock:
            data = self._read_unlocked()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Map counter
            if event_type == "POHON_JATUH_ALAMI":
                data["counters"]["pohon_jatuh_alami"] += 1
            elif event_type == "POHON_DITEBANG":
                data["counters"]["pohon_ditebang"] += 1
            elif event_type == "API_TERDETEKSI":
                data["counters"]["insiden_api"] += 1
            elif event_type == "OBJEK_ULTRASONIK":
                data["counters"]["objek_masuk_ultrasonik"] += 1

            new_event = {
                "id": len(data["events"]) + 1,
                "timestamp": timestamp,
                "type": event_type,
                "zone": zone,
                "description": description,
                "details": details or {}
            }
            
            # Prepend newest event first
            data["events"].insert(0, new_event)
            # Keep max 1000 events
            if len(data["events"]) > 1000:
                data["events"] = data["events"][:1000]
                
            data["system_status"]["last_sync"] = timestamp
            self._write_unlocked(data)
            return new_event

    def filter_events(self, date_query=None, event_type=None, search_keyword=None, limit=None):
        """
        Filter events dynamically by date (YYYY-MM-DD), type, or search keyword.
        Returns filtered events and aggregated statistics.
        """
        with self.lock:
            data = self._read_unlocked()
            events = data.get("events", [])

            filtered = []
            breakdown = {
                "pohon_jatuh_alami": 0,
                "pohon_ditebang": 0,
                "insiden_api": 0,
                "objek_masuk_ultrasonik": 0,
                "total": 0
            }

            date_str = str(date_query).strip() if date_query else ""
            ev_type = str(event_type).strip().upper() if event_type else ""
            kw = str(search_keyword).strip().lower() if search_keyword else ""

            for evt in events:
                evt_ts = evt.get("timestamp", "")
                evt_type_val = evt.get("type", "").upper()
                evt_desc = evt.get("description", "").lower()
                evt_zone = evt.get("zone", "").lower()

                # Filter Date (check if timestamp starts with or contains date_str)
                if date_str and not evt_ts.startswith(date_str):
                    continue

                # Filter Event Type
                if ev_type and ev_type != "ALL" and evt_type_val != ev_type:
                    continue

                # Filter Keyword (Search in description, zone, type)
                if kw and (kw not in evt_desc and kw not in evt_zone and kw not in evt_type_val.lower()):
                    continue

                filtered.append(evt)

                # Aggregation
                if evt_type_val == "POHON_JATUH_ALAMI":
                    breakdown["pohon_jatuh_alami"] += 1
                elif evt_type_val == "POHON_DITEBANG":
                    breakdown["pohon_ditebang"] += 1
                elif evt_type_val == "API_TERDETEKSI":
                    breakdown["insiden_api"] += 1
                elif evt_type_val == "OBJEK_ULTRASONIK":
                    breakdown["objek_masuk_ultrasonik"] += 1

            breakdown["total"] = len(filtered)

            if limit and limit > 0:
                filtered = filtered[:limit]

            return {
                "filtered_events": filtered,
                "breakdown": breakdown,
                "total_records": len(events)
            }

    def export_events_csv(self):
        """
        Generates CSV format string of all events in the local database.
        """
        with self.lock:
            data = self._read_unlocked()
            events = data.get("events", [])

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "ID",
                "Timestamp",
                "Tanggal",
                "Jam",
                "Tipe Event",
                "Wilayah / Sektor",
                "Deskripsi Insiden",
                "Confidence AI",
                "Sudut Servo",
                "Status"
            ])

            for evt in events:
                ts = str(evt.get("timestamp", ""))
                date_part = ts.split(" ")[0] if " " in ts else ts
                time_part = ts.split(" ")[1] if " " in ts else ""
                
                details = evt.get("details", {}) or {}
                conf = details.get("confidence", "")
                conf_str = "-"
                if conf is not None and conf != "":
                    try:
                        conf_str = f"{int(round(float(conf) * 100))}%"
                    except (ValueError, TypeError):
                        conf_str = str(conf)
                angle = details.get("angle", "-")

                writer.writerow([
                    evt.get("id", ""),
                    ts,
                    date_part,
                    time_part,
                    evt.get("type", ""),
                    evt.get("zone", ""),
                    evt.get("description", ""),
                    conf_str,
                    f"{angle}°" if angle != "-" else "-",
                    "TERCATAT"
                ])

            return output.getvalue()

    def update_system_status(self, key, value):
        with self.lock:
            data = self._read_unlocked()
            data["system_status"][key] = value
            data["system_status"]["last_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._write_unlocked(data)

    def _read_unlocked(self):
        with open(self.db_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_unlocked(self, data):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
