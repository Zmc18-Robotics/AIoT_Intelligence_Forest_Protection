"""
=======================================================================
 AIoT Forest Protection - Interactive Area & Angle Calibration Tool
=======================================================================
Fungsi:
  1. Menandai 4 titik poligon untuk Area 1 dan Area 2 pada kamera ESP32-CAM.
  2. Menentukan garis rentang sudut 0° dan 90° untuk Servo 1 dan Servo 2.
     Sehingga saat ada api terdeteksi, servo akan memprediksi sudut secara
     presisi sesuai posisi koordinat api di sepanjang sumbu 0° - 90°.

Kontrol Keyboard:
  [1]     : Kalibrasi ulang 4 Titik Poligon AREA 1 (klik 4 titik: P1->P2->P3->P4)
  [2]     : Kalibrasi ulang 4 Titik Poligon AREA 2 (klik 4 titik: P1->P2->P3->P4)
  [3]     : Kalibrasi Garis Sudut SERVO 1 (klik 2 titik: Titik 1 = 0°, Titik 2 = 90°)
  [4]     : Kalibrasi Garis Sudut SERVO 2 (klik 2 titik: Titik 1 = 0°, Titik 2 = 90°)
  [Drag]  : Klik & geser (drag) titik manapun di layar langsung dengan mouse
  [S]     : Simpan konfigurasi ke data/zones_config.json
  [R]     : Reset semua titik ke posisi default
  [Q]/ESC : Simpan dan Keluar
=======================================================================
"""

import os
import sys
import json
import time
import socket
import struct
import threading
import cv2
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "python_backend" else SCRIPT_DIR
CONFIG_PATHS = [
    os.path.join(ROOT_DIR, "data", "zones_config.json"),
    os.path.join(ROOT_DIR, "python_backend", "data", "zones_config.json")
]
CONFIG_PATH = CONFIG_PATHS[0]

# Menggunakan IP ESP32-CAM dari konfigurasi sentral (otomatis sinkron dengan main.py & server.py)
try:
    from network_config import load_network_config
    _, ESP32_CAM_IP, _, ESP32_CAM_PORT = load_network_config("192.168.4.3", "192.168.4.2")
except Exception:
    ESP32_CAM_IP = "192.168.4.2"
    ESP32_CAM_PORT = 80

if len(sys.argv) > 1 and "." in sys.argv[1]:
    ESP32_CAM_IP = sys.argv[1].strip()

DEFAULT_POINTS = {
    "area1": [
        {"name": "P1 (Kiri Atas)",   "x": 0.319, "y": 0.267},
        {"name": "P2 (Kanan Atas)",  "x": 0.512, "y": 0.417},
        {"name": "P3 (Kanan Bawah)", "x": 0.153, "y": 0.812},
        {"name": "P4 (Kiri Bawah)",  "x": 0.000, "y": 0.546}
    ],
    "area2": [
        {"name": "P1 (Kiri Atas)",   "x": 0.575, "y": 0.479},
        {"name": "P2 (Kanan Atas)",  "x": 0.812, "y": 0.683},
        {"name": "P3 (Kanan Bawah)", "x": 0.522, "y": 1.000},
        {"name": "P4 (Kiri Bawah)",  "x": 0.212, "y": 0.867}
    ]
}

DEFAULT_SERVO_POINTS = {
    "area1": {
        "p0":  {"name": "S1: 0°",  "x": 0.05, "y": 0.54, "angle": 0},
        "p90": {"name": "S1: 90°", "x": 0.45, "y": 0.35, "angle": 90}
    },
    "area2": {
        "p0":  {"name": "S2: 0°",  "x": 0.25, "y": 0.87, "angle": 0},
        "p90": {"name": "S2: 90°", "x": 0.80, "y": 0.65, "angle": 90}
    }
}

# State global
current_config = None
active_edit_mode = None  # "area1", "area2", "servo1", "servo2", atau None
new_click_points = []
dragging_item = None     # ("polygon", area_key, point_index) atau ("servo", area_key, "p0"/"p90")
mouse_hover_pos = (0, 0)
is_running = True
latest_frame = None
frame_lock = threading.Lock()
toast_message = "Siap mengkalibrasi area & sudut 0°-90°"
toast_time = time.time()


def load_config():
    global current_config
    loaded = False
    for cp in CONFIG_PATHS:
        if os.path.exists(cp):
            try:
                with open(cp, "r", encoding="utf-8") as f:
                    current_config = json.load(f)
                    print(f"[+] Memuat konfigurasi zona dari: {cp}")
                    loaded = True
                    break
            except Exception as e:
                print(f"[!] Gagal membaca {cp}: {e}")

    if not loaded or not current_config:
        current_config = {
            "version": "1.0",
            "description": "Konfigurasi 4 Titik Poligon & Kalibrasi Sudut Servo (0° - 90°)",
            "area1": {
                "name": "Area 1",
                "servo": 1,
                "servo_gpio": 16,
                "relay": 1,
                "relay_gpio": 25,
                "servo_points": DEFAULT_SERVO_POINTS["area1"],
                "points": DEFAULT_POINTS["area1"]
            },
            "area2": {
                "name": "Area 2",
                "servo": 2,
                "servo_gpio": 17,
                "relay": 2,
                "relay_gpio": 26,
                "servo_points": DEFAULT_SERVO_POINTS["area2"],
                "points": DEFAULT_POINTS["area2"]
            }
        }

    # Pastikan setiap area memiliki struktur servo_points
    for ak in ["area1", "area2"]:
        if ak not in current_config:
            current_config[ak] = {}
        if "points" not in current_config[ak]:
            current_config[ak]["points"] = DEFAULT_POINTS[ak]
        if "servo_points" not in current_config[ak]:
            current_config[ak]["servo_points"] = DEFAULT_SERVO_POINTS[ak]
        else:
            if "p0" not in current_config[ak]["servo_points"]:
                current_config[ak]["servo_points"]["p0"] = DEFAULT_SERVO_POINTS[ak]["p0"]
            if "p90" not in current_config[ak]["servo_points"]:
                current_config[ak]["servo_points"]["p90"] = DEFAULT_SERVO_POINTS[ak]["p90"]


def save_config():
    global toast_message, toast_time
    for cp in CONFIG_PATHS:
        try:
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(current_config, f, indent=2)
            print(f"[+] Konfigurasi berhasil disimpan ke: {cp}")
        except Exception as e:
            print(f"[!] Gagal menyimpan ke {cp}: {e}")
    toast_message = "✅ Konfigurasi Area & Sudut Servo Tersimpan!"
    toast_time = time.time()


# ── Hitung Prediksi Sudut dari Posisi (cx, cy) ──
def compute_projected_angle(cx, cy, servo_pts, w, h):
    p0 = servo_pts.get("p0")
    p90 = servo_pts.get("p90")
    if not p0 or not p90:
        return 90

    x0, y0 = p0["x"] * w, p0["y"] * h
    x1, y1 = p90["x"] * w, p90["y"] * h

    dx = x1 - x0
    dy = y1 - y0
    seg_sq = dx * dx + dy * dy
    if seg_sq < 1.0:
        return 45

    t = ((cx - x0) * dx + (cy - y0) * dy) / seg_sq
    t_clamped = np.clip(t, 0.0, 1.0)
    angle = int(round(p0.get("angle", 0) + t_clamped * (p90.get("angle", 90) - p0.get("angle", 0))))
    return int(np.clip(angle, 0, 180))


# ── Thread Penerima Kamera ESP32-CAM atau Webcam ──
def camera_worker():
    global latest_frame, is_running
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        sock.connect((ESP32_CAM_IP, ESP32_CAM_PORT))
        sock.settimeout(10.0)
        print(f"[CAM] Berhasil terhubung ke ESP32-CAM ({ESP32_CAM_IP}:{ESP32_CAM_PORT})")

        while is_running:
            len_bytes = sock.recv(4)
            if not len_bytes or len(len_bytes) != 4:
                break
            frame_len = struct.unpack(">I", len_bytes)[0]
            if frame_len <= 0 or frame_len > 1_000_000:
                continue

            buf = bytearray()
            while len(buf) < frame_len and is_running:
                part = sock.recv(min(4096, frame_len - len(buf)))
                if not part:
                    break
                buf.extend(part)

            if len(buf) == frame_len:
                arr = np.frombuffer(buf, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    with frame_lock:
                        latest_frame = img
    except Exception as e:
        print(f"[CAM INFO] ESP32-CAM ({ESP32_CAM_IP}) offline/tidak ditemukan ({e}). Menggunakan Webcam lokal...")
    finally:
        if sock:
            try: sock.close()
            except Exception: pass

    # Fallback ke Webcam jika ESP32-CAM tidak terhubung
    cap = cv2.VideoCapture(0)
    while is_running:
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                with frame_lock:
                    latest_frame = frame
                time.sleep(0.03)
                continue

        # Fallback sintetis jika tidak ada webcam sama sekali
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        dummy[:] = (40, 45, 50)
        cv2.putText(dummy, "KAMERA STANDBY (KLIK/DRAG UNTUK KALIBRASI)", (50, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 2)
        with frame_lock:
            latest_frame = dummy
        time.sleep(0.05)


# ── Handler Mouse (Klik dan Drag Titik) ──
def mouse_callback(event, mx, my, flags, param):
    global active_edit_mode, new_click_points, dragging_item, mouse_hover_pos, toast_message, toast_time
    if latest_frame is None:
        return

    fh, fw = latest_frame.shape[:2]
    norm_x = round(float(np.clip(mx / fw, 0.0, 1.0)), 3)
    norm_y = round(float(np.clip(my / fh, 0.0, 1.0)), 3)
    mouse_hover_pos = (mx, my)

    # 1. Mode Menandai 4 Titik Poligon Area Baru [1] atau [2]
    if active_edit_mode in ("area1", "area2") and event == cv2.EVENT_LBUTTONDOWN:
        p_names = ["P1 (Kiri Atas)", "P2 (Kanan Atas)", "P3 (Kanan Bawah)", "P4 (Kiri Bawah)"]
        p_idx = len(new_click_points)
        new_click_points.append({
            "name": p_names[p_idx],
            "x": norm_x,
            "y": norm_y
        })
        toast_message = f"{active_edit_mode.upper()}: Titik {p_idx+1}/4 ({p_names[p_idx]}) ditandai"
        toast_time = time.time()

        if len(new_click_points) == 4:
            current_config[active_edit_mode]["points"] = new_click_points.copy()
            toast_message = f"✅ 4 Titik Poligon {active_edit_mode.upper()} Selesai!"
            toast_time = time.time()
            active_edit_mode = None
            new_click_points = []
            save_config()
        return

    # 2. Mode Menandai 2 Titik Sudut Servo [3] atau [4] (0° dan 90°)
    if active_edit_mode in ("servo1", "servo2") and event == cv2.EVENT_LBUTTONDOWN:
        ak = "area1" if active_edit_mode == "servo1" else "area2"
        s_label = "Servo 1" if ak == "area1" else "Servo 2"

        if len(new_click_points) == 0:
            # Klik pertama = Titik 0 Derajat
            new_click_points.append({"x": norm_x, "y": norm_y})
            toast_message = f"📍 {s_label}: Titik 0° ditandai! Klik titik ke-2 untuk 90°"
            toast_time = time.time()
        elif len(new_click_points) == 1:
            # Klik kedua = Titik 90 Derajat
            p0_norm = new_click_points[0]
            current_config[ak]["servo_points"]["p0"]["x"] = p0_norm["x"]
            current_config[ak]["servo_points"]["p0"]["y"] = p0_norm["y"]
            current_config[ak]["servo_points"]["p90"]["x"] = norm_x
            current_config[ak]["servo_points"]["p90"]["y"] = norm_y

            toast_message = f"✅ Garis Sudut 0° - 90° {s_label} Selesai & Disimpan!"
            toast_time = time.time()
            active_edit_mode = None
            new_click_points = []
            save_config()
        return

    # 3. Mode Drag / Geser Titik Langsung dengan Mouse
    if event == cv2.EVENT_LBUTTONDOWN and active_edit_mode is None:
        # Prioritas 1: Cek apakah klik berada di titik sudut servo (p0 atau p90)
        for ak in ["area1", "area2"]:
            s_pts = current_config[ak].get("servo_points", {})
            for pk in ["p0", "p90"]:
                if pk in s_pts:
                    px = int(s_pts[pk]["x"] * fw)
                    py = int(s_pts[pk]["y"] * fh)
                    if np.hypot(mx - px, my - py) <= 18:
                        dragging_item = ("servo", ak, pk)
                        toast_message = f"Menggeser Sudut: {s_pts[pk]['name']}"
                        toast_time = time.time()
                        return

        # Prioritas 2: Cek apakah klik berada di titik poligon area (P1..P4)
        for ak in ["area1", "area2"]:
            pts = current_config[ak].get("points", [])
            for i, p in enumerate(pts):
                px = int(p["x"] * fw)
                py = int(p["y"] * fh)
                if np.hypot(mx - px, my - py) <= 18:
                    dragging_item = ("polygon", ak, i)
                    toast_message = f"Menggeser Titik Poligon: {ak.upper()} - {p['name']}"
                    toast_time = time.time()
                    return

    elif event == cv2.EVENT_MOUSEMOVE:
        if dragging_item is not None:
            dtype, ak, key_or_idx = dragging_item
            if dtype == "servo":
                current_config[ak]["servo_points"][key_or_idx]["x"] = norm_x
                current_config[ak]["servo_points"][key_or_idx]["y"] = norm_y
            elif dtype == "polygon":
                current_config[ak]["points"][key_or_idx]["x"] = norm_x
                current_config[ak]["points"][key_or_idx]["y"] = norm_y

    elif event == cv2.EVENT_LBUTTONUP:
        if dragging_item is not None:
            dragging_item = None
            save_config()
            toast_message = "✅ Titik berhasil digeser dan disimpan!"
            toast_time = time.time()


def main():
    global is_running, active_edit_mode, new_click_points, current_config, toast_message, toast_time

    load_config()

    print("=" * 75)
    print(" 📍 ALAT KALIBRASI INTERAKTIF: AREA & SUDUT SERVO (0° - 90°)")
    print("=" * 75)
    print("Area 1 (Servo 1 GPIO 16, Relay 1 GPIO 25)")
    print("Area 2 (Servo 2 GPIO 17, Relay 2 GPIO 26)")
    print("-" * 75)
    print("CARA MEMBERI SUDUT 0° DAN 90°:")
    print("  Cara 1: Tekan [3] (Servo 1) atau [4] (Servo 2), lalu:")
    print("          - Klik ke-1 pada layar = Titik sudut 0°")
    print("          - Klik ke-2 pada layar = Titik sudut 90°")
    print("  Cara 2: Geser langsung lingkaran 0° atau 90° menggunakan mouse (Drag & Drop)")
    print("-" * 75)
    print("KONTROL KEYBOARD:")
    print("  [1]     : Buat 4 titik poligon AREA 1 (Kiri Atas->Kanan Atas->Kanan Bawah->Kiri Bawah)")
    print("  [2]     : Buat 4 titik poligon AREA 2")
    print("  [3]     : Tentukan Garis Sudut SERVO 1 (Titik 1 = 0°, Titik 2 = 90°)")
    print("  [4]     : Tentukan Garis Sudut SERVO 2 (Titik 1 = 0°, Titik 2 = 90°)")
    print("  [Mouse] : Klik & tarik titik manapun di layar langsung")
    print("  [S]     : Simpan konfigurasi")
    print("  [R]     : Reset ke default")
    print("  [Q/ESC] : Simpan & Keluar")
    print("=" * 75)

    # Mulai thread kamera
    cam_thread = threading.Thread(target=camera_worker, daemon=True)
    cam_thread.start()

    window_name = "AIoT Forest - Kalibrasi Area & Sudut Servo (0-90)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1020, 680)
    cv2.setMouseCallback(window_name, mouse_callback)

    while is_running:
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None

        if frame is None:
            time.sleep(0.03)
            continue

        h, w = frame.shape[:2]
        canvas = frame.copy()
        overlay = canvas.copy()

        # ── 1. GAMBAR POLIGON DAN 4 TITIK AREA 1 (Cyan/Biru) ──
        pts1 = []
        for p in current_config["area1"]["points"]:
            pts1.append([int(p["x"] * w), int(p["y"] * h)])
        pts1 = np.array(pts1, dtype=np.int32)

        if len(pts1) == 4:
            cv2.fillPoly(overlay, [pts1], (80, 50, 0))
            cv2.polylines(canvas, [pts1], True, (255, 200, 0), 2, cv2.LINE_AA)
            for i, pt in enumerate(pts1):
                cv2.circle(canvas, tuple(pt), 7, (255, 200, 0), -1)
                cv2.circle(canvas, tuple(pt), 10, (255, 255, 255), 2)
                p_label = f"1:P{i+1}"
                cv2.putText(canvas, p_label, (pt[0] + 10, pt[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(canvas, p_label, (pt[0] + 10, pt[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 0), 1, cv2.LINE_AA)

            top1 = pts1[np.argmin(pts1[:, 1])]
            cv2.putText(canvas, "AREA 1 (Servo 1 [GPIO 16])", (max(10, top1[0] - 10), max(20, top1[1] - 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 220, 0), 2, cv2.LINE_AA)

        # ── 2. GAMBAR POLIGON DAN 4 TITIK AREA 2 (Oranye) ──
        pts2 = []
        for p in current_config["area2"]["points"]:
            pts2.append([int(p["x"] * w), int(p["y"] * h)])
        pts2 = np.array(pts2, dtype=np.int32)

        if len(pts2) == 4:
            cv2.fillPoly(overlay, [pts2], (0, 40, 90))
            cv2.polylines(canvas, [pts2], True, (0, 165, 255), 2, cv2.LINE_AA)
            for i, pt in enumerate(pts2):
                cv2.circle(canvas, tuple(pt), 7, (0, 165, 255), -1)
                cv2.circle(canvas, tuple(pt), 10, (255, 255, 255), 2)
                p_label = f"2:P{i+1}"
                cv2.putText(canvas, p_label, (pt[0] + 10, pt[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(canvas, p_label, (pt[0] + 10, pt[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1, cv2.LINE_AA)

            top2 = pts2[np.argmin(pts2[:, 1])]
            cv2.putText(canvas, "AREA 2 (Servo 2 [GPIO 17])", (max(10, top2[0] - 10), max(20, top2[1] - 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 165, 255), 2, cv2.LINE_AA)

        cv2.addWeighted(overlay, 0.22, canvas, 0.78, 0, canvas)

        # ── 3. GAMBAR GARIS KALIBRASI SUDUT SERVO 1 (0° - 90°) [Neon Yellow/Green] ──
        s1_pts = current_config["area1"].get("servo_points", {})
        if "p0" in s1_pts and "p90" in s1_pts:
            x0 = int(s1_pts["p0"]["x"] * w)
            y0 = int(s1_pts["p0"]["y"] * h)
            x1 = int(s1_pts["p90"]["x"] * w)
            y1 = int(s1_pts["p90"]["y"] * h)

            # Garis utama sumbu sudut S1
            cv2.line(canvas, (x0, y0), (x1, y1), (0, 255, 255), 2, cv2.LINE_AA)
            # Titik tengah 45°
            mx, my = (x0 + x1) // 2, (y0 + y1) // 2
            cv2.circle(canvas, (mx, my), 5, (0, 255, 255), -1)
            cv2.putText(canvas, "45°", (mx + 6, my - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)

            # Titik 0 Derajat
            cv2.circle(canvas, (x0, y0), 9, (0, 255, 255), -1)
            cv2.circle(canvas, (x0, y0), 12, (255, 255, 255), 2)
            cv2.putText(canvas, "S1: 0°", (x0 - 15, y0 - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(canvas, "S1: 0°", (x0 - 15, y0 - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 255), 2, cv2.LINE_AA)

            # Titik 90 Derajat
            cv2.circle(canvas, (x1, y1), 9, (0, 200, 255), -1)
            cv2.circle(canvas, (x1, y1), 12, (255, 255, 255), 2)
            cv2.putText(canvas, "S1: 90°", (x1 + 8, y1 - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(canvas, "S1: 90°", (x1 + 8, y1 - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 200, 255), 2, cv2.LINE_AA)

        # ── 4. GAMBAR GARIS KALIBRASI SUDUT SERVO 2 (0° - 90°) [Neon Magenta/Pink] ──
        s2_pts = current_config["area2"].get("servo_points", {})
        if "p0" in s2_pts and "p90" in s2_pts:
            x0 = int(s2_pts["p0"]["x"] * w)
            y0 = int(s2_pts["p0"]["y"] * h)
            x1 = int(s2_pts["p90"]["x"] * w)
            y1 = int(s2_pts["p90"]["y"] * h)

            # Garis utama sumbu sudut S2
            cv2.line(canvas, (x0, y0), (x1, y1), (255, 100, 255), 2, cv2.LINE_AA)
            # Titik tengah 45°
            mx, my = (x0 + x1) // 2, (y0 + y1) // 2
            cv2.circle(canvas, (mx, my), 5, (255, 100, 255), -1)
            cv2.putText(canvas, "45°", (mx + 6, my - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 100, 255), 1, cv2.LINE_AA)

            # Titik 0 Derajat
            cv2.circle(canvas, (x0, y0), 9, (255, 100, 255), -1)
            cv2.circle(canvas, (x0, y0), 12, (255, 255, 255), 2)
            cv2.putText(canvas, "S2: 0°", (x0 - 15, y0 - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(canvas, "S2: 0°", (x0 - 15, y0 - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 100, 255), 2, cv2.LINE_AA)

            # Titik 90 Derajat
            cv2.circle(canvas, (x1, y1), 9, (220, 50, 220), -1)
            cv2.circle(canvas, (x1, y1), 12, (255, 255, 255), 2)
            cv2.putText(canvas, "S2: 90°", (x1 + 8, y1 - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(canvas, "S2: 90°", (x1 + 8, y1 - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (220, 50, 220), 2, cv2.LINE_AA)

        # ── 5. INDIKATOR PREDIKSI SUDUT REAL-TIME SAAT KURSOR DIGERAKKAN ──
        hx, hy = mouse_hover_pos
        ang1 = compute_projected_angle(hx, hy, current_config["area1"]["servo_points"], w, h)
        ang2 = compute_projected_angle(hx, hy, current_config["area2"]["servo_points"], w, h)

        # ── 6. GAMBAR TITIK KLIK BARU JIKA SEDANG DALAM MODE KLIK BERURUTAN ──
        if active_edit_mode and new_click_points:
            for i, p in enumerate(new_click_points):
                px, py = int(p["x"] * w), int(p["y"] * h)
                cv2.circle(canvas, (px, py), 9, (0, 255, 0), -1)
                lbl_t = f"Titik #{i+1} (0°)" if i == 0 and "servo" in active_edit_mode else f"Titik #{i+1}"
                cv2.putText(canvas, lbl_t, (px + 10, py - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 0), 2)

        # ── 7. HEADER & PANDUAN PENGGUNA ──
        cv2.rectangle(canvas, (0, 0), (w, 62), (18, 18, 18), -1)
        cv2.line(canvas, (0, 62), (w, 62), (60, 60, 60), 1)

        if active_edit_mode:
            if active_edit_mode == "servo1":
                status_txt = f"⚙️ MENANDAI GARIS SUDUT SERVO 1 ({len(new_click_points)}/2) -> KLIK KE-{len(new_click_points)+1}: {'TITIK 0°' if len(new_click_points)==0 else 'TITIK 90°'}"
                color_st = (0, 255, 255)
            elif active_edit_mode == "servo2":
                status_txt = f"⚙️ MENANDAI GARIS SUDUT SERVO 2 ({len(new_click_points)}/2) -> KLIK KE-{len(new_click_points)+1}: {'TITIK 0°' if len(new_click_points)==0 else 'TITIK 90°'}"
                color_st = (255, 100, 255)
            else:
                status_txt = f"📍 MENANDAI POLIGON {active_edit_mode.upper()} ({len(new_click_points)}/4 TITIK)"
                color_st = (0, 255, 150)
        else:
            status_txt = f"MODE BEBAS (DRAG TITIK) | Kursor Simulasi -> S1: {ang1}° | S2: {ang2}°"
            color_st = (210, 210, 210)

        cv2.putText(canvas, status_txt, (14, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.50, color_st, 1, cv2.LINE_AA)

        hint_keys = "[1] Area 1 (4pt) | [2] Area 2 (4pt) | [3] Sudut S1 (0°-90°) | [4] Sudut S2 (0°-90°) | [Drag] Geser | [S] Simpan | [Q] Keluar"
        cv2.putText(canvas, hint_keys, (14, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (150, 210, 255), 1, cv2.LINE_AA)

        # ── 8. TOAST NOTIFIKASI DI BAGIAN BAWAH ──
        if toast_message and (time.time() - toast_time) < 3.2:
            (tw, th), _ = cv2.getTextSize(toast_message, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            tx = (w - tw) // 2
            ty = h - 25
            cv2.rectangle(canvas, (tx - 15, ty - th - 10), (tx + tw + 15, ty + 10), (10, 10, 10), -1)
            cv2.rectangle(canvas, (tx - 15, ty - th - 10), (tx + tw + 15, ty + 10), (0, 255, 140), 2)
            cv2.putText(canvas, toast_message, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 140), 2, cv2.LINE_AA)

        cv2.imshow(window_name, canvas)
        key = cv2.waitKey(20) & 0xFF

        if key in (ord('q'), ord('Q'), 27):
            save_config()
            break
        elif key == ord('1'):
            active_edit_mode = "area1"
            new_click_points = []
            toast_message = "Area 1: Klik 4 titik (Kiri Atas -> Kanan Atas -> Kanan Bawah -> Kiri Bawah)"
            toast_time = time.time()
            print("\n[+] Mode Poligon Area 1 aktif. Klik 4 titik berurutan di layar.")
        elif key == ord('2'):
            active_edit_mode = "area2"
            new_click_points = []
            toast_message = "Area 2: Klik 4 titik (Kiri Atas -> Kanan Atas -> Kanan Bawah -> Kiri Bawah)"
            toast_time = time.time()
            print("\n[+] Mode Poligon Area 2 aktif. Klik 4 titik berurutan di layar.")
        elif key == ord('3'):
            active_edit_mode = "servo1"
            new_click_points = []
            toast_message = "Servo 1: Klik Titik ke-1 untuk Sudut 0°, lalu Titik ke-2 untuk Sudut 90°"
            toast_time = time.time()
            print("\n[+] Mode Sudut Servo 1 aktif:")
            print("    1. Klik titik lokasi sudut 0° pada layar")
            print("    2. Klik titik lokasi sudut 90° pada layar")
        elif key == ord('4'):
            active_edit_mode = "servo2"
            new_click_points = []
            toast_message = "Servo 2: Klik Titik ke-1 untuk Sudut 0°, lalu Titik ke-2 untuk Sudut 90°"
            toast_time = time.time()
            print("\n[+] Mode Sudut Servo 2 aktif:")
            print("    1. Klik titik lokasi sudut 0° pada layar")
            print("    2. Klik titik lokasi sudut 90° pada layar")
        elif key in (ord('s'), ord('S')):
            save_config()
        elif key in (ord('r'), ord('R')):
            current_config["area1"]["points"] = DEFAULT_POINTS["area1"]
            current_config["area2"]["points"] = DEFAULT_POINTS["area2"]
            current_config["area1"]["servo_points"] = DEFAULT_SERVO_POINTS["area1"]
            current_config["area2"]["servo_points"] = DEFAULT_SERVO_POINTS["area2"]
            save_config()
            toast_message = "Titik Area & Sudut Servo di-reset ke default!"
            toast_time = time.time()

    is_running = False
    cv2.destroyAllWindows()
    print("\n[SELESAI] Kalibrasi area dan sudut servo selesai.")


if __name__ == "__main__":
    main()
