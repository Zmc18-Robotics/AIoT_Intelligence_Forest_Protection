"""
=======================================================================
 AIoT Intelligence Forest Protection - Central Server & TCP/IP Hub
=======================================================================
Cukup tulis IP ESP32 dan ESP32-CAM langsung di kode di bawah ini!
Saat dijalankan, Python langsung menghubungkan keduanya secara otomatis.
=======================================================================
"""

import os
import sys
import time
import json
import socket
import threading
import cv2
import numpy as np
from datetime import datetime

# Pastikan folder python_backend ada di sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import io
from flask import Flask, render_template, Response, request, jsonify, send_file

# Coba import Flask-CORS dengan auto-install
try:
    from flask_cors import CORS
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "flask-cors"])
    from flask_cors import CORS

# Coba import Flask-SocketIO dengan auto-install & fallback
try:
    from flask_socketio import SocketIO, emit
    HAS_SOCKETIO = True
except ImportError:
    import subprocess
    print("[INFO] Paket 'flask-socketio' belum terpasang. Memasang otomatis...")
    subprocess.run([sys.executable, "-m", "pip", "install", "flask-socketio", "simple-websocket"])
    try:
        from flask_socketio import SocketIO, emit
        HAS_SOCKETIO = True
    except ImportError:
        HAS_SOCKETIO = False
        class DummySocketIO:
            def __init__(self, *args, **kwargs): pass
            def emit(self, *args, **kwargs): pass
            def on(self, event):
                def decorator(f): return f
                return decorator
            def run(self, app, **kwargs):
                app.run(host=kwargs.get('host', '0.0.0.0'), port=kwargs.get('port', 5000), debug=kwargs.get('debug', False))
        SocketIO = DummySocketIO
        def emit(*args, **kwargs): pass

from database_manager import DatabaseManager
from ai_detector import ForestAIDetector

# Import Notifikasi Email Terpadu (Damkar, Pohon Jatuh, Pohon Ditebang, Hardware Danger)
try:
    from email_notifier import (
        send_fire_alert_email_async,
        send_tree_fall_email_async,
        send_illegal_logging_email_async,
        send_hardware_danger_email_async
    )
except ImportError:
    try:
        sys.path.append(os.path.dirname(backend_dir))
        from email_notifier import (
            send_fire_alert_email_async,
            send_tree_fall_email_async,
            send_illegal_logging_email_async,
            send_hardware_danger_email_async
        )
    except Exception:
        def send_fire_alert_email_async(*args, **kwargs): pass
        def send_tree_fall_email_async(*args, **kwargs): pass
        def send_illegal_logging_email_async(*args, **kwargs): pass
        def send_hardware_danger_email_async(*args, **kwargs): pass

# Import Firebase Cloud Manager
try:
    from firebase_manager import FirebaseManager
    firebase_mgr = FirebaseManager()
except ImportError:
    class FirebaseManager:
        def sync_telemetry_async(self, *a, **k): pass
        def push_incident_event_async(self, *a, **k): pass
        def sync_full_snapshot_async(self, *a, **k): pass
        def is_active(self): return False
    firebase_mgr = FirebaseManager()

def get_local_ip():
    """Mendeteksi IP LAN / WiFi komputer ini agar bisa diakses oleh device apa pun di WiFi yang sama."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip

# =====================================================================
# KONFIGURASI IP SENTRAL (OTOMATIS SINKRON DENGAN main.py & test_model.py)
# =====================================================================
try:
    from network_config import load_network_config, save_network_config
    ESP32_MAIN_IP, ESP32_CAM_IP, ESP32_MAIN_PORT, ESP32_CAM_PORT = load_network_config("192.168.4.3", "192.168.4.2")
except Exception:
    ESP32_MAIN_IP   = "10.241.248.42"
    ESP32_CAM_IP    = "10.241.248.25"
    ESP32_MAIN_PORT = 8888
    ESP32_CAM_PORT  = 80
# =====================================================================

# Jika ada argumen dari terminal, contoh: python server.py 192.168.4.3 192.168.4.2
if len(sys.argv) > 1 and "." in sys.argv[1]:
    ESP32_MAIN_IP = sys.argv[1].strip()
if len(sys.argv) > 2 and "." in sys.argv[2]:
    ESP32_CAM_IP = sys.argv[2].strip()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "aiot-forest-protection-2026"
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Inisialisasi Modul
db = DatabaseManager(db_path="data/forest_database.json")
ai_engine = ForestAIDetector(conf_thresh=0.45)

# Runtime State
class SystemState:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_frame = None
        self.annotated_frame = None
        self.last_detections = []
        
        # Telemetry from ESP32
        self.ultrasonic_distance = 100.0 # cm
        self.flame_sensor_raw = 1 # 1 = normal, 0 = flame detected
        
        # Actuator status on ESP32 (2 Servos & 2 Relays)
        self.tower1_servo = 90
        self.tower2_servo = 90
        self.relay1_status = False
        self.relay2_status = False
        self.buzzer_status = False
        self.rgb_color = "GREEN"

        # Flag pemadaman otomatis agar tidak menimpa kontrol manual
        self.auto_fire_active = False
        
        # Network clients
        self.esp32_main_client = None
        self.esp32_cam_connected = False
        self.esp32_main_connected = False
        
        # Cooldown trackers & Timers
        self.last_fire_log_time = 0
        self.last_fallen_log_time = 0
        self.last_cut_log_time = 0
        self.last_ultrasonic_log_time = 0
        self.fire_start_time = None
        self.fire_email_dispatched = False

        # Target angle locking & 2-second update delay for Servos (Anti-jitter & stabilitas)
        self.locked_angle_1 = 90
        self.is_fire_locked_1 = False
        self.last_angle_update_1 = 0.0

        self.locked_angle_2 = 90
        self.is_fire_locked_2 = False
        self.last_angle_update_2 = 0.0

        self.last_fire_time_1 = 0.0
        self.last_fire_time_2 = 0.0

        self.last_sent_z1_active = False
        self.last_sent_z2_active = False
        self.last_sent_angle_1 = 90
        self.last_sent_angle_2 = 90
        self.last_cmd_time = 0.0

state = SystemState()

# ---------------------------------------------------------------------
# PENGIRIM PERINTAH CEPAT (TCP_NODELAY + HTTP FALLBACK)
# ---------------------------------------------------------------------
def send_command_to_esp32(cmd_dict):
    """Kirim JSON command ke ESP32 Main dengan TCP_NODELAY (respon instan < 1 ms)."""
    with state.lock:
        client = state.esp32_main_client

    sent_via_tcp = False
    if client:
        try:
            msg = json.dumps(cmd_dict) + "\n"
            client.sendall(msg.encode('utf-8'))
            sent_via_tcp = True
        except Exception as e:
            print(f"[TCP] [ERR] Gagal kirim ke ESP32 Main: {e}")
            with state.lock:
                state.esp32_main_connected = False
                state.esp32_main_client = None
            db.update_system_status("esp32_main_connected", False)
            socketio.emit("system_status_change", {"esp32_main_connected": False})
    else:
        print(f"[TCP] [!]  ESP32 Main belum terhubung! IP: '{ESP32_MAIN_IP}' ? Periksa Serial Monitor Arduino.")

    # Backup HTTP jika TCP socket belum terhubung (ESP32 Port 80)
    if not sent_via_tcp and ESP32_MAIN_IP:
        threading.Thread(target=_send_http_fallback, args=(cmd_dict,), daemon=True).start()

    return sent_via_tcp

def _send_http_fallback(cmd_dict):
    """Fallback pengiriman perintah via HTTP Port 80 ESP32 jika socket belum tersambung."""
    try:
        import urllib.request
        action = cmd_dict.get("action", "")
        if action == "SET_SERVO":
            tower = cmd_dict.get("tower", 1)
            angle = cmd_dict.get("angle", 90)
            url = f"http://{ESP32_MAIN_IP}/servo?tower={tower}&angle={angle}"
            urllib.request.urlopen(url, timeout=0.3)
        elif action == "SET_RELAY":
            relay = cmd_dict.get("relay", 1)
            st = cmd_dict.get("state", 0)
            url = f"http://{ESP32_MAIN_IP}/relay?id={relay}&state={st}"
            urllib.request.urlopen(url, timeout=0.3)
        elif action == "FIRE_EXTINGUISH":
            z1 = cmd_dict.get("zone1_active", False)
            z2 = cmd_dict.get("zone2_active", False)
            a1 = cmd_dict.get("zone1_angle", 90)
            a2 = cmd_dict.get("zone2_angle", 90)
            if z1:
                urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/servo?tower=1&angle={a1}", timeout=0.3)
                urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/relay?id=1&state=1", timeout=0.3)
            else:
                urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/servo?tower=1&angle=90", timeout=0.3)
                urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/relay?id=1&state=0", timeout=0.3)
            if z2:
                urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/servo?tower=2&angle={a2}", timeout=0.3)
                urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/relay?id=2&state=1", timeout=0.3)
            else:
                urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/servo?tower=2&angle=90", timeout=0.3)
                urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/relay?id=2&state=0", timeout=0.3)
        elif action == "STANDBY":
            urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/servo?tower=1&angle=90", timeout=0.3)
            urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/servo?tower=2&angle=90", timeout=0.3)
            urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/relay?id=1&state=0", timeout=0.3)
            urllib.request.urlopen(f"http://{ESP32_MAIN_IP}/relay?id=2&state=0", timeout=0.3)
    except Exception:
        pass

# ---------------------------------------------------------------------
# KONEKSI TCP KE ESP32 MAIN ACTUATOR NODE (Port 8888)
# ---------------------------------------------------------------------
def connect_esp32_main_socket(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) # ZERO DELAY
    sock.settimeout(2.5)
    sock.connect((ip, port))
    sock.settimeout(None)
    return sock

def tcp_esp32_main_client_thread():
    """Python aktif menghubungi ESP32 Main Node di IP yang ditentukan."""
    _last_printed_ip = None
    while True:
        with state.lock:
            already_connected = (state.esp32_main_client is not None)
            current_ip = ESP32_MAIN_IP

        if not already_connected:
            if not current_ip:
                if _last_printed_ip != "":
                    print("[TCP ESP32] [...] Menunggu IP ESP32 Main... (Isi di server.py atau lewat tombol 'Ganti IP' di web)")
                    _last_printed_ip = ""
                time.sleep(2.0)
                continue

            if _last_printed_ip != current_ip:
                print(f"[TCP ESP32] Mencoba hubungkan ke ESP32 Main ({current_ip}:{ESP32_MAIN_PORT})...")
                _last_printed_ip = current_ip

            sock = None
            try:
                sock = connect_esp32_main_socket(current_ip, ESP32_MAIN_PORT)
                print(f"[TCP ESP32] [OK] TERHUBUNG KE ESP32 MAIN ({current_ip}:{ESP32_MAIN_PORT})!")

                with state.lock:
                    state.esp32_main_client = sock
                    state.esp32_main_connected = True
                db.update_system_status("esp32_main_connected", True)
                socketio.emit("system_status_change", {"esp32_main_connected": True})

                buffer = ""
                while True:
                    with state.lock:
                        if ESP32_MAIN_IP != current_ip:  # IP berubah saat runtime
                            break
                    data = sock.recv(1024)
                    if not data:
                        break
                    buffer += data.decode('utf-8', errors='ignore')
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            handle_esp32_telemetry(line)

            except ConnectionRefusedError:
                print(f"[TCP ESP32] [ERR] Koneksi ditolak ({current_ip}:{ESP32_MAIN_PORT}) ? Pastikan ESP32 sudah boot & IP benar!")
            except OSError as e:
                print(f"[TCP ESP32] [ERR] Error: {e} ? Pastikan ESP32 menyala dan IP {current_ip} benar!")
            except Exception:
                pass
            finally:
                with state.lock:
                    state.esp32_main_connected = False
                    state.esp32_main_client = None
                db.update_system_status("esp32_main_connected", False)
                socketio.emit("system_status_change", {"esp32_main_connected": False})
                if sock:
                    try: sock.close()
                    except Exception: pass

        time.sleep(1.5)

def tcp_esp32_main_backup_server_thread(host="0.0.0.0", port=8888):
    """Mendengarkan jika ESP32 Main yang menghubungi Python (dua arah)."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind((host, port))
        server_sock.listen(2)
    except Exception:
        return

    while True:
        try:
            client_sock, client_addr = server_sock.accept()
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[TCP SERVER] [OK] ESP32 Main terhubung dari {client_addr}!")
            with state.lock:
                state.esp32_main_client = client_sock
                state.esp32_main_connected = True
            db.update_system_status("esp32_main_connected", True)
            socketio.emit("system_status_change", {"esp32_main_connected": True})

            buffer = ""
            while True:
                data = client_sock.recv(1024)
                if not data:
                    break
                buffer += data.decode('utf-8', errors='ignore')
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        handle_esp32_telemetry(line)
        except Exception:
            pass
        finally:
            with state.lock:
                state.esp32_main_connected = False
                state.esp32_main_client = None
            db.update_system_status("esp32_main_connected", False)
            socketio.emit("system_status_change", {"esp32_main_connected": False})
            time.sleep(1)

def handle_esp32_telemetry(raw_json_str):
    """Memproses telemetri masuk dari ESP32 (Jarak Ultrasonik & Sensor Api Hardware)."""
    try:
        data = json.loads(raw_json_str)
        distance = data.get("distance_cm", state.ultrasonic_distance)
        flame = data.get("flame_pin", state.flame_sensor_raw)

        state.ultrasonic_distance = distance
        state.flame_sensor_raw = flame

        socketio.emit("telemetry_update", {
            "distance_cm": distance,
            "flame_sensor": flame,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })

        # ── KRITIS: Sensor Api Hardware ESP32 (GPIO 35) ──────────────────────
        # flame == 0 → Active LOW: api fisik menjangkau chip / boks ESP32!
        if flame == 0:
            now = time.time()
            # Cooldown 30 detik agar tidak spam
            if not hasattr(state, '_last_hw_danger_time'):
                state._last_hw_danger_time = 0.0
            if now - state._last_hw_danger_time > 30.0:
                state._last_hw_danger_time = now
                print("[!!!!] BAHAYA KRITIS: Sensor Api Hardware ESP32 GPIO 35 TERPICU! Api menjangkau chip!")

                # 1. Catat ke database lokal
                hw_event = db.log_event(
                    event_type="HARDWARE_DANGER",
                    description="Sensor api hardware ESP32 (GPIO 35) terpicu! Api menjangkau chip fisik.",
                    zone="Modul Fisik ESP32 Node",
                    details={"flame_pin": flame, "sensor": "GPIO35_HW_FLAME"}
                )

                # 2. Kirim alert WebSocket ke semua browser yang terhubung
                socketio.emit("hardware_danger_alert", {
                    "active": True,
                    "message": "⚠️ PERINGATAN KRITIS: Sistem sedang dalam berbahaya!",
                    "detail": "Sensor api hardware ESP32 (GPIO 35) mendeteksi kobaran api di dekat chip fisik!",
                    "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                })

                # 3. Update stats di UI
                socketio.emit("new_incident", hw_event)
                socketio.emit("stats_update", db.get_all()["counters"])

                # 4. Kirim email darurat prioritas keselamatan hardware (async)
                send_hardware_danger_email_async(
                    module_location="Modul Fisik ESP32 Node (Area Hutan)",
                    frame_bgr=None
                )

                # 5. Kirim ke Firebase Cloud
                firebase_mgr.push_incident_event_async(hw_event)
        else:
            # Api padam / normal — kirim sinyal aman ke web
            if hasattr(state, '_last_hw_danger_time') and (time.time() - state._last_hw_danger_time) < 60.0:
                socketio.emit("hardware_danger_alert", {"active": False})

        # ── Cek Jarak Ultrasonik (Radius 1.0 - 8.0 cm) ─────────────────────────
        # Filter noise: sensor HC-SR04 valid berada di range 1.0 cm - 400.0 cm
        if 1.0 <= distance <= 400.0:
            if 1.0 <= distance <= 8.0:
                # Objek terdeteksi dalam zona kritis 1-8 cm
                now = time.time()
                # Alert dipicu saat objek baru pertama masuk atau setelah cooldown 10 detik
                if not getattr(state, "obstacle_in_zone", False) or (now - state.last_ultrasonic_log_time > 10.0):
                    state.obstacle_in_zone = True
                    state.last_ultrasonic_log_time = now
                    event = db.log_event(
                        event_type="OBJEK_ULTRASONIK",
                        description=f"Objek terdeteksi dalam radius dekat: {distance:.1f} cm",
                        zone="Area Sensor Ultrasonik",
                        details={"distance_cm": distance}
                    )
                    print(f"[ULTRASONIC] ⚠️ Jarak {distance:.1f} cm! Alert LED Kuning & Buzzer.")
                    send_command_to_esp32({
                        "action": "OBSTACLE_ALERT",
                        "rgb": "YELLOW"
                    })
                    socketio.emit("new_incident", event)
                    socketio.emit("stats_update", db.get_all()["counters"])
                    firebase_mgr.push_incident_event_async(event)
                    firebase_mgr.sync_counters_async(db.get_all()["counters"])

            elif distance > 12.0:
                # Hysteresis: hanya reset jika objek telah menjauh > 12 cm
                if getattr(state, "obstacle_in_zone", False):
                    state.obstacle_in_zone = False
                    print(f"[ULTRASONIC] 🟢 Objek menjauh ({distance:.1f} cm). Mengembalikan LED ke Hijau.")
                    send_command_to_esp32({
                        "action": "OBSTACLE_CLEAR"
                    })
                    socketio.emit("obstacle_clear", {"distance_cm": distance})

        # ── Sinkronisasi Telemetri ke Firebase Cloud (Non-blocking) ─────────
        firebase_mgr.sync_telemetry_async({
            "distance_cm": distance,
            "flame_pin": flame,
            "flame_hw_danger": (flame == 0),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    except Exception:
        pass

# ---------------------------------------------------------------------
# KONEKSI TCP KE ESP32-CAM (STREAM VIDEO PORT 80)
# ---------------------------------------------------------------------
def connect_cam_tcp(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect((ip, port))
    sock.settimeout(10)
    return sock

def recv_exact_cam(sock, n):
    buf = bytearray(n)
    view = memoryview(buf)
    pos = 0
    while pos < n:
        try:
            bytes_read = sock.recv_into(view[pos:], n - pos)
            if not bytes_read:
                return None
            pos += bytes_read
        except Exception:
            return None
    return bytes(buf)

def tcp_esp32_cam_client_thread():
    """Membaca stream TCP dari ESP32-CAM (persis seperti di CAM BERHASIL)."""
    _last_printed_ip = None
    while True:
        current_cam_ip = ESP32_CAM_IP
        if not current_cam_ip:
            if _last_printed_ip != "":
                print("[TCP CAM] [...] Menunggu IP ESP32-CAM... (isi di server.py atau 'Ganti IP' di web)")
                _last_printed_ip = ""
            time.sleep(2.0)
            continue

        sock = None
        try:
            if _last_printed_ip != current_cam_ip:
                print(f"[TCP CAM] Mencoba hubungkan ke ESP32-CAM ({current_cam_ip}:{ESP32_CAM_PORT})...")
                _last_printed_ip = current_cam_ip
            sock = connect_cam_tcp(current_cam_ip, ESP32_CAM_PORT)
            print(f"[TCP CAM] [OK] TERHUBUNG KE ESP32-CAM ({current_cam_ip}:{ESP32_CAM_PORT})!")

            state.esp32_cam_connected = True
            db.update_system_status("esp32_cam_connected", True)
            socketio.emit("system_status_change", {"esp32_cam_connected": True})

            while True:
                # 1. Baca panjang frame (4 byte)
                len_bytes = recv_exact_cam(sock, 4)
                if not len_bytes:
                    break

                frame_len = (len_bytes[0] << 24) | (len_bytes[1] << 16) | (len_bytes[2] << 8) | len_bytes[3]
                if frame_len == 0 or frame_len > 1_000_000:
                    continue

                # 2. Baca data JPEG
                jpeg_data = recv_exact_cam(sock, frame_len)
                if not jpeg_data or len(jpeg_data) != frame_len:
                    break

                # 3. Decode frame
                np_arr = np.frombuffer(jpeg_data, np.uint8)
                img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if img is not None:
                    with state.lock:
                        state.current_frame = img

        except Exception:
            pass
        finally:
            state.esp32_cam_connected = False
            db.update_system_status("esp32_cam_connected", False)
            socketio.emit("system_status_change", {"esp32_cam_connected": False})
            if sock:
                try: sock.close()
                except Exception: pass
            time.sleep(1.0)

# ---------------------------------------------------------------------
# VIDEO STREAM & AI PROCESSING LOOP
# ---------------------------------------------------------------------
def video_capture_and_ai_loop():
    """Loop inferensi AI Vision continuous."""
    while True:
        frame = None
        with state.lock:
            if state.current_frame is not None:
                frame = state.current_frame.copy()

        # Jika ESP32-CAM belum terhubung, tampilkan frame panduan (TANPA mencoba buka webcam lokal)
        if frame is None:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            frame[:] = (20, 30, 25)
            cam_ip = ESP32_CAM_IP or "belum diisi"
            cv2.putText(frame, "Menunggu ESP32-CAM...", (140, 210),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 160), 2)
            cv2.putText(frame, f"IP: {cam_ip}:80", (200, 255),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 180, 120), 1)
            cv2.putText(frame, "Pastikan laptop terhubung ke WiFi ESP32", (70, 300),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 180, 100), 1)

        # Jalankan AI Detection & Poligon 4 Titik
        annotated_frame, detections = ai_engine.detect(frame)

        with state.lock:
            state.annotated_frame = annotated_frame
            state.last_detections = detections

        # Proses pemadaman api otomatis
        process_ai_events(detections)

        time.sleep(0.035)

def process_ai_events(detections):
    """Menangani logika deteksi api, pohon tumbang, pohon ditebang, & aktuasi otomatis dengan jeda pembaruan 2 detik."""
    now = time.time()
    fire_in_zone1 = False
    fire_in_zone2 = False
    raw_angle_zone1 = None
    raw_angle_zone2 = None

    for det in detections:
        label   = str(det.get("label", "")).strip()
        cls_id  = det.get("class_id", -1)
        zone    = det.get("zone", 0)
        angle   = det.get("angle", 90)
        conf    = det.get("confidence", 0.0)
        zone_label = f"Area {zone}" if zone in [1, 2] else "Area Pantau Hutan"

        label_low = label.lower()

        # ── Tentukan kategori berdasarkan LABEL & CLASS ID model ──
        # 1. API (Prioritas Tertinggi)
        is_api = ("api" in label_low or "fire" in label_low or cls_id == 2)

        # 2. POHON DITEBANG / ILLEGAL LOGGING (Prioritas Keamanan Kedua)
        is_ditebang = (
            not is_api and (
                "ditebang" in label_low or "tebang" in label_low or
                "illegal" in label_low or "logging" in label_low or
                "cut" in label_low or cls_id == 0
            )
        )

        # 3. POHON JATUH ALAMI (Hanya jika BUKAN pohon ditebang)
        is_jatuh = (
            not is_api and not is_ditebang and (
                "jatuh" in label_low or "alami" in label_low or
                "tumbang" in label_low or "fallen" in label_low or
                "natural" in label_low or cls_id == 1
            )
        )

        # ── A. API TERDETEKSI ──────────────────────────────────────────────────
        if is_api:
            if zone == 1:
                fire_in_zone1 = True
                raw_angle_zone1 = angle
            elif zone == 2:
                fire_in_zone2 = True
                raw_angle_zone2 = angle

            if now - state.last_fire_log_time > 5.0:
                state.last_fire_log_time = now
                event = db.log_event(
                    event_type="API_TERDETEKSI",
                    description=f"Api terdeteksi di {zone_label} (Angle: {angle}°, Conf: {int(conf*100)}%)",
                    zone=zone_label,
                    details=det
                )
                print(f"🔥 [FIRE ALERT] Api di {zone_label}! Sudut Target: {angle}° label='{label}' cls_id={cls_id}")
                socketio.emit("new_incident", event)
                socketio.emit("stats_update", db.get_all()["counters"])
                firebase_mgr.push_incident_event_async(event)
                firebase_mgr.sync_counters_async(db.get_all()["counters"])

        # ── B. POHON DITEBANG / ILLEGAL LOGGING ───────────────────────────────
        elif is_ditebang:
            if now - state.last_cut_log_time > 20.0:
                state.last_cut_log_time = now
                event = db.log_event(
                    event_type="POHON_DITEBANG",
                    description=f"Pembalakan liar / pohon ditebang di {zone_label} (Conf: {int(conf*100)}%)",
                    zone=zone_label,
                    details=det
                )
                print(f"🪓 [ILLEGAL LOGGING] {zone_label} (Akurasi: {int(conf*100)}%) label='{label}' cls_id={cls_id}")
                socketio.emit("new_incident", event)
                socketio.emit("stats_update", db.get_all()["counters"])
                firebase_mgr.push_incident_event_async(event)
                firebase_mgr.sync_counters_async(db.get_all()["counters"])

                # Kirim email hanya jika akurasi meyakinkan (>= 55%) agar bebas dari false alarm
                if conf >= 0.55:
                    with state.lock:
                        snap_frame = state.current_frame.copy() if state.current_frame is not None else None
                    send_illegal_logging_email_async(zone_label, conf, snap_frame)

        # ── C. POHON JATUH ALAMI ──────────────────────────────────────────────
        elif is_jatuh:
            if now - state.last_fallen_log_time > 20.0:
                state.last_fallen_log_time = now
                event = db.log_event(
                    event_type="POHON_JATUH_ALAMI",
                    description=f"Pohon tumbang alami di {zone_label} (Conf: {int(conf*100)}%)",
                    zone=zone_label,
                    details=det
                )
                print(f"🍃 [POHON JATUH] {zone_label} (Akurasi: {int(conf*100)}%) label='{label}' cls_id={cls_id}")
                socketio.emit("new_incident", event)
                socketio.emit("stats_update", db.get_all()["counters"])
                firebase_mgr.push_incident_event_async(event)
                firebase_mgr.sync_counters_async(db.get_all()["counters"])

                # Kirim email hanya jika akurasi meyakinkan (>= 55%) agar bebas dari false alarm
                if conf >= 0.55:
                    with state.lock:
                        snap_frame = state.current_frame.copy() if state.current_frame is not None else None
                    send_tree_fall_email_async(zone_label, conf, snap_frame)

    # ── LOGIKA KUNCI SUDUT AWAL & JEDA PEMBARUAN 2 DETIK (STABILITAS & ANTI-JITTER) ──
    ANGLE_UPDATE_INTERVAL = 2.0  # Jeda 2 detik sebelum sudut servo diperbarui saat api berpindah
    ANGLE_DEADBAND = 5           # Minimal perpindahan 5 derajat agar servo tidak getar/jitter
    FIRE_HOLD_SECONDS = 1.5      # Debounce api 1.5 detik agar status tidak flicker saat frame drop

    # Servo 1 (Area 1)
    if fire_in_zone1 and raw_angle_zone1 is not None:
        state.last_fire_time_1 = now
        if not state.is_fire_locked_1:
            state.is_fire_locked_1 = True
            state.locked_angle_1 = raw_angle_zone1
            state.last_angle_update_1 = now
            print(f"🎯 [TARGET LOCK S1] Api di Area 1 -> Kunci Sudut: {state.locked_angle_1}°")
        else:
            # Sudah terkunci: Cek apakah sudah lewat 2.0 detik DAN berpindah cukup jauh (>= 5°)
            if (now - state.last_angle_update_1 >= ANGLE_UPDATE_INTERVAL):
                if abs(raw_angle_zone1 - state.locked_angle_1) >= ANGLE_DEADBAND:
                    print(f"🔄 [TARGET UPDATE S1] Api berpindah ({state.locked_angle_1}° -> {raw_angle_zone1}°) -> Update setelah jeda 2 detik")
                    state.locked_angle_1 = raw_angle_zone1
                    state.last_angle_update_1 = now

    # Servo 2 (Area 2)
    if fire_in_zone2 and raw_angle_zone2 is not None:
        state.last_fire_time_2 = now
        if not state.is_fire_locked_2:
            state.is_fire_locked_2 = True
            state.locked_angle_2 = raw_angle_zone2
            state.last_angle_update_2 = now
            print(f"🎯 [TARGET LOCK S2] Api di Area 2 -> Kunci Sudut: {state.locked_angle_2}°")
        else:
            # Sudah terkunci: Cek apakah sudah lewat 2.0 detik DAN berpindah cukup jauh (>= 5°)
            if (now - state.last_angle_update_2 >= ANGLE_UPDATE_INTERVAL):
                if abs(raw_angle_zone2 - state.locked_angle_2) >= ANGLE_DEADBAND:
                    print(f"🔄 [TARGET UPDATE S2] Api berpindah ({state.locked_angle_2}° -> {raw_angle_zone2}°) -> Update setelah jeda 2 detik")
                    state.locked_angle_2 = raw_angle_zone2
                    state.last_angle_update_2 = now

    # Debounce status api (tahan 1.5 detik setelah deteksi terakhir)
    has_fire_1 = (now - state.last_fire_time_1) < FIRE_HOLD_SECONDS
    has_fire_2 = (now - state.last_fire_time_2) < FIRE_HOLD_SECONDS

    if not has_fire_1:
        state.is_fire_locked_1 = False
        state.locked_angle_1 = 90

    if not has_fire_2:
        state.is_fire_locked_2 = False
        state.locked_angle_2 = 90

    # ── EKSEKUSI PEMADAMAN API OTOMATIS & PENGIRIMAN PERINTAH KE ESP32 ──
    if has_fire_1 or has_fire_2:
        state.auto_fire_active = True
        state.buzzer_status = True
        state.rgb_color = "BLINK_RED_YELLOW"
        state.relay1_status = has_fire_1
        state.relay2_status = has_fire_2
        state.tower1_servo = state.locked_angle_1 if has_fire_1 else 90
        state.tower2_servo = state.locked_angle_2 if has_fire_2 else 90

        # Cek durasi kebakaran untuk dispatch email Damkar (> 15 detik)
        if state.fire_start_time is None:
            state.fire_start_time = now
            state.fire_email_dispatched = False
        elif (now - state.fire_start_time >= 15.0) and not state.fire_email_dispatched:
            state.fire_email_dispatched = True
            fire_area = "Area 1 & 2" if (has_fire_1 and has_fire_2) else ("Area 1" if has_fire_1 else "Area 2")
            fire_ang = state.tower1_servo if has_fire_1 else state.tower2_servo
            with state.lock:
                snap_frame = state.current_frame.copy() if state.current_frame is not None else None
            print("🚨 [DAMKAR DISPATCH] Api telah berkobar > 15 detik! Mengirim email darurat ke Damkar...")
            send_fire_alert_email_async(
                area_name=fire_area,
                duration_sec=now - state.fire_start_time,
                angle_info=f"Servo Nozzle: {fire_ang}°",
                frame_bgr=snap_frame
            )

        # Cek apakah perintah perlu dikirim ke ESP32 (Hanya saat status aktif berubah atau sudut berpindah >= ANGLE_DEADBAND)
        should_send = (
            (has_fire_1 != state.last_sent_z1_active) or
            (has_fire_2 != state.last_sent_z2_active) or
            (has_fire_1 and abs(state.locked_angle_1 - state.last_sent_angle_1) >= ANGLE_DEADBAND) or
            (has_fire_2 and abs(state.locked_angle_2 - state.last_sent_angle_2) >= ANGLE_DEADBAND)
        )

        if should_send and (now - state.last_cmd_time >= 0.25):
            state.last_cmd_time = now
            state.last_sent_z1_active = has_fire_1
            state.last_sent_z2_active = has_fire_2
            state.last_sent_angle_1 = state.tower1_servo
            state.last_sent_angle_2 = state.tower2_servo

            cmd = {
                "action": "FIRE_EXTINGUISH",
                "zone1_active": has_fire_1,
                "zone1_angle": state.tower1_servo,
                "relay1": 1 if has_fire_1 else 0,
                "zone2_active": has_fire_2,
                "zone2_angle": state.tower2_servo,
                "relay2": 1 if has_fire_2 else 0,
                "buzzer": 1,
                "rgb": "BLINK_RED_YELLOW"
            }
            send_command_to_esp32(cmd)
            socketio.emit("actuator_status_update", {
                "tower1_servo": state.tower1_servo,
                "tower2_servo": state.tower2_servo,
                "relay1": state.relay1_status,
                "relay2": state.relay2_status,
                "buzzer": True,
                "rgb_color": "BLINK_RED_YELLOW"
            })
    else:
        # Api padam atau aman
        state.fire_start_time = None
        state.fire_email_dispatched = False

        if state.auto_fire_active:
            state.auto_fire_active = False
            state.relay1_status = False
            state.relay2_status = False
            state.buzzer_status = False
            state.tower1_servo = 90
            state.tower2_servo = 90
            state.rgb_color = "GREEN"
            state.last_sent_z1_active = False
            state.last_sent_z2_active = False
            state.last_sent_angle_1 = 90
            state.last_sent_angle_2 = 90

            cmd = {
                "action": "STANDBY",
                "zone1_angle": 90,
                "zone2_angle": 90,
                "relay1": 0,
                "relay2": 0,
                "buzzer": 0,
                "rgb": "GREEN"
            }
            send_command_to_esp32(cmd)
            socketio.emit("actuator_status_update", {
                "tower1_servo": 90,
                "tower2_servo": 90,
                "relay1": False,
                "relay2": False,
                "buzzer": False,
                "rgb_color": "GREEN"
            })

# ---------------------------------------------------------------------
# WEBSOCKET INSTANT CONTROL HANDLERS (RESPON INSTAN < 1-2 MS)
# ---------------------------------------------------------------------
@socketio.on("manual_control")
def handle_manual_control(data):
    """Menerima aksi dari Web via WebSocket (Langsung gerak seketika!)."""
    action = data.get("action", "")

    if action == "SET_SERVO":
        tower = data.get("tower", 1)
        angle = int(data.get("angle", 90))
        if tower == 1:
            state.tower1_servo = angle
        else:
            state.tower2_servo = angle
        send_command_to_esp32({"action": "SET_SERVO", "tower": tower, "angle": angle})
        emit("actuator_status_update", {
            "tower1_servo": state.tower1_servo,
            "tower2_servo": state.tower2_servo,
            "relay1": state.relay1_status,
            "relay2": state.relay2_status
        }, broadcast=True)

    elif action == "TOGGLE_RELAY":
        relay_id = data.get("relay", 1)
        status = bool(data.get("status", False))
        if relay_id == 1:
            state.relay1_status = status
        else:
            state.relay2_status = status
        send_command_to_esp32({"action": "SET_RELAY", "relay": relay_id, "state": 1 if status else 0})
        emit("actuator_status_update", {
            "tower1_servo": state.tower1_servo,
            "tower2_servo": state.tower2_servo,
            "relay1": state.relay1_status,
            "relay2": state.relay2_status
        }, broadcast=True)

    elif action == "TEST_BUZZER":
        send_command_to_esp32({"action": "BEEP"})

    elif action == "SET_RGB":
        color = data.get("color", "GREEN")
        state.rgb_color = color
        send_command_to_esp32({"action": "SET_RGB", "color": color})

# ---------------------------------------------------------------------
# FLASK WEB DASHBOARD & REST APIS
# ---------------------------------------------------------------------
@app.route("/")
def index():
    db_data = db.get_all()
    local_ip = get_local_ip()
    net = {
        "esp32_main_ip": ESP32_MAIN_IP,
        "esp32_cam_ip": ESP32_CAM_IP,
        "local_ip": local_ip,
        "wifi_url": f"http://{local_ip}:5000"
    }
    return render_template("index.html", data=db_data, net=net, local_ip=local_ip, wifi_url=f"http://{local_ip}:5000")

def generate_video_stream():
    """Generates MJPEG video stream."""
    while True:
        with state.lock:
            frame = state.annotated_frame
            if frame is None:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "Menunggu Kamera...", (200, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                continue
            frame_bytes = jpeg.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.035)

@app.route("/video_feed")
def video_feed():
    return Response(generate_video_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/database", methods=["GET"])
def api_get_database():
    return jsonify(db.get_all())

@app.route("/api/database/filter", methods=["GET"])
def api_filter_database():
    """Memfilter data kejadian berdasarkan tanggal (YYYY-MM-DD), tipe event, atau kata kunci pencarian."""
    date_query = request.args.get("date", "").strip()
    event_type = request.args.get("type", "").strip()
    search_kw = request.args.get("search", "").strip()
    result = db.filter_events(date_query=date_query, event_type=event_type, search_keyword=search_kw)
    return jsonify(result)

@app.route("/api/database/export_csv", methods=["GET"])
def api_export_database_csv():
    """Mendownload seluruh data riwayat kejadian dalam format berkas CSV untuk Microsoft Excel / Spreadsheet."""
    try:
        csv_data = db.export_events_csv()
        # Berikan prefix UTF-8 BOM agar Excel menampilkan derajat (°) dan aksen dengan sempurna
        csv_bytes = ("\ufeff" + csv_data).encode("utf-8-sig")
        filename = f"forest_database_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype="text/csv; charset=utf-8",
            as_attachment=True,
            download_name=filename,
            max_age=0
        )
    except Exception as e:
        print(f"[EXPORT CSV ERROR] {e}")
        csv_data = db.export_events_csv()
        csv_bytes = ("\ufeff" + csv_data).encode("utf-8-sig")
        filename = f"forest_database_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        resp = Response(csv_bytes, mimetype="text/csv; charset=utf-8")
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        resp.headers["Content-Length"] = str(len(csv_bytes))
        return resp

@app.route("/api/network/local_ip", methods=["GET"])
def api_get_local_ip():
    """Mengembalikan alamat IP WiFi komputer saat ini untuk akses mudah dari perangkat lain."""
    local_ip = get_local_ip()
    return jsonify({
        "local_ip": local_ip,
        "wifi_url": f"http://{local_ip}:5000",
        "port": 5000
    })

@app.route("/api/zones", methods=["GET", "POST"])
def api_zones():
    """Membaca dan menyimpan 4 titik penentu khusus untuk Area 1 dan Area 2."""
    if request.method == "POST":
        data = request.json or {}
        if "area1" in data and "area2" in data:
            ai_engine.save_zones_config(data)
            socketio.emit("zones_updated", ai_engine.zones)
            return jsonify({"status": "success", "message": "Titik area berhasil disimpan", "zones": ai_engine.zones})
        return jsonify({"status": "error", "message": "Format data area tidak valid"}), 400
    return jsonify(ai_engine.zones)

@app.route("/api/network", methods=["GET", "POST"])
def api_network():
    """Baca / perbarui IP ESP32 Main & ESP32-CAM secara langsung tanpa restart server."""
    global ESP32_MAIN_IP, ESP32_CAM_IP

    if request.method == "POST":
        data = request.json or {}
        new_main_ip = data.get("esp32_main_ip", "").strip()
        new_cam_ip  = data.get("esp32_cam_ip",  "").strip()

        changed_main = (new_main_ip and new_main_ip != ESP32_MAIN_IP)
        changed_cam  = (new_cam_ip  and new_cam_ip  != ESP32_CAM_IP)

        if changed_main:
            print(f"[NETWORK] IP ESP32 Main diperbarui: {ESP32_MAIN_IP!r} -> {new_main_ip!r}")
            # Putus koneksi lama agar thread reconnect otomatis ke IP baru
            with state.lock:
                old = state.esp32_main_client
                state.esp32_main_client = None
                state.esp32_main_connected = False
            if old:
                try: old.close()
                except Exception: pass
            ESP32_MAIN_IP = new_main_ip

        if changed_cam:
            print(f"[NETWORK] IP ESP32-CAM diperbarui: {ESP32_CAM_IP!r} -> {new_cam_ip!r}")
            ESP32_CAM_IP = new_cam_ip

        if changed_main or changed_cam:
            try:
                save_network_config(ESP32_MAIN_IP, ESP32_CAM_IP, ESP32_MAIN_PORT, ESP32_CAM_PORT)
            except Exception:
                pass

        return jsonify({
            "status": "success",
            "esp32_main_ip": ESP32_MAIN_IP,
            "esp32_cam_ip":  ESP32_CAM_IP,
        })

    # GET -> kembalikan IP saat ini
    return jsonify({
        "esp32_main_ip": ESP32_MAIN_IP,
        "esp32_cam_ip":  ESP32_CAM_IP,
    })

@app.route("/api/telemetry", methods=["GET"])
def api_get_telemetry():
    return jsonify({
        "ultrasonic_distance": state.ultrasonic_distance,
        "flame_sensor": state.flame_sensor_raw,
        "tower1_servo": state.tower1_servo,
        "tower2_servo": state.tower2_servo,
        "relay1": state.relay1_status,
        "relay2": state.relay2_status,
        "buzzer": state.buzzer_status,
        "rgb_color": state.rgb_color,
        "esp32_main_connected": state.esp32_main_connected,
        "esp32_cam_connected": state.esp32_cam_connected,
        "detections": state.last_detections
    })

@app.route("/api/control", methods=["POST"])
def api_manual_control():
    """REST API kontrol aktuator (bisa dipanggil dari web, curl, atau HP)."""
    data = request.json or {}
    action = data.get("action", "")
    
    if action == "SET_SERVO":
        tower = int(data.get("tower", 1))
        angle = int(data.get("angle", 90))
        if tower == 1:
            state.tower1_servo = angle
        else:
            state.tower2_servo = angle
        send_command_to_esp32({"action": "SET_SERVO", "tower": tower, "angle": angle})
        socketio.emit("actuator_status_update", {
            "tower1_servo": state.tower1_servo,
            "tower2_servo": state.tower2_servo,
            "relay1": state.relay1_status,
            "relay2": state.relay2_status
        })
        
    elif action == "TOGGLE_RELAY":
        relay_id = int(data.get("relay", 1))
        status = bool(data.get("status", False))
        if relay_id == 1:
            state.relay1_status = status
        else:
            state.relay2_status = status
        send_command_to_esp32({"action": "SET_RELAY", "relay": relay_id, "state": 1 if status else 0})
        socketio.emit("actuator_status_update", {
            "tower1_servo": state.tower1_servo,
            "tower2_servo": state.tower2_servo,
            "relay1": state.relay1_status,
            "relay2": state.relay2_status
        })

    elif action == "TEST_BUZZER":
        send_command_to_esp32({"action": "BEEP"})

    elif action == "SET_RGB":
        color = data.get("color", "GREEN")
        state.rgb_color = color
        send_command_to_esp32({"action": "SET_RGB", "color": color})
        socketio.emit("actuator_status_update", {"rgb_color": color})

    elif action == "CAPTURE_SNAPSHOT":
        with state.lock:
            if state.current_frame is not None:
                os.makedirs("dataset/images", exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = os.path.join("dataset/images", f"snapshot_{timestamp}.jpg")
                cv2.imwrite(save_path, state.current_frame)
                return jsonify({"status": "success", "file": save_path})
            else:
                return jsonify({"status": "error", "message": "No active camera frame"}), 400

    return jsonify({"status": "success", "action": action})

# ---------------------------------------------------------------------
# INITIALIZATION & MAIN ENTRY
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Start thread klien koneksi ke ESP32 Main Node
    tcp_main_client_thread = threading.Thread(target=tcp_esp32_main_client_thread, daemon=True)
    tcp_main_client_thread.start()

    # 1b. Start thread backup server jika ESP32 yang masuk
    tcp_main_srv_thread = threading.Thread(target=tcp_esp32_main_backup_server_thread, daemon=True)
    tcp_main_srv_thread.start()

    # 2. Start TCP Client thread -> konek ke ESP32-CAM (Port 80)
    tcp_cam_thread = threading.Thread(target=tcp_esp32_cam_client_thread, daemon=True)
    tcp_cam_thread.start()

    # 3. Start Video Stream & AI Processing thread
    ai_thread = threading.Thread(target=video_capture_and_ai_loop, daemon=True)
    ai_thread.start()

    # 4. Start Firebase Periodic Sync thread (sinkronisasi lokal → cloud setiap 10 detik)
    def _firebase_periodic_sync_thread():
        """Background thread: menjaga Firebase selalu sinkron dengan database lokal."""
        import time as _time
        _time.sleep(3.0)  # Tunggu server init selesai
        while True:
            try:
                all_data = db.get_all()
                counters  = all_data.get("counters", {})
                events    = all_data.get("events", [])
                sys_state = all_data.get("system_status", {})

                # Selalu kirim counters (agar web & Firebase selalu sama)
                firebase_mgr.sync_counters_async(counters)

                # Kirim status sistem (koneksi ESP32, dsb)
                firebase_mgr.sync_system_status_async({
                    **sys_state,
                    "esp32_cam_connected":  state.esp32_cam_connected,
                    "esp32_main_connected": state.esp32_main_connected,
                    "last_sync": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

                # Kirim telemetri sensor terkini
                firebase_mgr.sync_telemetry_async({
                    "distance_cm":   state.ultrasonic_distance,
                    "flame_pin":     state.flame_sensor_raw,
                    "flame_hw_danger": (state.flame_sensor_raw == 0),
                    "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

                # Kirim insiden terakhir (jika ada)
                if events:
                    url = firebase_mgr._build_url("forest_protection/last_incident")
                    if url:
                        import requests as _req
                        try:
                            _req.put(url, json=events[0], timeout=3.0)
                        except Exception:
                            pass

            except Exception:
                pass  # Jangan crash walau Firebase gagal

            _time.sleep(10.0)  # Interval 10 detik

    firebase_sync_thread = threading.Thread(target=_firebase_periodic_sync_thread, daemon=True)
    firebase_sync_thread.start()

    local_wifi_ip = get_local_ip()
    print("=" * 72)
    print(" 🌲 [FOREST] AIoT Forest Protection Central Server & Web Hub")
    print("=" * 72)
    print(" 💻 Akses Laptop Ini    : http://localhost:5000")
    print(f" 📱 Akses HP / WiFi     : http://{local_wifi_ip}:5000")
    print("    (Device apa pun di WiFi yang sama dapat membuka link di atas!)")
    print("-" * 72)
    if ESP32_MAIN_IP:
        print(f" Target ESP32 Main (Actuator) : {ESP32_MAIN_IP}:{ESP32_MAIN_PORT}")
    else:
        print(" Target ESP32 Main (Actuator) : [!] BELUM DIISI -> buka web -> 'Ganti IP'")
    if ESP32_CAM_IP:
        print(f" Target ESP32-CAM (Video)     : {ESP32_CAM_IP}:{ESP32_CAM_PORT}")
    else:
        print(" Target ESP32-CAM (Video)     : [!] BELUM DIISI -> buka web -> 'Ganti IP'")
    print("-" * 72)
    print(" 💡 Database Lokal Persisten: data/forest_database.json")
    print(" 📧 Notifikasi Email Terpadu: Damkar | Pohon Jatuh | Pohon Ditebang | Hardware Danger")
    if firebase_mgr.is_active():
        print(f" ☁️  Firebase Cloud DB      : {firebase_mgr.config.get('database_url', 'N/A')}")
    else:
        print(" ☁️  Firebase Cloud DB      : [!] Nonaktif - isi database_url di data/firebase_config.json")
    print("=" * 72)

    # Sinkronisasi snapshot awal ke Firebase (data existing dari database lokal)
    def _firebase_initial_sync():
        import time
        time.sleep(2.0)  # Tunggu server siap dulu
        try:
            all_data = db.get_all()
            counters = all_data.get("counters", {})
            events = all_data.get("events", [])

            # Kirim counters
            firebase_mgr.sync_counters_async(counters)

            # Kirim status sistem awal
            firebase_mgr.sync_system_status_async({
                "server_started": True,
                "startup_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "esp32_cam_connected": False,
                "esp32_main_connected": False
            })

            # Kirim insiden terakhir jika ada
            if events:
                firebase_mgr.push_incident_event_async(events[0])

            print("[FIREBASE] ☁️  Snapshot awal database lokal berhasil dikirim ke Firebase Cloud!")
        except Exception as e:
            print(f"[FIREBASE] [!] Gagal sync awal: {e}")

    threading.Thread(target=_firebase_initial_sync, daemon=True).start()

    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
