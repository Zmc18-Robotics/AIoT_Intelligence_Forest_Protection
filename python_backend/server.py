"""
=======================================================================
 AIoT Intelligence Forest Protection - Central Server & TCP/IP Hub
=======================================================================
Features:
  - ESP32-CAM Stream Receiver & AI Vision Inference (YOLO / Vision)
  - ESP32 Actuator Node TCP/IP Socket Server (Port 8888)
  - REST & WebSocket APIs for Live Web Dashboard
  - Automated Fire Extinguishing Logic (Zone 1 / Zone 2 targeting)
  - Ultrasonic Sweep Distance (1-8cm) Incursion Detection & Database Logging
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
from flask import Flask, render_template, Response, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS

from database_manager import DatabaseManager
from ai_detector import ForestAIDetector

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "aiot-forest-protection-2026"
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── KONFIGURASI NETWORK ──────────────────────────────────────────────
# Ganti dengan IP ESP32-CAM (lihat Serial Monitor saat ESP32-CAM boot)
ESP32_CAM_IP   = "192.168.1.101"  # ← IP ESP32-CAM
ESP32_CAM_PORT = 80               # Port 80 (TCP Server ESP32-CAM)
# ─────────────────────────────────────────────────────────────────────

# Initialize modules
db = DatabaseManager(db_path="data/forest_database.json")
ai_engine = ForestAIDetector(conf_thresh=0.45)

# Global runtime state
class SystemState:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_frame = None
        self.annotated_frame = None
        self.last_detections = []
        
        # Telemetry from ESP32
        self.ultrasonic_distance = 100.0 # cm
        self.flame_sensor_raw = 1 # 1 = normal, 0 = flame detected
        
        # Actuator status on ESP32 (Exactly 2 Servos)
        self.tower1_servo = 90
        self.tower2_servo = 90
        self.relay1_status = False
        self.relay2_status = False
        self.buzzer_status = False
        self.rgb_color = "GREEN"
        
        # Network clients
        self.esp32_main_client = None
        self.esp32_cam_connected = False
        self.esp32_main_connected = False
        
        # Cooldown trackers to prevent logging spam
        self.last_fire_log_time = 0
        self.last_fallen_log_time = 0
        self.last_cut_log_time = 0
        self.last_ultrasonic_log_time = 0

state = SystemState()

# ---------------------------------------------------------------------
# TCP SERVER FOR ESP32 MAIN ACTUATOR NODE (Port 8888)
# ---------------------------------------------------------------------
def send_command_to_esp32(cmd_dict):
    """Send JSON command string over TCP to ESP32 Main."""
    if state.esp32_main_client:
        try:
            msg = json.dumps(cmd_dict) + "\n"
            state.esp32_main_client.sendall(msg.encode('utf-8'))
            return True
        except Exception as e:
            print(f"[TCP ERROR] Failed to send command to ESP32: {e}")
            state.esp32_main_connected = False
            state.esp32_main_client = None
            db.update_system_status("esp32_main_connected", False)
    return False

def tcp_esp32_server_thread(host="0.0.0.0", port=8888):
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_sock.bind((host, port))
        server_sock.listen(5)
        print(f"[TCP SERVER] Listening for ESP32 Main on {host}:{port}")
    except Exception as e:
        print(f"[TCP SERVER ERROR] Could not bind port {port}: {e}")
        return

    while True:
        try:
            client_sock, client_addr = server_sock.accept()
            print(f"[TCP SERVER] ESP32 Main Node connected from {client_addr}")
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

        except Exception as e:
            print(f"[TCP SERVER] ESP32 client disconnected: {e}")
        finally:
            state.esp32_main_connected = False
            state.esp32_main_client = None
            db.update_system_status("esp32_main_connected", False)
            socketio.emit("system_status_change", {"esp32_main_connected": False})
            time.sleep(1)

def handle_esp32_telemetry(raw_json_str):
    """Parses incoming telemetry from ESP32 Main (Ultrasonic Distance & Flame Sensor)."""
    try:
        data = json.loads(raw_json_str)
        distance = data.get("distance_cm", state.ultrasonic_distance)
        flame = data.get("flame_pin", state.flame_sensor_raw)

        state.ultrasonic_distance = distance
        state.flame_sensor_raw = flame

        # Emit live telemetry to web dashboard
        socketio.emit("telemetry_update", {
            "distance_cm": distance,
            "flame_sensor": flame,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })

        # CHECK ULTRASONIC RANGE (1 - 8 cm threshold)
        if 1.0 <= distance <= 8.0:
            now = time.time()
            if now - state.last_ultrasonic_log_time > 3.0: # 3 second debounce
                state.last_ultrasonic_log_time = now
                event = db.log_event(
                    event_type="OBJEK_ULTRASONIK",
                    description=f"Objek terdeteksi dalam radius dekat: {distance:.1f} cm",
                    zone="Area Sensor Ultrasonik",
                    details={"distance_cm": distance}
                )
                print(f"🚨 [ULTRASONIC INTRUDER] Distance: {distance:.1f} cm! Alerting LED & Buzzer.")
                
                # Command ESP32 to turn on warning RGB LED and sound alert
                send_command_to_esp32({
                    "action": "OBSTACLE_ALERT",
                    "rgb": "YELLOW",
                    "buzzer_beep": 2
                })
                socketio.emit("new_incident", event)
                socketio.emit("stats_update", db.get_all()["counters"])

    except Exception as e:
        print(f"[TELEMETRY PARSE ERROR] Invalid JSON from ESP32: {raw_json_str} ({e})")

# ---------------------------------------------------------------------
# TCP SERVER FOR ESP32-CAM VIDEO STREAM (Port 8889)
# ---------------------------------------------------------------------
# TCP CLIENT FOR ESP32-CAM VIDEO STREAM (Port 80 - CAM BERHASIL)
# ---------------------------------------------------------------------
def connect_cam_tcp(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((ip, port))
    sock.settimeout(15)
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
        except socket.timeout:
            return None
        except Exception:
            return None
    return bytes(buf)

def tcp_esp32_cam_client_thread():
    """Membaca stream TCP dari ESP32-CAM (Port 80) persis seperti di CAM.py."""
    while True:
        sock = None
        try:
            print(f"[TCP CAM] Menghubungkan ke ESP32-CAM di {ESP32_CAM_IP}:{ESP32_CAM_PORT}...")
            sock = connect_cam_tcp(ESP32_CAM_IP, ESP32_CAM_PORT)
            print(f"[TCP CAM] Terhubung ke ESP32-CAM ({ESP32_CAM_IP}:{ESP32_CAM_PORT})!")

            state.esp32_cam_connected = True
            db.update_system_status("esp32_cam_connected", True)
            socketio.emit("system_status_change", {"esp32_cam_connected": True})

            while True:
                # 1. Baca panjang frame (4 byte)
                len_bytes = recv_exact_cam(sock, 4)
                if not len_bytes:
                    print("[TCP CAM] Terputus atau gagal membaca panjang frame.")
                    break

                frame_len = (len_bytes[0] << 24) | (len_bytes[1] << 16) | (len_bytes[2] << 8) | len_bytes[3]
                if frame_len == 0 or frame_len > 1_000_000:
                    continue

                # 2. Baca data gambar JPEG
                jpeg_data = recv_exact_cam(sock, frame_len)
                if not jpeg_data or len(jpeg_data) != frame_len:
                    print("[TCP CAM] Data frame tidak lengkap.")
                    break

                # 3. Decode frame
                np_arr = np.frombuffer(jpeg_data, np.uint8)
                img    = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if img is not None:
                    with state.lock:
                        state.current_frame = img

        except Exception as e:
            print(f"[TCP CAM] Error koneksi ESP32-CAM: {e}")
        finally:
            state.esp32_cam_connected = False
            db.update_system_status("esp32_cam_connected", False)
            socketio.emit("system_status_change", {"esp32_cam_connected": False})
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            time.sleep(1)

# ---------------------------------------------------------------------
# VIDEO STREAM & AI PROCESSING LOOP
# ---------------------------------------------------------------------
def video_capture_and_ai_loop():
    """
    Continuous AI inference loop.
    Processes frames coming from TCP Port 8889 (ESP32-CAM) or fallback webcam/synthetic demo.
    """
    cap = None
    last_frame_processed = None

    while True:
        frame = None
        with state.lock:
            if state.current_frame is not None:
                frame = state.current_frame.copy()

        # Fallback to local webcam or synthetic demo if ESP32-CAM not sending frames yet
        if frame is None:
            if cap is None:
                cap = cv2.VideoCapture(0)
            
            if cap.isOpened():
                ret, cam_f = cap.read()
                if ret and cam_f is not None:
                    frame = cam_f
            
            if frame is None:
                # Generate synthetic forest demo frame
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                frame[:] = (34, 75, 40)
                cv2.rectangle(frame, (100, 150), (140, 480), (25, 55, 100), -1)
                cv2.circle(frame, (120, 150), 70, (40, 130, 60), -1)
                cv2.rectangle(frame, (480, 180), (520, 480), (25, 55, 100), -1)
                cv2.circle(frame, (500, 180), 65, (40, 130, 60), -1)

                sec = int(time.time()) % 15
                if sec in [3, 4, 5, 6]:
                    cv2.circle(frame, (180, 350), 35, (0, 140, 255), -1)
                    cv2.circle(frame, (180, 340), 20, (0, 240, 255), -1)
                elif sec in [10, 11, 12]:
                    cv2.circle(frame, (460, 360), 40, (0, 120, 255), -1)
                    cv2.circle(frame, (460, 350), 22, (0, 255, 255), -1)

                cv2.putText(frame, "WAITING FOR ESP32-CAM TCP STREAM (PORT 8889)", (80, 460),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 255, 200), 1)

        # Run AI detection
        annotated_frame, detections = ai_engine.detect(frame)

        with state.lock:
            state.annotated_frame = annotated_frame
            state.last_detections = detections

        # Process detections for business logic & ESP32 actuation
        process_ai_events(detections)

        time.sleep(0.035)

def process_ai_events(detections):
    """Dispatches real-time commands based on detected objects."""
    now = time.time()
    fire_in_zone1 = False
    fire_in_zone2 = False
    fire_angle_zone1 = 90
    fire_angle_zone2 = 90

    for det in detections:
        cls_id = det["class_id"]
        label = det["label"]
        zone = det["zone"]
        angle = det["angle"]
        conf = det["confidence"]

        # --- A. FIRE DETECTED ---
        if label == "Api":
            if zone == 1:
                fire_in_zone1 = True
                fire_angle_zone1 = angle
            elif zone == 2:
                fire_in_zone2 = True
                fire_angle_zone2 = angle

            # Log incident with debounce (every 5 seconds)
            if now - state.last_fire_log_time > 5.0:
                state.last_fire_log_time = now
                event = db.log_event(
                    event_type="API_TERDETEKSI",
                    description=f"Api terdeteksi di Wilayah {zone} (Angle: {angle}°, Conf: {int(conf*100)}%)",
                    zone=f"Wilayah {zone}",
                    details=det
                )
                print(f"🔥 [FIRE INCIDENT] Alert Zone {zone}! Actuating Tower {zone} Servo & Relay.")
                socketio.emit("new_incident", event)
                socketio.emit("stats_update", db.get_all()["counters"])

        # --- B. NATURALLY FALLEN TREE DETECTED ---
        elif label == "Pohon jatuh alami":
            if now - state.last_fallen_log_time > 6.0:
                state.last_fallen_log_time = now
                event = db.log_event(
                    event_type="POHON_JATUH_ALAMI",
                    description=f"Pohon jatuh alami terdeteksi di Wilayah {zone}",
                    zone=f"Wilayah {zone}",
                    details=det
                )
                print(f"🌲 [FALLEN TREE] Natural fall logged in Zone {zone}")
                socketio.emit("new_incident", event)
                socketio.emit("stats_update", db.get_all()["counters"])

        # --- C. CUT TREE / ILLEGAL LOGGING DETECTED ---
        elif label == "Pohon yang ditebang":
            if now - state.last_cut_log_time > 6.0:
                state.last_cut_log_time = now
                event = db.log_event(
                    event_type="POHON_DITEBANG",
                    description=f"Penebangan liar / pohon ditebang terdeteksi di Wilayah {zone}",
                    zone=f"Wilayah {zone}",
                    details=det
                )
                print(f"🪓 [ILLEGAL LOGGING] Felled tree logged in Zone {zone}")
                socketio.emit("new_incident", event)
                socketio.emit("stats_update", db.get_all()["counters"])

    # Actuation dispatch for Fire extinguishing
    if fire_in_zone1 or fire_in_zone2:
        state.buzzer_status = True
        state.rgb_color = "RED"
        state.relay1_status = fire_in_zone1
        state.relay2_status = fire_in_zone2
        state.tower1_servo = fire_angle_zone1 if fire_in_zone1 else state.tower1_servo
        state.tower2_servo = fire_angle_zone2 if fire_in_zone2 else state.tower2_servo

        cmd = {
            "action": "FIRE_EXTINGUISH",
            "zone1_active": fire_in_zone1,
            "zone1_angle": fire_angle_zone1,
            "relay1": 1 if fire_in_zone1 else 0,
            "zone2_active": fire_in_zone2,
            "zone2_angle": fire_angle_zone2,
            "relay2": 1 if fire_in_zone2 else 0,
            "buzzer": 1,
            "rgb": "RED"
        }
        send_command_to_esp32(cmd)
    else:
        # If no fire currently detected and relays were on, turn them off
        if state.relay1_status or state.relay2_status:
            state.relay1_status = False
            state.relay2_status = False
            state.buzzer_status = False
            state.rgb_color = "GREEN"
            cmd = {
                "action": "STANDBY",
                "relay1": 0,
                "relay2": 0,
                "buzzer": 0,
                "rgb": "GREEN"
            }
            send_command_to_esp32(cmd)

# ---------------------------------------------------------------------
# FLASK WEB DASHBOARD & REST APIS
# ---------------------------------------------------------------------
@app.route("/")
def index():
    db_data = db.get_all()
    return render_template("index.html", data=db_data)

def generate_video_stream():
    """Generates MJPEG video stream with bounding box overlays."""
    while True:
        with state.lock:
            frame = state.annotated_frame
            if frame is None:
                # Blank loading screen
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "Waiting for Camera Stream...", (160, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            
            ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ret:
                continue
            frame_bytes = jpeg.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.04)

@app.route("/video_feed")
def video_feed():
    return Response(generate_video_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/database", methods=["GET"])
def api_get_database():
    return jsonify(db.get_all())

@app.route("/api/telemetry", methods=["GET"])
def api_get_telemetry():
    return jsonify({
        "radar_angle": state.radar_angle,
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
    """Manual actuator control from Web UI."""
    data = request.json or {}
    action = data.get("action", "")
    
    if action == "SET_SERVO":
        tower = data.get("tower", 1)
        angle = int(data.get("angle", 90))
        if tower == 1:
            state.tower1_servo = angle
        else:
            state.tower2_servo = angle
        send_command_to_esp32({"action": "SET_SERVO", "tower": tower, "angle": angle})
        
    elif action == "TOGGLE_RELAY":
        relay_id = data.get("relay", 1)
        status = bool(data.get("status", False))
        if relay_id == 1:
            state.relay1_status = status
        else:
            state.relay2_status = status
        send_command_to_esp32({"action": "SET_RELAY", "relay": relay_id, "state": 1 if status else 0})
        
    elif action == "CAPTURE_SNAPSHOT":
        # Save snapshot of live camera into dataset/images/ for manual labeling
        with state.lock:
            if state.current_frame is not None:
                os.makedirs("dataset/images", exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = os.path.join("dataset/images", f"snapshot_{timestamp}.jpg")
                cv2.imwrite(save_path, state.current_frame)
                print(f"[DATASET] Captured and saved snapshot to {save_path}")
                return jsonify({"status": "success", "file": save_path})
            else:
                return jsonify({"status": "error", "message": "No active camera frame"}), 400

    return jsonify({"status": "success", "action": action})

# ---------------------------------------------------------------------
# INITIALIZATION & MAIN ENTRY
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Start TCP Server thread for ESP32 Main Actuator Node (Port 8888)
    tcp_main_thread = threading.Thread(target=tcp_esp32_server_thread, daemon=True)
    tcp_main_thread.start()

    # 2. Start TCP Client thread — konek ke ESP32-CAM (sekarang jadi server)
    tcp_cam_thread = threading.Thread(target=tcp_esp32_cam_client_thread, daemon=True)
    tcp_cam_thread.start()

    # 3. Start Video Stream & AI Processing thread
    ai_thread = threading.Thread(target=video_capture_and_ai_loop, daemon=True)
    ai_thread.start()

    print("=" * 70)
    print("AIoT Intelligence Forest Protection Server Started")
    print("Web Dashboard    : http://localhost:5000")
    print("ESP32 Main TCP   : Listen port 8888 (ESP32 konek ke sini)")
    print(f"ESP32-CAM TCP    : Konek ke {ESP32_CAM_IP}:{ESP32_CAM_PORT}")
    print("=" * 70)
    print(f"[INFO] Pastikan IP ESP32-CAM sudah benar: ESP32_CAM_IP = '{ESP32_CAM_IP}'")

    socketio.run(app, host="0.0.0.0", port=5000, debug=False)

