"""
=============================================================
  AIoT Forest Protection -- Central Network Configuration
=============================================================
  Modul sentral penyimpan & pembaca alamat IP ESP32.
  Mengubah IP di sini atau di main.py / server.py akan
  otomatis memperbarui seluruh script tanpa perlu edit ulang!
=============================================================
"""

import os
import json

def get_network_paths():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir) if os.path.basename(script_dir) == "python_backend" else script_dir
    return [
        os.path.join(root_dir, "data", "network_config.json"),
        os.path.join(root_dir, "python_backend", "data", "network_config.json")
    ]

def load_network_config(fallback_main="192.168.4.3", fallback_cam="192.168.4.2"):
    """Membaca konfigurasi IP dari file JSON sentral."""
    paths = get_network_paths()
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    main_ip = data.get("esp32_main_ip", fallback_main)
                    cam_ip  = data.get("esp32_cam_ip", fallback_cam)
                    m_port  = data.get("esp32_main_port", 8888)
                    c_port  = data.get("esp32_cam_port", 80)
                    return str(main_ip).strip(), str(cam_ip).strip(), int(m_port), int(c_port)
            except Exception:
                pass
    return fallback_main, fallback_cam, 8888, 80

def save_network_config(main_ip, cam_ip, main_port=8888, cam_port=80):
    """Menyimpan konfigurasi IP ke semua lokasi agar otomatis tersinkronisasi."""
    cfg = {
        "esp32_main_ip": str(main_ip).strip(),
        "esp32_cam_ip": str(cam_ip).strip(),
        "esp32_main_port": int(main_port),
        "esp32_cam_port": int(cam_port)
    }
    paths = get_network_paths()
    for p in paths:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
    return cfg
