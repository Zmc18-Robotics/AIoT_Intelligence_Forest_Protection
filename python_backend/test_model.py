"""
=======================================================================
 AIoT Intelligence Forest Protection - Live Camera Model Testing Tool
=======================================================================
Menguji model YOLO hasil training secara REALTIME melalui KAMERA:
  - Mengarahkan kamera ke objek / foto / datasheet
  - Otomatis memunculkan bounding box pada objek yang terdeteksi
  - Menampilkan nama kelas dan persentase keyakinan (confidence %)
  - Menampilkan 4 titik Area 1 & Area 2 yang telah dikalibrasi

Mendukung 3 Pilihan Kamera:
  [1] ESP32-CAM WiFi (TCP/IP Stream Port 80)  <-- Utama
  [2] Webcam Laptop / Kamera USB (Index 0, 1)
  [3] USB Serial COM Port (ESP32-CAM via USB CH340 - Baud 460800)

Cara pakai:
  python python_backend/test_model.py                  # Auto-connect (Cepat!)
  python python_backend/test_model.py 192.168.4.2      # Langsung ESP32-CAM IP
  python python_backend/test_model.py 0                # Langsung Webcam 0
  python python_backend/test_model.py COM3             # Langsung Serial COM3

Kontrol Keyboard:
  [+] / [-] : Naikkan / turunkan Ambang Batas Keyakinan (Confidence %)
  [S]       : Simpan Foto Hasil Deteksi (Screenshot)
  [C]       : Reload Titik Area Kalibrasi
  [F]       : Toggle Flash / Senter ESP32-CAM
  [Q] / ESC : Keluar
=======================================================================
"""

import os
import sys
import time
import socket
import struct
import threading
import argparse
import json
import cv2
import numpy as np

# Coba import pyserial jika ada
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "python_backend" else SCRIPT_DIR

# Baca IP ESP32-CAM dari konfigurasi sentral
try:
    from network_config import load_network_config
    _, DEFAULT_ESP32_CAM_IP, _, _ = load_network_config("192.168.4.3", "192.168.4.2")
except Exception:
    DEFAULT_ESP32_CAM_IP = "10.175.157.25"

# Lokasi konfigurasi area
ZONES_CONFIG_PATHS = [
    os.path.join(ROOT_DIR, "data", "zones_config.json"),
    os.path.join(ROOT_DIR, "python_backend", "data", "zones_config.json")
]

# Lokasi model bobot terbaik
DEFAULT_MODEL_PATHS = [
    os.path.join(ROOT_DIR, "runs", "detect", "runs", "forest_ai", "forest_protection_model", "weights", "best.pt"),
    os.path.join(ROOT_DIR, "runs", "forest_ai", "forest_protection_model", "weights", "best.pt"),
    os.path.join(ROOT_DIR, "runs", "detect", "runs", "forest_ai", "forest_protection_model", "weights", "last.pt"),
    os.path.join(ROOT_DIR, "best.pt"),
    os.path.join(ROOT_DIR, "yolov8n.pt")
]

SAVE_RESULT_DIR = os.path.join(ROOT_DIR, "dataset", "test_results")
os.makedirs(SAVE_RESULT_DIR, exist_ok=True)

# Warna kelas (BGR)
CLASS_COLOR_BY_NAME = {
    "Api"                : (30,  30,  255),   # Merah
    "api"                : (30,  30,  255),
    "Pohon yang ditebang": (0,  220,  255),   # Kuning
    "pohon yang ditebang": (0,  220,  255),
    "Pohon Ditebang"     : (0,  220,  255),
    "Pohon jatuh alami"  : (0,  210,   60),   # Hijau
    "pohon jatuh alami"  : (0,  210,   60),
    "Pohon Jatuh"        : (0,  210,   60),
}
DEFAULT_COLOR = (200, 200, 200)

def get_class_color(name: str):
    if name in CLASS_COLOR_BY_NAME:
        return CLASS_COLOR_BY_NAME[name]
    name_lower = name.lower()
    for k, v in CLASS_COLOR_BY_NAME.items():
        if k.lower() == name_lower:
            return v
    return DEFAULT_COLOR

CANVAS_W = 1000
CANVAS_H = 700
TOP_BAR_H = 65
BOTTOM_BAR_H = 45

latest_frame     = None
frame_lock       = threading.Lock()
is_running       = True
source_connected = False
fps_val          = 0.0
source_info_str  = ""
ser_global       = None
flash_state      = True
active_zones     = {}

def load_zones():
    for p in ZONES_CONFIG_PATHS:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(f"[ZONE] Memuat titik kalibrasi dari {p}")
                    return data
            except Exception as e:
                print(f"[ZONE] Gagal membaca {p}: {e}")
    return {}

def find_best_model(custom_path=None):
    if custom_path and os.path.exists(custom_path):
        return custom_path
    for p in DEFAULT_MODEL_PATHS:
        if os.path.exists(p):
            return p
    return "yolov8n.pt"

def is_ip_reachable(ip, port=80, timeout=0.8):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        s.close()
        return True
    except Exception:
        return False

# =====================================================================
# THREAD 1: WEBCAM
# =====================================================================
def webcam_thread(cam_index):
    global latest_frame, source_connected, fps_val, is_running
    print(f"\n[WEBCAM] Membuka kamera index {cam_index}...")

    cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(cam_index)

    if not cap.isOpened():
        print(f"[WEBCAM ERROR] Gagal membuka kamera index {cam_index}.")
        source_connected = False
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    source_connected = True
    print(f"[WEBCAM] Kamera index {cam_index} aktif!")

    prev_time = time.time()
    while is_running:
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue

        curr_time = time.time()
        diff = curr_time - prev_time
        if diff > 0:
            fps_val = 0.9 * fps_val + 0.1 * (1.0 / diff) if fps_val > 0 else (1.0 / diff)
        prev_time = curr_time

        with frame_lock:
            latest_frame = frame

    cap.release()
    source_connected = False

# =====================================================================
# THREAD 2: USB SERIAL
# =====================================================================
def serial_thread(port_name, baud_rate=460800):
    global latest_frame, source_connected, fps_val, is_running, ser_global
    if not HAS_SERIAL:
        print("[SERIAL ERROR] Modul pyserial belum terpasang.")
        return

    while is_running:
        ser = None
        try:
            print(f"\n[SERIAL] Membuka {port_name} pada Baud {baud_rate}...")
            ser = serial.Serial(port_name, baud_rate, timeout=2.0)
            ser_global = ser
            time.sleep(0.5)
            ser.reset_input_buffer()
            ser.write(b"START_SERIAL_STREAM\n")
            ser.flush()

            source_connected = True
            print(f"[SERIAL] Terhubung ke {port_name}! Menerima video stream...")

            prev_time = time.time()
            while is_running:
                byte1 = ser.read(1)
                if not byte1: continue
                if byte1 == b"\xaa":
                    rest = ser.read(3)
                    if rest == b"\xbb\xcc\xdd":
                        len_bytes = ser.read(4)
                        if len(len_bytes) == 4:
                            frame_len = struct.unpack(">I", len_bytes)[0]
                            if 0 < frame_len <= 1_000_000:
                                jpeg_data = bytearray()
                                while len(jpeg_data) < frame_len and is_running:
                                    chunk = ser.read(min(4096, frame_len - len(jpeg_data)))
                                    if not chunk: break
                                    jpeg_data.extend(chunk)

                                if len(jpeg_data) == frame_len:
                                    np_arr = np.frombuffer(jpeg_data, dtype=np.uint8)
                                    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                                    if frame is not None:
                                        curr_time = time.time()
                                        diff = curr_time - prev_time
                                        if diff > 0:
                                            fps_val = 0.9 * fps_val + 0.1 * (1.0 / diff) if fps_val > 0 else (1.0 / diff)
                                        prev_time = curr_time
                                        with frame_lock:
                                            latest_frame = frame
        except Exception as e:
            source_connected = False
        finally:
            if ser and ser.is_open:
                try:
                    ser.write(b"STOP_SERIAL_STREAM\n")
                    ser.close()
                except Exception: pass
            ser_global = None
            source_connected = False
            time.sleep(1.5)

# =====================================================================
# THREAD 3: TCP/IP STREAM (ESP32-CAM)
# =====================================================================
def recv_exact(sock, n):
    data = b""
    while len(data) < n and is_running:
        try:
            chunk = sock.recv(n - len(data))
            if not chunk: return None
            data += chunk
        except Exception:
            return None
    return data

def tcp_wifi_thread(ip, port=80):
    global latest_frame, source_connected, fps_val, is_running

    while is_running:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.5)
            sock.connect((ip, port))
            sock.settimeout(12.0)
            source_connected = True
            print(f"[TCP] Berhasil terhubung ke ESP32-CAM ({ip}:{port})!")

            prev_time = time.time()
            while is_running:
                len_bytes = recv_exact(sock, 4)
                if not len_bytes: break

                frame_len = struct.unpack(">I", len_bytes)[0]
                if frame_len <= 0 or frame_len > 1_000_000:
                    continue

                jpeg_data = recv_exact(sock, frame_len)
                if not jpeg_data or len(jpeg_data) != frame_len:
                    break

                np_arr = np.frombuffer(jpeg_data, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is not None:
                    curr_time = time.time()
                    diff = curr_time - prev_time
                    if diff > 0:
                        fps_val = 0.9 * fps_val + 0.1 * (1.0 / diff) if fps_val > 0 else (1.0 / diff)
                    prev_time = curr_time

                    with frame_lock:
                        latest_frame = frame

        except Exception:
            pass
        finally:
            source_connected = False
            if sock:
                try: sock.close()
                except Exception: pass
            time.sleep(1.5)

def toggle_flash():
    global flash_state, ser_global
    flash_state = not flash_state
    if ser_global and ser_global.is_open:
        try:
            ser_global.write(f"FLASH:{1 if flash_state else 0}\n".encode("utf-8"))
            print(f"[*] Senter/Flash diubah ke: {'ON' if flash_state else 'OFF'}")
        except Exception:
            pass

def get_available_com_ports():
    if not HAS_SERIAL:
        return []
    return [p.device for p in serial.tools.list_ports.comports()]

# =====================================================================
# LIVE CAMERA RUNNER
# =====================================================================
def run_live_camera_test(model_path, conf_thresh=0.45, camera_override=None):
    global is_running, source_info_str, active_zones

    try:
        from ultralytics import YOLO
    except ImportError:
        print("[ERROR] Modul 'ultralytics' belum terpasang. Jalankan: pip install ultralytics")
        return

    print("=" * 65)
    print(" 🌲 AIoT Forest Protection — Live Camera Model Tester")
    print("=" * 65)
    print(f"[*] Model Bobot   : {model_path}")
    print(f"[*] Ambang Batas  : {conf_thresh * 100:.0f}%")
    print(f"[*] Target ESP32  : {DEFAULT_ESP32_CAM_IP}:80")
    print("=" * 65)

    # 1. Load YOLO Model
    print("[AI] Memuat model YOLO...")
    model = YOLO(model_path)
    print(f"[AI] Model siap! Kelas: {list(model.names.values())}\n")

    active_zones = load_zones()

    # 2. Tentukan Sumber Kamera secara Cerdas
    selected_mode = None
    target_param  = None

    # Jika ada parameter dari CLI
    target_arg = camera_override
    if target_arg is None and len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        target_arg = sys.argv[1].strip()

    if target_arg:
        if target_arg.isdigit():
            selected_mode = "webcam"
            target_param = int(target_arg)
        elif target_arg.upper().startswith("COM"):
            selected_mode = "serial"
            target_param = target_arg.upper()
        elif "." in target_arg:
            selected_mode = "esp32"
            target_param = target_arg
        elif target_arg.lower() in ("cam", "esp", "esp32"):
            selected_mode = "esp32"
            target_param = DEFAULT_ESP32_CAM_IP

    # Jika tidak ada argumen di CLI: Cek secara otomatis tanpa nge-freeze!
    if selected_mode is None:
        # Cek apakah terminal interaktif atau Code Runner
        is_interactive = sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False

        if not is_interactive:
            # Code Runner atau Subproses: Langsung pilih ESP32-CAM secara otomatis
            print("[AUTO] Menjalankan dalam mode non-interaktif -> Memilih ESP32-CAM secara otomatis.")
            selected_mode = "esp32"
            target_param = DEFAULT_ESP32_CAM_IP
        else:
            # Terminal interaktif
            esp_online = is_ip_reachable(DEFAULT_ESP32_CAM_IP, 80, timeout=0.6)
            com_list = get_available_com_ports()
            com_hint = f" ({', '.join(com_list)})" if com_list else ""

            print("PILIH SUMBER KAMERA:")
            print(f"  [1] ESP32-CAM WiFi ({DEFAULT_ESP32_CAM_IP}:80)  [{'ONLINE' if esp_online else 'OFFLINE'}]  <-- Default")
            print(f"  [2] Webcam Laptop / Kamera USB (Index 0)")
            print(f"  [3] USB Serial COM Port{com_hint}")
            print("-" * 65)

            try:
                pilihan = input(f"Pilihan (1/2/3) [Tekan Enter untuk ESP32-CAM]: ").strip()
            except (EOFError, Exception):
                pilihan = ""

            if pilihan == "2":
                selected_mode = "webcam"
                target_param = 0
            elif pilihan == "3":
                selected_mode = "serial"
                target_param = com_list[0] if com_list else "COM3"
            else:
                selected_mode = "esp32"
                target_param = DEFAULT_ESP32_CAM_IP

    # Mulai thread kamera sesuai mode
    if selected_mode == "webcam":
        cam_idx = target_param if isinstance(target_param, int) else 0
        source_info_str = f"Webcam (Index {cam_idx})"
        threading.Thread(target=webcam_thread, args=(cam_idx,), daemon=True).start()
    elif selected_mode == "serial":
        com_name = target_param if isinstance(target_param, str) else "COM3"
        source_info_str = f"Serial ({com_name} @ 460800)"
        threading.Thread(target=serial_thread, args=(com_name, 460800), daemon=True).start()
    else:
        ip = target_param if isinstance(target_param, str) and "." in target_param else DEFAULT_ESP32_CAM_IP
        source_info_str = f"ESP32-CAM ({ip}:80)"
        threading.Thread(target=tcp_wifi_thread, args=(ip, 80), daemon=True).start()

    window_name = f"AIoT Forest — Live Detection ({source_info_str})"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, CANVAS_W, CANVAS_H)

    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
    placeholder[:] = (20, 25, 22)
    cv2.putText(placeholder, f"Menghubungkan ke {source_info_str}...", (60, 220),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 210, 120), 2)
    cv2.putText(placeholder, "Pastikan laptop terhubung ke WiFi 'Absolute Solver'", (65, 270),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (140, 160, 140), 1)

    toast_msg = f"Model {os.path.basename(model_path)} siap"
    toast_time = time.time()
    shot_counter = 0

    print(f"\n[INFO] Membuka jendela deteksi realtime...")
    print("  [+] / [-] : Ubah Ambang Batas Keyakinan (Confidence %)")
    print("  [S]       : Simpan Foto Hasil Deteksi")
    print("  [C]       : Reload Titik Kalibrasi Area")
    print("  [F]       : Toggle Flash / Senter")
    print("  [Q] / ESC : Keluar\n")

    last_inf_time = 0.0
    detections = []
    inf_time_ms = 0.0

    try:
        while True:
            with frame_lock:
                frame = latest_frame.copy() if latest_frame is not None else None

            if frame is None:
                display = placeholder.copy()
                detections = []
                inf_time_ms = 0.0
            else:
                fh, fw = frame.shape[:2]

                # Jalankan inferensi YOLO (maksimal tiap 30ms agar tidak membebani CPU)
                now = time.time()
                if now - last_inf_time >= 0.035:
                    last_inf_time = now
                    start_inf = time.time()
                    results = model.predict(source=frame, conf=conf_thresh, imgsz=320, verbose=False)
                    inf_time_ms = (time.time() - start_inf) * 1000

                    detections = []
                    for r in results:
                        for box in (r.boxes or []):
                            cls_id = int(box.cls[0].item())
                            conf = float(box.conf[0].item())
                            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                            lbl = model.names.get(cls_id, f"Kelas {cls_id}")
                            detections.append({
                                "cls": cls_id,
                                "label": lbl,
                                "conf": conf,
                                "bbox": [int(x1), int(y1), int(x2), int(y2)]
                            })

                # Gambar 4 Titik Poligon Area 1 & Area 2 dari kalibrasi user
                poly1_pts = []
                poly2_pts = []
                for p in active_zones.get("area1", {}).get("points", []):
                    poly1_pts.append([int(p["x"] * fw), int(p["y"] * fh)])
                for p in active_zones.get("area2", {}).get("points", []):
                    poly2_pts.append([int(p["x"] * fw), int(p["y"] * fh)])

                # Gambar Area 1 (Hijau)
                if len(poly1_pts) >= 3:
                    p1_arr = np.array(poly1_pts, dtype=np.int32)
                    ov1 = frame.copy()
                    cv2.fillPoly(ov1, [p1_arr], (0, 220, 80))
                    cv2.addWeighted(ov1, 0.15, frame, 0.85, 0, frame)
                    cv2.polylines(frame, [p1_arr], True, (0, 220, 80), 2, cv2.LINE_AA)
                    for idx, pt in enumerate(poly1_pts):
                        cv2.circle(frame, tuple(pt), 6, (0, 220, 80), -1)
                        cv2.circle(frame, tuple(pt), 8, (255, 255, 255), 1)
                        cv2.putText(frame, f"1:P{idx+1}", (pt[0]+7, pt[1]-6),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1)
                    cx1 = int(np.mean(p1_arr[:, 0]))
                    cy1 = int(np.mean(p1_arr[:, 1]))
                    cv2.putText(frame, "AREA 1 (Servo 1)", (cx1-50, cy1),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 220, 80), 2)

                # Gambar Area 2 (Biru)
                if len(poly2_pts) >= 3:
                    p2_arr = np.array(poly2_pts, dtype=np.int32)
                    ov2 = frame.copy()
                    cv2.fillPoly(ov2, [p2_arr], (80, 120, 255))
                    cv2.addWeighted(ov2, 0.15, frame, 0.85, 0, frame)
                    cv2.polylines(frame, [p2_arr], True, (80, 120, 255), 2, cv2.LINE_AA)
                    for idx, pt in enumerate(poly2_pts):
                        cv2.circle(frame, tuple(pt), 6, (80, 120, 255), -1)
                        cv2.circle(frame, tuple(pt), 8, (255, 255, 255), 1)
                        cv2.putText(frame, f"2:P{idx+1}", (pt[0]+7, pt[1]-6),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1)
                    cx2 = int(np.mean(p2_arr[:, 0]))
                    cy2 = int(np.mean(p2_arr[:, 1]))
                    cv2.putText(frame, "AREA 2 (Servo 2)", (cx2-50, cy2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (80, 120, 255), 2)

                # Gambar Garis Kalibrasi Sudut Servo (0° - 90°)
                cfg_angles = [("area1", (255, 230, 0), "S1"), ("area2", (255, 100, 255), "S2")]
                for ak, col, pfx in cfg_angles:
                    s_pts = active_zones.get(ak, {}).get("servo_points", {})
                    if "p0" in s_pts and "p90" in s_pts:
                        p0 = s_pts["p0"]
                        p90 = s_pts["p90"]
                        x0, y0 = int(p0["x"] * fw), int(p0["y"] * fh)
                        x1, y1 = int(p90["x"] * fw), int(p90["y"] * fh)
                        cv2.line(frame, (x0, y0), (x1, y1), col, 2, cv2.LINE_AA)
                        cv2.circle(frame, (x0, y0), 7, col, -1)
                        cv2.putText(frame, f"{pfx}: 0°", (x0-10, y0-8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 2)
                        cv2.circle(frame, (x1, y1), 7, col, -1)
                        cv2.putText(frame, f"{pfx}: 90°", (x1+8, y1+5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 2)

                # Gambar Bounding Box deteksi & Target Sudut
                for det in detections:
                    lbl_name = det["label"]
                    conf = det["conf"]
                    x1, y1, x2, y2 = det["bbox"]
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                    det_zone = ""
                    calc_deg_str = ""
                    if len(poly1_pts) >= 3 and cv2.pointPolygonTest(np.array(poly1_pts, dtype=np.int32), (cx, cy), False) >= 0:
                        det_zone = " [Area 1]"
                        s_pts = active_zones.get("area1", {}).get("servo_points", {})
                        if "p0" in s_pts and "p90" in s_pts:
                            p0 = s_pts["p0"]; p90 = s_pts["p90"]
                            x0, y0 = p0["x"] * fw, p0["y"] * fh
                            x1, y1 = p90["x"] * fw, p90["y"] * fh
                            dx, dy = x1 - x0, y1 - y0
                            L2 = dx*dx + dy*dy
                            if L2 > 0:
                                t = np.clip(((cx - x0)*dx + (cy - y0)*dy) / L2, 0.0, 1.0)
                                a = int(round(p0.get("angle", 0) + t * (p90.get("angle", 90) - p0.get("angle", 0))))
                                calc_deg_str = f" | S1: {a}°"
                    elif len(poly2_pts) >= 3 and cv2.pointPolygonTest(np.array(poly2_pts, dtype=np.int32), (cx, cy), False) >= 0:
                        det_zone = " [Area 2]"
                        s_pts = active_zones.get("area2", {}).get("servo_points", {})
                        if "p0" in s_pts and "p90" in s_pts:
                            p0 = s_pts["p0"]; p90 = s_pts["p90"]
                            x0, y0 = p0["x"] * fw, p0["y"] * fh
                            x1, y1 = p90["x"] * fw, p90["y"] * fh
                            dx, dy = x1 - x0, y1 - y0
                            L2 = dx*dx + dy*dy
                            if L2 > 0:
                                t = np.clip(((cx - x0)*dx + (cy - y0)*dy) / L2, 0.0, 1.0)
                                a = int(round(p0.get("angle", 0) + t * (p90.get("angle", 90) - p0.get("angle", 0))))
                                calc_deg_str = f" | S2: {a}°"

                    col = get_class_color(lbl_name)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), col, 2)

                    badge_text = f"{lbl_name}{det_zone}{calc_deg_str} : {conf*100:.1f}%"
                    cv2.rectangle(frame, (x1, max(0, y1-24)), (x1 + len(badge_text)*9 + 15, max(0, y1)), col, -1)
                    cv2.putText(frame, badge_text, (x1 + 6, max(16, y1-6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (15, 15, 15), 2)

                display = frame

            # Render ke Canvas HUD
            cur_h, cur_w = display.shape[:2]
            canvas = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
            canvas[:] = (20, 20, 20)

            avail_w = CANVAS_W - 20
            avail_h = CANVAS_H - TOP_BAR_H - BOTTOM_BAR_H - 10
            scale = min(avail_w / cur_w, avail_h / cur_h)
            disp_w = int(cur_w * scale)
            disp_h = int(cur_h * scale)

            offset_x = (CANVAS_W - disp_w) // 2
            offset_y = TOP_BAR_H + (avail_h - disp_h) // 2

            resized_disp = cv2.resize(display, (disp_w, disp_h), interpolation=cv2.INTER_LINEAR)
            canvas[offset_y : offset_y + disp_h, offset_x : offset_x + disp_w] = resized_disp

            # Header HUD
            cv2.rectangle(canvas, (0, 0), (CANVAS_W, TOP_BAR_H), (12, 12, 12), -1)
            cv2.line(canvas, (0, TOP_BAR_H), (CANVAS_W, TOP_BAR_H), (45, 45, 45), 1)

            det_count = len(detections)
            status_text = f"TERDETEKSI: {det_count} Objek" if det_count > 0 else "Menunggu Objek..."
            status_col = (0, 255, 120) if det_count > 0 else (160, 160, 160)
            cv2.putText(canvas, f"STATUS: {status_text}", (15, 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.58, status_col, 2, cv2.LINE_AA)

            fps_str = f"{fps_val:.1f} FPS" if source_connected else "Offline"
            inf_str = f"Inference: {inf_time_ms:.1f}ms" if inf_time_ms > 0 else ""
            cv2.putText(canvas, f"Kamera: {source_info_str}  |  {fps_str}  |  {inf_str}",
                        (15, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180, 180, 180), 1, cv2.LINE_AA)

            bx = CANVAS_W - 320
            cv2.putText(canvas, f"Model: {os.path.basename(model_path)}", (bx, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.44, (200, 220, 255), 1, cv2.LINE_AA)
            cv2.putText(canvas, f"Ambang Batas Conf: {conf_thresh * 100:.0f}%  [+/-]", (bx, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 230, 255), 2, cv2.LINE_AA)

            # Footer HUD
            foot_y = CANVAS_H - BOTTOM_BAR_H
            cv2.rectangle(canvas, (0, foot_y), (CANVAS_W, CANVAS_H), (12, 12, 12), -1)
            cv2.line(canvas, (0, foot_y), (CANVAS_W, foot_y), (45, 45, 45), 1)
            cv2.putText(canvas, "[+] / [-] Ubah Conf %   |   [S] Simpan Foto   |   [C] Reload Area   |   [F] Flash   |   [Q] Keluar",
                        (20, foot_y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (190, 225, 255), 1, cv2.LINE_AA)

            # Toast Popup
            if toast_msg and (time.time() - toast_time) < 2.0:
                t_size, _ = cv2.getTextSize(toast_msg, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 1)
                tw = t_size[0] + 24
                tx = (CANVAS_W - tw) // 2
                ty = TOP_BAR_H + 10
                cv2.rectangle(canvas, (tx, ty), (tx + tw, ty + 30), (20, 20, 20), -1)
                cv2.rectangle(canvas, (tx, ty), (tx + tw, ty + 30), (0, 255, 120), 2)
                cv2.putText(canvas, toast_msg, (tx + 12, ty + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 120), 1, cv2.LINE_AA)

            cv2.imshow(window_name, canvas)

            key = cv2.waitKey(15) & 0xFF
            if key in (ord('q'), ord('Q'), 27):
                break
            elif key in (ord('+'), ord('=')):
                conf_thresh = min(0.95, conf_thresh + 0.05)
                toast_msg = f"Confidence: {conf_thresh * 100:.0f}%"
                toast_time = time.time()
            elif key in (ord('-'), ord('_')):
                conf_thresh = max(0.05, conf_thresh - 0.05)
                toast_msg = f"Confidence: {conf_thresh * 100:.0f}%"
                toast_time = time.time()
            elif key in (ord('c'), ord('C')):
                active_zones = load_zones()
                toast_msg = "Area Kalibrasi Berhasil Di-reload!"
                toast_time = time.time()
            elif key in (ord('s'), ord('S')):
                shot_counter += 1
                out_path = os.path.join(SAVE_RESULT_DIR, f"live_det_{int(time.time())}_{shot_counter:03d}.jpg")
                cv2.imwrite(out_path, canvas)
                toast_msg = f"Disimpan ke: {os.path.basename(out_path)}"
                toast_time = time.time()
            elif key in (ord('f'), ord('F')):
                toggle_flash()

    except KeyboardInterrupt:
        pass
    finally:
        is_running = False
        cv2.destroyAllWindows()
        print("\n[SELESAI] Pengujian kamera selesai.\n")

def main():
    parser = argparse.ArgumentParser(description="Live Camera YOLO Model Tester")
    parser.add_argument("source", nargs="?", default=None, help="Camera index (0), COM port (COM3), or IP (192.168.4.2)")
    parser.add_argument("--model", type=str, default=None, help="Path ke model best.pt")
    parser.add_argument("--conf", type=float, default=0.45, help="Ambang batas keyakinan (default: 0.45)")
    args = parser.parse_args()

    model_file = find_best_model(args.model)
    print(f"[INFO] Menggunakan model: {model_file}")

    run_live_camera_test(model_file, conf_thresh=args.conf, camera_override=args.source)

if __name__ == "__main__":
    main()
