import json
import os
import threading
from datetime import datetime

class DatabaseManager:
    """
    Manages JSON-based database operations for the Forest Protection System.
    Handles counters (fallen trees, logged trees, fire incidents, ultrasonic entries)
    and detailed timestamped event logs in a thread-safe manner.
    """
    def __init__(self, db_path="data/forest_database.json"):
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
            with open(self.db_path, "w") as f:
                json.dump(default_data, f, indent=2)

    def get_all(self):
        with self.lock:
            try:
                with open(self.db_path, "r") as f:
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
            # Keep max 500 events
            if len(data["events"]) > 500:
                data["events"] = data["events"][:500]
                
            data["system_status"]["last_sync"] = timestamp
            self._write_unlocked(data)
            return new_event

    def update_system_status(self, key, value):
        with self.lock:
            data = self._read_unlocked()
            data["system_status"][key] = value
            data["system_status"]["last_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._write_unlocked(data)

    def _read_unlocked(self):
        with open(self.db_path, "r") as f:
            return json.load(f)

    def _write_unlocked(self, data):
        with open(self.db_path, "w") as f:
            json.dump(data, f, indent=2)
