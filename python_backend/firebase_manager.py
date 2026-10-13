"""
=============================================================================
 AIoT Forest Protection - Firebase Realtime Database Connector (Cloud Global)
=============================================================================
Fungsi:
  - Mengirimkan data telemetri, counter, status sistem, dan event log ke
    Firebase Realtime Database (Google Cloud) via REST API.
  - Non-blocking (Asynchronous): Berjalan di background thread sehingga tidak
    menghambat performa kamera, inferensi AI, dan pergerakan servo ESP32.
  - Memungkinkan monitoring data secara publik / global melalui Firebase Console
    atau URL web publik mana pun.
=============================================================================
"""

import os
import sys
import json
import time
import threading
import requests
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "python_backend" else SCRIPT_DIR
CONFIG_PATHS = [
    os.path.join(ROOT_DIR, "data", "firebase_config.json"),
    os.path.join(ROOT_DIR, "python_backend", "data", "firebase_config.json")
]
CONFIG_PATH = CONFIG_PATHS[0]

DEFAULT_FIREBASE_CONFIG = {
    "enabled": True,
    # Masukkan URL Firebase Realtime Database Anda di sini:
    # Contoh: "https://proyek-aiot-hutan-default-rtdb.firebaseio.com"
    "database_url": "https://aiot-forest-protection-default-rtdb.firebaseio.com",
    # Opsional: Database secret / auth token (kosongkan jika rules .read=true, .write=true)
    "auth_token": "",
    "sync_interval_seconds": 3
}


class FirebaseManager:
    def __init__(self, config_path=None):
        self.config_path = config_path or CONFIG_PATH
        self.lock = threading.Lock()
        self.config = self._load_config()
        self._last_sync_time = 0.0
        self._last_warn_time = 0.0

    def _load_config(self):
        cfg = DEFAULT_FIREBASE_CONFIG.copy()
        loaded = False
        for cp in CONFIG_PATHS:
            if os.path.exists(cp):
                try:
                    with open(cp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        cfg.update(data)
                        loaded = True
                        break
                except Exception as e:
                    print(f"[FIREBASE] Gagal membaca config {cp}: {e}")

        if not loaded:
            self._save_config(cfg)
        return cfg

    def _save_config(self, cfg):
        for cp in CONFIG_PATHS:
            try:
                os.makedirs(os.path.dirname(cp), exist_ok=True)
                with open(cp, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2)
            except Exception as e:
                print(f"[FIREBASE] Gagal menyimpan config {cp}: {e}")

    def update_config(self, database_url, auth_token=None, enabled=True):
        """Memperbarui URL Firebase secara dinamis saat runtime."""
        with self.lock:
            self.config["database_url"] = database_url.strip()
            if auth_token is not None:
                self.config["auth_token"] = auth_token.strip()
            self.config["enabled"] = bool(enabled)
            self._save_config(self.config)

    def _build_url(self, path="forest_protection"):
        """Membangun endpoint URL REST API Firebase."""
        base_url = self.config.get("database_url", "").strip().rstrip("/")
        if not base_url or not base_url.startswith("http"):
            return None

        clean_path = path.strip("/")
        auth = self.config.get("auth_token", "").strip()
        auth_param = f"?auth={auth}" if auth else ""
        return f"{base_url}/{clean_path}.json{auth_param}"

    def is_active(self):
        url = self.config.get("database_url", "").strip()
        return self.config.get("enabled", True) and bool(url) and url.startswith("http")

    # -------------------------------------------------------------------------
    #  OPERASI PENGIRIMAN DATA KE FIREBASE
    # -------------------------------------------------------------------------

    def sync_telemetry_async(self, telemetry_dict):
        """Kirim pembaruan telemetri di background thread."""
        threading.Thread(target=self._sync_telemetry_worker, args=(telemetry_dict,), daemon=True).start()

    def _sync_telemetry_worker(self, telemetry_dict):
        if not self.is_active():
            return
        url = self._build_url("forest_protection/telemetry")
        if not url:
            return
        try:
            payload = telemetry_dict.copy()
            payload["last_cloud_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            requests.patch(url, json=payload, timeout=3.0)
        except Exception as e:
            self._log_warn(f"Gagal kirim telemetri: {e}")

    def sync_counters_async(self, counters_dict):
        """Kirim statistik counter ke Firebase di background thread."""
        threading.Thread(target=self._sync_counters_worker, args=(counters_dict,), daemon=True).start()

    def _sync_counters_worker(self, counters_dict):
        if not self.is_active():
            return
        url = self._build_url("forest_protection/counters")
        if not url:
            return
        try:
            requests.put(url, json=counters_dict, timeout=3.0)
        except Exception as e:
            self._log_warn(f"Gagal kirim counter: {e}")

    def push_incident_event_async(self, event_dict):
        """Kirim log kejadian baru ke Firebase di background thread."""
        threading.Thread(target=self._push_incident_worker, args=(event_dict,), daemon=True).start()

    def _push_incident_worker(self, event_dict):
        if not self.is_active():
            return
        # 1. Simpan sebagai insiden terakhir (last_incident)
        url_last = self._build_url("forest_protection/last_incident")
        # 2. Tambahkan ke riwayat events list (POST untuk auto-generated push ID)
        url_events = self._build_url("forest_protection/events")

        try:
            if url_last:
                requests.put(url_last, json=event_dict, timeout=3.0)
            if url_events:
                requests.post(url_events, json=event_dict, timeout=3.0)
            print(f"[FIREBASE] ✅ Data insiden #{event_dict.get('id', '')} berhasil dikirim ke Cloud Firebase!")
        except Exception as e:
            self._log_warn(f"Gagal kirim insiden: {e}")

    def sync_system_status_async(self, status_dict):
        """Kirim status sistem (koneksi esp32, mode pemadam, dll) ke Firebase."""
        threading.Thread(target=self._sync_status_worker, args=(status_dict,), daemon=True).start()

    def _sync_status_worker(self, status_dict):
        if not self.is_active():
            return
        url = self._build_url("forest_protection/system_status")
        if not url:
            return
        try:
            requests.patch(url, json=status_dict, timeout=3.0)
        except Exception as e:
            self._log_warn(f"Gagal kirim system status: {e}")

    def sync_full_snapshot_async(self, full_db_dict, telemetry_dict):
        """Mengirimkan seluruh snapshot sistem ke Firebase secara berkala."""
        now = time.time()
        interval = self.config.get("sync_interval_seconds", 3)
        if now - self._last_sync_time < interval:
            return
        self._last_sync_time = now

        threading.Thread(
            target=self._sync_full_snapshot_worker,
            args=(full_db_dict, telemetry_dict),
            daemon=True
        ).start()

    def _sync_full_snapshot_worker(self, full_db_dict, telemetry_dict):
        if not self.is_active():
            return
        url = self._build_url("forest_protection")
        if not url:
            return
        try:
            payload = {
                "counters": full_db_dict.get("counters", {}),
                "system_status": full_db_dict.get("system_status", {}),
                "telemetry": telemetry_dict,
                "last_cloud_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if full_db_dict.get("events"):
                payload["last_incident"] = full_db_dict["events"][0]
            requests.patch(url, json=payload, timeout=3.5)
        except Exception as e:
            self._log_warn(f"Gagal sinkronisasi snapshot: {e}")

    def _log_warn(self, msg):
        now = time.time()
        # Batasi log warning maksimal 1 kali per 30 detik agar tidak membanjiri terminal
        if now - self._last_warn_time > 30.0:
            self._last_warn_time = now
            print(f"[FIREBASE CLOUD] [!] {msg} (Periksa koneksi internet atau database_url di data/firebase_config.json)")
