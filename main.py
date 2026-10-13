"""
=============================================================
  AIoT Forest Protection -- Main Program
  (Presisi Sudut 0°-90°, Anti-Kedip, & Mode Ganti-Gantian)
=============================================================
  Fitur Utama:
    1. Kalibrasi Sudut 0° dan 90° untuk Servo 1 & Servo 2:
       - Titik 0° dan 90° tampil di layar (S1 Cyan, S2 Magenta)
       - Anda bisa KLIK & TARIK (drag) titik tersebut langsung dengan mouse!
       - Sudut servo diprediksi proporsional antara titik 0° dan 90°
    2. Mode Ganti-Gantian (Mutual Exclusion):
       - Hanya SATU servo & pompa yang aktif dalam satu waktu
       - Jika kedua area ada api, sistem menyemprot ganti-gantian (2.5 detik per area)
       - Arus listrik tidak akan drop dan ESP32 tidak akan reset!
    3. Stabilizer & Anti-Kedip:
       - Bounding box stabil persis seperti test_model.py
       - Hold-time 1.3 detik mencegah kedipan dan flicker

  Kontrol Keyboard:
    [Mouse]   : Klik & geser titik 'S1: 0°', 'S1: 90°', 'S2: 0°', 'S2: 90°'
    [S]       : Simpan posisi titik kalibrasi ke file JSON
    [+] / [-] : Ubah ambang batas keyakinan (Confidence %)
    [1]       : Test toggle Servo 1 (45° <-> 135°)
    [2]       : Test toggle Servo 2 (45° <-> 135°)
    [R]       : Test toggle Relay Pompa (ON / OFF)
    [B]       : Test Buzzer Beep
    [C]       : Reload konfigurasi dari file
    [Q] / ESC : Keluar
=============================================================
"""

import sys, socket, struct, threading, time, json, os, subprocess
import cv2, numpy as np

# =============================================================
#  KONFIGURASI IP (UBAH DI SINI AKAN OTOMATIS SINKRON KE SEMUA SCRIPT!)
# =============================================================
ESP32_MAIN_IP  = "10.175.157.151"   # IP ESP32 Main (Servo, Relay, Buzzer)
ESP32_CAM_IP   = "10.175.157.25"   # IP ESP32-CAM (Video Stream)
ESP32_MAIN_PORT = 8888
ESP32_CAM_PORT  = 80
# =============================================================

# Dukungan argumen CLI cepat: python main.py 192.168.4.3 192.168.4.2
if len(sys.argv) > 1 and "." in sys.argv[1]:
    ESP32_MAIN_IP = sys.argv[1].strip()
if len(sys.argv) > 2 and "." in sys.argv[2]:
    ESP32_CAM_IP = sys.argv[2].strip()

# Simpan otomatis ke konfigurasi sentral (agar server.py, calibrate_zones.py, test_model.py otomatis sama!)
try:
    from network_config import save_network_config
    save_network_config(ESP32_MAIN_IP, ESP32_CAM_IP, ESP32_MAIN_PORT, ESP32_CAM_PORT)
except Exception:
    pass

# Sistem Notifikasi Email Darurat Damkar
try:
    from email_notifier import send_fire_alert_email_async
except Exception:
    def send_fire_alert_email_async(*args, **kwargs): pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ZONES_CONFIG_PATHS = [
    os.path.join(BASE_DIR, "data", "zones_config.json"),
    os.path.join(BASE_DIR, "python_backend", "data", "zones_config.json")
]
MODEL_PATH = os.path.join(BASE_DIR, "runs", "detect", "runs", "forest_ai", "forest_protection_model", "weights", "best.pt")
CONF_THRESHOLD = 0.45

# ---- Network check ----
def check_network(ip):
    try:
        r = subprocess.run(["ping", "-n", "1", "-w", "1000", ip], capture_output=True, timeout=5)
        return r.returncode == 0
    except: return False

# ---- Load YOLO ----
def load_yolo():
    try:
        from ultralytics import YOLO
        if not os.path.exists(MODEL_PATH):
            print("[YOLO] Model belum ditemukan di runs/, pakai fallback deteksi warna api")
            return None
        model = YOLO(MODEL_PATH)
        print(f"[YOLO] Model berhasil dimuat: {MODEL_PATH}")
        print(f"[YOLO] Kelas model: {list(model.names.values())}")
        return model
    except ImportError:
        print("[YOLO] ultralytics tidak terinstall, pakai fallback deteksi warna")
        return None

# ---- Load / Save zones & servo calibration ----
DEFAULT_CONFIG = {
    "version": "1.0",
    "area1": {
        "name": "Area 1",
        "servo": 1,
        "servo_points": {
            "p0":  {"name": "S1: 0°",  "x": 0.050, "y": 0.540, "angle": 0},
            "p90": {"name": "S1: 90°", "x": 0.450, "y": 0.350, "angle": 90}
        },
        "points": [
            {"name": "P1", "x": 0.319, "y": 0.267},
            {"name": "P2", "x": 0.512, "y": 0.417},
            {"name": "P3", "x": 0.153, "y": 0.812},
            {"name": "P4", "x": 0.000, "y": 0.546}
        ]
    },
    "area2": {
        "name": "Area 2",
        "servo": 2,
        "servo_points": {
            "p0":  {"name": "S2: 0°",  "x": 0.250, "y": 0.870, "angle": 0},
            "p90": {"name": "S2: 90°", "x": 0.800, "y": 0.650, "angle": 90}
        },
        "points": [
            {"name": "P1", "x": 0.575, "y": 0.479},
            {"name": "P2", "x": 0.812, "y": 0.683},
            {"name": "P3", "x": 0.522, "y": 1.000},
            {"name": "P4", "x": 0.212, "y": 0.867}
        ]
    }
}

def load_zones():
    for p in ZONES_CONFIG_PATHS:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Pastikan struktur servo_points ada
                    for ak in ["area1", "area2"]:
                        if "servo_points" not in data.get(ak, {}):
                            data[ak]["servo_points"] = DEFAULT_CONFIG[ak]["servo_points"]
                    print(f"[ZONE] Berhasil memuat area & kalibrasi sudut dari: {p}")
                    return data
            except Exception as e:
                print(f"[ZONE] Gagal membaca {p}: {e}")
    print("[ZONE] Menggunakan konfigurasi default")
    return DEFAULT_CONFIG

def save_zones_to_disk(cfg_data):
    for p in ZONES_CONFIG_PATHS:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cfg_data, f, indent=2)
            print(f"[ZONE] Konfigurasi berhasil disimpan ke {p}")
        except Exception as e:
            print(f"[ZONE ERROR] Gagal simpan ke {p}: {e}")

def get_poly(zones, key, w, h):
    pts = zones.get(key, {}).get("points", [])
    return np.array([[int(p["x"]*w), int(p["y"]*h)] for p in pts], dtype=np.int32)

def in_zone_dist(cx, cy, poly):
    if len(poly) < 3: return -999.0
    return cv2.pointPolygonTest(poly, (float(cx), float(cy)), True)

def compute_calibrated_angle(cx, cy, servo_pts, default_poly=None, w=640, h=480):
    """
    Menghitung sudut servo (0° - 90°) berdasarkan proyeksi vektor api (cx, cy)
    terhadap garis kalibrasi P_0deg dan P_90deg.
    """
    if not servo_pts or "p0" not in servo_pts or "p90" not in servo_pts:
        if default_poly is not None and len(default_poly) >= 3:
            min_x = np.min(default_poly[:, 0])
            max_x = np.max(default_poly[:, 0])
            span = max(1, max_x - min_x)
            r = np.clip((cx - min_x) / span, 0.0, 1.0)
            return int(r * 90)
        return 90

    p0 = servo_pts["p0"]
    p90 = servo_pts["p90"]
    x0, y0 = p0["x"] * w, p0["y"] * h
    x1, y1 = p90["x"] * w, p90["y"] * h

    dx = x1 - x0
    dy = y1 - y0
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1.0:
        return 45

    # Proyeksi vektor titik api (cx, cy) ke ruas garis (x0, y0) -> (x1, y1)
    u_x = cx - x0
    u_y = cy - y0
    t = (u_x * dx + u_y * dy) / seg_len_sq
    t_clamped = np.clip(t, 0.0, 1.0)

    angle_min = p0.get("angle", 0)
    angle_max = p90.get("angle", 90)
    calc_angle = int(round(angle_min + t_clamped * (angle_max - angle_min)))
    return int(np.clip(calc_angle, 0, 180)), (int(x0 + t_clamped * dx), int(y0 + t_clamped * dy))

# ---- TCP Camera ----
frame_queue, frame_lock = [], threading.Lock()
cam_connected = False

def recv_exact(s, n):
    data = b""
    while len(data) < n:
        try:
            pkt = s.recv(n - len(data))
            if not pkt: return None
            data += pkt
        except: return None
    return data

def cam_thread():
    global cam_connected
    while True:
        sock = None
        try:
            if not check_network(ESP32_CAM_IP):
                print(f"\n[CAM] {ESP32_CAM_IP} tidak terjangkau -- Sambungkan WiFi 'Absolute Solver'!")
                time.sleep(4); continue
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((ESP32_CAM_IP, ESP32_CAM_PORT))
            sock.settimeout(15)
            cam_connected = True
            print(f"[CAM] Terhubung ke {ESP32_CAM_IP}:{ESP32_CAM_PORT}!")
            while True:
                lb = recv_exact(sock, 4)
                if not lb: break
                fl = struct.unpack(">I", lb)[0]
                if fl == 0 or fl > 1000000: continue
                jd = recv_exact(sock, fl)
                if not jd: break
                with frame_lock:
                    frame_queue.clear()
                    frame_queue.append(jd)
        except Exception:
            pass
        finally:
            cam_connected = False
            if sock:
                try: sock.close()
                except: pass
        time.sleep(2)

# ---- TCP ESP32 Main ----
esp_sock, esp_lock = None, threading.Lock()
esp_connected = False

def esp_thread():
    global esp_sock, esp_connected
    while True:
        with esp_lock:
            already = esp_sock is not None
        if not already:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.settimeout(3)
                s.connect((ESP32_MAIN_IP, ESP32_MAIN_PORT))
                s.settimeout(None)
                with esp_lock:
                    esp_sock = s
                    esp_connected = True
                print(f"[ESP32] Terhubung ke {ESP32_MAIN_IP}:{ESP32_MAIN_PORT}!")
                buf = ""
                while True:
                    data = s.recv(256)
                    if not data: break
                    buf += data.decode("utf-8", errors="ignore")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            try:
                                d = json.loads(line)
                                print(f"\r[SENSOR] Jarak:{d.get('distance_cm',0):.1f}cm FlamePin:{d.get('flame_pin',1)}   ", end="")
                            except: pass
            except ConnectionRefusedError: pass
            except OSError: pass
            except Exception: pass
            finally:
                with esp_lock:
                    esp_sock = None
                    esp_connected = False
        time.sleep(2)

def send_cmd(cmd):
    with esp_lock: s = esp_sock
    if s:
        try:
            payload = (json.dumps(cmd) + "\n").encode()
            s.sendall(payload)
            return True
        except:
            with esp_lock:
                globals()["esp_sock"] = None
                globals()["esp_connected"] = False
    return False

# ---- Deteksi warna api (fallback) ----
def detect_fire_color(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0, 100, 200]), np.array([25, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([170, 100, 200]), np.array([180, 255, 255]))
    cnts, _ = cv2.findContours(cv2.bitwise_or(m1, m2), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dets = []
    for c in cnts:
        if cv2.contourArea(c) < 250: continue
        x, y, w, h = cv2.boundingRect(c)
        dets.append({
            "label": "Api",
            "class_id": 2,
            "bbox": [x, y, x+w, y+h],
            "center": [x+w//2, y+h//2],
            "confidence": 0.85
        })
    return dets

def detect_yolo(model, frame, conf_thresh=0.45):
    results = model.predict(source=frame, verbose=False, imgsz=320, conf=conf_thresh)
    dets = []
    if not results: return dets
    for box in (results[0].boxes or []):
        conf = float(box.conf[0].item())
        cls_id = int(box.cls[0].item())
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
        lbl = model.names.get(cls_id, f"Kelas {cls_id}")
        dets.append({
            "label": lbl,
            "class_id": cls_id,
            "bbox": [x1, y1, x2, y2],
            "center": [(x1+x2)//2, (y1+y2)//2],
            "confidence": conf
        })
    return dets

# Global state untuk drag mouse
dragging_target = None  # ("area1", "p0"), ("area1", "p90"), ("area2", "p0"), ("area2", "p90")
toast_message = ""
toast_time = 0.0

def mouse_callback(event, mx, my, flags, param):
    global dragging_target, toast_message, toast_time
    zones = param.get("zones")
    w = param.get("w", 640)
    h = param.get("h", 480)

    norm_x = round(float(np.clip(mx / max(1, w), 0.0, 1.0)), 3)
    norm_y = round(float(np.clip(my / max(1, h), 0.0, 1.0)), 3)

    if event == cv2.EVENT_LBUTTONDOWN:
        for area_key in ["area1", "area2"]:
            s_pts = zones.get(area_key, {}).get("servo_points", {})
            for pt_key in ["p0", "p90"]:
                if pt_key in s_pts:
                    px = int(s_pts[pt_key]["x"] * w)
                    py = int(s_pts[pt_key]["y"] * h)
                    if np.hypot(mx - px, my - py) <= 20:
                        dragging_target = (area_key, pt_key)
                        toast_message = f"Menggeser Titik {s_pts[pt_key]['name']}"
                        toast_time = time.time()
                        return

    elif event == cv2.EVENT_MOUSEMOVE:
        if dragging_target is not None:
            area_key, pt_key = dragging_target
            zones[area_key]["servo_points"][pt_key]["x"] = norm_x
            zones[area_key]["servo_points"][pt_key]["y"] = norm_y

    elif event == cv2.EVENT_LBUTTONUP:
        if dragging_target is not None:
            area_key, pt_key = dragging_target
            dragging_target = None
            save_zones_to_disk(zones)
            toast_message = f"✅ Posisi Titik Sudut Disimpan!"
            toast_time = time.time()

# ---- Draw zones & Servo Angle Lines ----
def draw_zones_and_angles(frame, zones, w, h):
    # 1. Gambar Poligon Area (Hijau & Biru redup)
    cfg_zones = [("area1", "AREA 1 (Servo 1)", (0, 220, 80)), ("area2", "AREA 2 (Servo 2)", (80, 120, 255))]
    for key, lbl, color in cfg_zones:
        poly = get_poly(zones, key, w, h)
        if len(poly) < 3: continue
        ov = frame.copy()
        cv2.fillPoly(ov, [poly], color)
        cv2.addWeighted(ov, 0.12, frame, 0.88, 0, frame)
        cv2.polylines(frame, [poly], True, color, 1, cv2.LINE_AA)

    # 2. Gambar Garis Referensi Sudut Servo 0° - 90° (Cyan untuk S1, Magenta untuk S2)
    cfg_angles = [
        ("area1", (255, 230, 0), "S1"),    # Kuning/Cyan
        ("area2", (255, 100, 255), "S2")   # Magenta
    ]
    for key, color, prefix in cfg_angles:
        s_pts = zones.get(key, {}).get("servo_points", {})
        if "p0" in s_pts and "p90" in s_pts:
            p0 = s_pts["p0"]
            p90 = s_pts["p90"]
            x0, y0 = int(p0["x"] * w), int(p0["y"] * h)
            x1, y1 = int(p90["x"] * w), int(p90["y"] * h)

            # Garis penghubung 0° ke 90°
            cv2.line(frame, (x0, y0), (x1, y1), color, 2, cv2.LINE_AA)

            # Titik tengah (45°)
            mid_x, mid_y = (x0 + x1) // 2, (y0 + y1) // 2
            cv2.circle(frame, (mid_x, mid_y), 3, (255, 255, 255), -1)
            cv2.putText(frame, "45°", (mid_x + 5, mid_y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (220, 220, 220), 1)

            # Titik P0 (0°)
            cv2.circle(frame, (x0, y0), 8, color, -1)
            cv2.circle(frame, (x0, y0), 10, (255, 255, 255), 1)
            cv2.putText(frame, f"{prefix}: 0°", (x0 - 15, y0 - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 2)

            # Titik P90 (90°)
            cv2.circle(frame, (x1, y1), 8, color, -1)
            cv2.circle(frame, (x1, y1), 10, (255, 255, 255), 1)
            cv2.putText(frame, f"{prefix}: 90°", (x1 + 10, y1 + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 2)

    return frame

# ---- Main ----
def main():
    global CONF_THRESHOLD, toast_message, toast_time
    print("=" * 65)
    print("  🌲 AIoT Forest Protection -- Calibrated Angle & Alternating System")
    print("=" * 65)
    print(f"  ESP32 Main : {ESP32_MAIN_IP}:{ESP32_MAIN_PORT}")
    print(f"  ESP32-CAM  : {ESP32_CAM_IP}:{ESP32_CAM_PORT}")
    print("  Fitur Khusus:")
    print("    - Titik Sudut 0° dan 90° bisa DIGESER langsung pakai Mouse di layar!")
    print("    - Mode Ganti-Gantian: Arus aman, pompa & servo tidak tabrakan")
    print("  Tombol Keyboard:")
    print("    [S]       : Simpan Titik Sudut Kalibrasi")
    print("    [+] / [-] : Ubah Ambang Batas Keyakinan (Confidence %)")
    print("    [1]       : Test Toggle Servo 1 (45° / 135°)")
    print("    [2]       : Test Toggle Servo 2 (45° / 135°)")
    print("    [R]       : Test Toggle Relay Pompa 1 & 2")
    print("    [B]       : Test Buzzer Beep")
    print("    [C]       : Reload Titik Kalibrasi")
    print("    [Q] / ESC : Keluar")
    print("=" * 65)

    yolo_model = load_yolo()
    zones = load_zones()

    threading.Thread(target=cam_thread, daemon=True).start()
    threading.Thread(target=esp_thread, daemon=True).start()

    # --- STATE DEBOUNCE, SUDUT TERKUNCI & INTERVAL 2 DETIK ---
    FIRE_HOLD_SECONDS     = 1.5   # Tahan status api 1.5 detik agar tidak berkedip
    ANGLE_UPDATE_INTERVAL = 2.0   # Update sudut hanya tiap 2 detik jika api berpindah
    ANGLE_DEADBAND        = 8     # Perpindahan minimal 8° agar servo tidak jitter

    last_fire_time_1      = 0.0
    last_fire_time_2      = 0.0

    is_fire_locked_1      = False
    is_fire_locked_2      = False
    locked_angle_1        = 90
    locked_angle_2        = 90
    last_angle_update_1   = 0.0
    last_angle_update_2   = 0.0

    sent_angle_1          = 90
    sent_angle_2          = 90
    last_sent_z1_active   = False
    last_sent_z2_active   = False

    # Sistem Email Peringatan Damkar (Terkirim 1x jika api > 15 detik)
    FIRE_EMAIL_TIMEOUT    = 15.0  # Batas durasi 15 detik api tak kunjung padam
    fire_start_time       = None  # Waktu mulai api aktif kontinu
    fire_email_sent       = False # Flag anti-spam: hanya kirim sekali per insiden

    last_cmd_time         = 0.0
    last_yolo_time        = 0.0
    current_dets          = []

    # Kontrol Pergantian Bergantian (Time-shared Alternating Mode)
    CYCLE_DURATION    = 2.6   # Semprot tiap area selama 2.6 detik jika dua-duanya ada api
    PAUSE_SETTLE_TIME = 0.25  # Jeda 0.25 detik tanpa pompa sebelum pindah (stabilkan arus)
    alternating_turn  = 1     # 1 = Giliran Area 1, 2 = Giliran Area 2
    turn_start_time   = time.time()
    is_pausing_turn   = False
    pause_start_time  = 0.0

    active_extinguish_area = 0 # 0=Standby, 1=Area 1, 2=Area 2

    test_s1_toggle    = False
    test_s2_toggle    = False
    test_relay_toggle = False

    window_name = "AIoT Forest Protection"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 980, 580)

    mouse_params = {"zones": zones, "w": 640, "h": 480}
    cv2.setMouseCallback(window_name, mouse_callback, mouse_params)

    while True:
        frame = None
        with frame_lock:
            if frame_queue:
                arr = np.frombuffer(frame_queue[-1], np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

        zone1_active = False
        zone2_active = False
        alternating_info = ""
        w, h = 640, 480

        if frame is None:
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            frame[:] = (20, 30, 25)
            cv2.putText(frame, "Menunggu ESP32-CAM...", (120, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 140), 2)
            cv2.putText(frame, f"Target: {ESP32_CAM_IP}:{ESP32_CAM_PORT}", (165, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 160, 120), 1)
            cv2.putText(frame, "Pastikan terhubung WiFi 'Absolute Solver'", (95, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (100, 160, 100), 1)
        else:
            h, w = frame.shape[:2]
            mouse_params["w"] = w
            mouse_params["h"] = h

            frame = draw_zones_and_angles(frame, zones, w, h)

            now = time.time()

            # 1. Jalankan inferensi YOLO (Tiap 35ms)
            if now - last_yolo_time >= 0.035:
                last_yolo_time = now
                if yolo_model:
                    current_dets = detect_yolo(yolo_model, frame, conf_thresh=CONF_THRESHOLD)
                else:
                    current_dets = detect_fire_color(frame)

            poly1 = get_poly(zones, "area1", w, h)
            poly2 = get_poly(zones, "area2", w, h)

            # 2. Gambar deteksi dan kalkulasi sudut presisi (First-Angle Lock)
            for det in current_dets:
                lbl = det["label"]
                cls_id = det.get("class_id", -1)
                cx, cy = det["center"]
                x1, y1, x2, y2 = det["bbox"]
                conf = det["confidence"]

                is_fire = (cls_id == 2 or "api" in lbl.lower())
                color = (0, 60, 255) if is_fire else (0, 220, 80)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, f"{lbl} {conf:.0%}", (x1, max(18, y1-6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2)

                if is_fire:
                    d1 = in_zone_dist(cx, cy, poly1)
                    d2 = in_zone_dist(cx, cy, poly2)

                    # Tentukan apakah api masuk ke Area 1 atau Area 2
                    if d1 >= 0 and d1 >= d2:
                        last_fire_time_1 = now
                        s_pts1 = zones.get("area1", {}).get("servo_points", {})
                        calc_a, proj_pt = compute_calibrated_angle(cx, cy, s_pts1, poly1, w, h)

                        # LOGIKA KUNCI SUDUT PERTAMA & INTERVAL 2 DETIK (SERVO 1)
                        if not is_fire_locked_1:
                            is_fire_locked_1 = True
                            locked_angle_1 = calc_a
                            last_angle_update_1 = now
                            print(f"\n[TARGET LOCK] S1: Api terdeteksi di Area 1 -> KUNCI SUDUT: {locked_angle_1}°")
                        else:
                            # Sudah terkunci: Cek apakah sudah 2.0 detik DAN berpindah cukup jauh
                            if (now - last_angle_update_1 >= ANGLE_UPDATE_INTERVAL):
                                if abs(calc_a - locked_angle_1) >= ANGLE_DEADBAND:
                                    print(f"\n[TARGET UPDATE] S1: Api berpindah ({locked_angle_1}° -> {calc_a}°) -> Update setelah jeda 2 detik")
                                    locked_angle_1 = calc_a
                                    last_angle_update_1 = now

                        # Gambar target sudut di layar
                        cv2.circle(frame, proj_pt, 6, (0, 255, 255), -1)
                        cv2.line(frame, (cx, cy), proj_pt, (0, 255, 255), 1, cv2.LINE_AA)
                        cv2.putText(frame, f"S1 Locked: {locked_angle_1}°", (x1, y2+22),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 230, 255), 2)

                    elif d2 >= 0 and d2 > d1:
                        last_fire_time_2 = now
                        s_pts2 = zones.get("area2", {}).get("servo_points", {})
                        calc_a, proj_pt = compute_calibrated_angle(cx, cy, s_pts2, poly2, w, h)

                        # LOGIKA KUNCI SUDUT PERTAMA & INTERVAL 2 DETIK (SERVO 2)
                        if not is_fire_locked_2:
                            is_fire_locked_2 = True
                            locked_angle_2 = calc_a
                            last_angle_update_2 = now
                            print(f"\n[TARGET LOCK] S2: Api terdeteksi di Area 2 -> KUNCI SUDUT: {locked_angle_2}°")
                        else:
                            # Sudah terkunci: Cek apakah sudah 2.0 detik DAN berpindah cukup jauh
                            if (now - last_angle_update_2 >= ANGLE_UPDATE_INTERVAL):
                                if abs(calc_a - locked_angle_2) >= ANGLE_DEADBAND:
                                    print(f"\n[TARGET UPDATE] S2: Api berpindah ({locked_angle_2}° -> {calc_a}°) -> Update setelah jeda 2 detik")
                                    locked_angle_2 = calc_a
                                    last_angle_update_2 = now

                        # Gambar target sudut di layar
                        cv2.circle(frame, proj_pt, 6, (255, 100, 255), -1)
                        cv2.line(frame, (cx, cy), proj_pt, (255, 100, 255), 1, cv2.LINE_AA)
                        cv2.putText(frame, f"S2 Locked: {locked_angle_2}°", (x1, y2+22),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 120, 255), 2)

            # 3. Debounce: status api tetap aktif selama 1.5 detik dari frame terakhir
            has_fire_1 = (now - last_fire_time_1) < FIRE_HOLD_SECONDS
            has_fire_2 = (now - last_fire_time_2) < FIRE_HOLD_SECONDS

            if not has_fire_1:
                is_fire_locked_1 = False
                locked_angle_1 = 90

            if not has_fire_2:
                is_fire_locked_2 = False
                locked_angle_2 = 90

            # 4. LOGIKA GANTI-GANTIAN (MUTUAL EXCLUSION) AGAR ARUS TIDAK DROP
            zone1_active = False
            zone2_active = False
            alternating_info = ""

            if has_fire_1 and not has_fire_2:
                # Hanya Area 1 yang ada api -> Area 1 aktif penuh
                zone1_active = True
                active_extinguish_area = 1
                is_pausing_turn = False

            elif has_fire_2 and not has_fire_1:
                # Hanya Area 2 yang ada api -> Area 2 aktif penuh
                zone2_active = True
                active_extinguish_area = 2
                is_pausing_turn = False

            elif has_fire_1 and has_fire_2:
                # KEDUA AREA ADA API: SEMPROT GANTI-GANTIAN!
                active_extinguish_area = 3  # mode ganti-gantian

                if is_pausing_turn:
                    # Jeda transisi: matikan kedua pompa 0.25 detik agar voltase stabil
                    zone1_active = False
                    zone2_active = False
                    alternating_info = f"🔄 Transisi arus -> Giliran Area {alternating_turn}"
                    if now - pause_start_time >= PAUSE_SETTLE_TIME:
                        is_pausing_turn = False
                        turn_start_time = now
                else:
                    # Fase penyemprotan area yang sedang giliran
                    rem_time = max(0.0, CYCLE_DURATION - (now - turn_start_time))
                    if alternating_turn == 1:
                        zone1_active = True
                        alternating_info = f"🔄 GANTI-GANTIAN: AREA 1 AKTIF ({rem_time:.1f}s) | AREA 2 MENUNGGU"
                    else:
                        zone2_active = True
                        alternating_info = f"🔄 GANTI-GANTIAN: AREA 2 AKTIF ({rem_time:.1f}s) | AREA 1 MENUNGGU"

                    if rem_time <= 0.0:
                        # Ganti giliran ke area berikutnya setelah jeda arus
                        alternating_turn = 2 if alternating_turn == 1 else 1
                        is_pausing_turn = True
                        pause_start_time = now
            else:
                # Tidak ada api di mana pun -> Standby
                active_extinguish_area = 0
                is_pausing_turn = False

            # 5. Kirim Perintah ke ESP32 hanya jika diperlukan (Stabil & Tanpa Spam)
            should_send = False

            # Cek jika status on/off berubah
            if zone1_active != last_sent_z1_active or zone2_active != last_sent_z2_active:
                should_send = True

            # Cek jika sudut terkunci yang aktif berubah (misal setelah interval 2 detik)
            if zone1_active and abs(locked_angle_1 - sent_angle_1) >= ANGLE_DEADBAND:
                should_send = True
            if zone2_active and abs(locked_angle_2 - sent_angle_2) >= ANGLE_DEADBAND:
                should_send = True

            # Jaga jeda pengiriman minimal 0.25 detik agar ESP32 stabil
            if should_send and (now - last_cmd_time >= 0.25):
                last_cmd_time = now
                last_sent_z1_active = zone1_active
                last_sent_z2_active = zone2_active
                sent_angle_1 = locked_angle_1 if zone1_active else 90
                sent_angle_2 = locked_angle_2 if zone2_active else 90

                if zone1_active or zone2_active:
                    send_cmd({
                        "action": "FIRE_EXTINGUISH",
                        "zone1_active": zone1_active,
                        "zone1_angle": sent_angle_1,
                        "zone2_active": zone2_active,
                        "zone2_angle": sent_angle_2
                    })
                    z1_stat = f"ON ({sent_angle_1}°)" if zone1_active else "IDLE"
                    z2_stat = f"ON ({sent_angle_2}°)" if zone2_active else "IDLE"
                    print(f"\n[ACTION] Servo 1={z1_stat} | Servo 2={z2_stat}")
                else:
                    send_cmd({"action": "STANDBY"})
                    sent_angle_1 = 90
                    sent_angle_2 = 90
                    print("\n[ACTION] Standby -> Servo 90°, Pompa OFF")

            # 6. LOGIKA EMAIL DARURAT DAMKAR (JIKA API TIDAK PADAM DALAM 15 DETIK)
            if has_fire_1 or has_fire_2:
                if fire_start_time is None:
                    fire_start_time = now
                fire_duration = now - fire_start_time

                # Jika api menyala selama >= 15 detik dan belum pernah dikirim pada insiden ini (Anti-Spam)
                if fire_duration >= FIRE_EMAIL_TIMEOUT and not fire_email_sent:
                    fire_email_sent = True

                    if has_fire_1 and has_fire_2:
                        area_str = "Area 1 & Area 2 (Kedua Sektor Terbakar)"
                        angle_str = f"Servo 1: {locked_angle_1}°, Servo 2: {locked_angle_2}°"
                    elif has_fire_1:
                        area_str = "Area 1 (Sektor Barat)"
                        angle_str = f"Servo 1 Terarah pada {locked_angle_1}°"
                    else:
                        area_str = "Area 2 (Sektor Timur)"
                        angle_str = f"Servo 2 Terarah pada {locked_angle_2}°"

                    print(f"\n🚨 [DISPATCH DAMKAR] Api tidak kunjung padam ({fire_duration:.1f}s)! Mengirim email darurat ke Petugas Damkar...")
                    toast_message = "🚨 EMAIL DARURAT TELAH DIKIRIM KE PETUGAS DAMKAR!"
                    toast_time = time.time()

                    # Kirim email darurat asinkron beserta foto bukti kamera
                    send_fire_alert_email_async(area_str, fire_duration, angle_str, frame)
            else:
                # Api padam / tidak ada api -> reset timer & anti-spam
                if fire_start_time is not None:
                    print("\n[INFO] Api telah padam. Timer darurat damkar di-reset.")
                fire_start_time = None
                fire_email_sent = False

        # Toast Message di Layar
        if toast_message and (time.time() - toast_time) < 2.0:
            tw = len(toast_message) * 11 + 30
            tx = (w - tw) // 2
            cv2.rectangle(frame, (tx, 15), (tx + tw, 48), (20, 20, 20), -1)
            cv2.rectangle(frame, (tx, 15), (tx + tw, 48), (0, 255, 120), 2)
            cv2.putText(frame, toast_message, (tx + 15, 38),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 120), 1, cv2.LINE_AA)

        # Status Bar Bawah
        h2, w2 = frame.shape[:2]
        bar = np.zeros((32, w2, 3), dtype=np.uint8)
        bar[:] = (22, 22, 22)
        cv2.putText(bar, f"CAM:{'OK' if cam_connected else 'ERR'}", (10, 21),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 220, 80) if cam_connected else (80, 80, 230), 1)
        cv2.putText(bar, f"ESP:{'OK' if esp_connected else 'ERR'}", (125, 21),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 220, 80) if esp_connected else (80, 80, 230), 1)

        if alternating_info:
            status_txt = alternating_info
            status_clr = (0, 200, 255)
        elif zone1_active:
            status_txt = f"🔥 API AREA 1 -> SERVO 1 ({sent_angle_1}°) AKTIF | SERVO 2 DIAM"
            status_clr = (0, 60, 255)
        elif zone2_active:
            status_txt = f"🔥 API AREA 2 -> SERVO 2 ({sent_angle_2}°) AKTIF | SERVO 1 DIAM"
            status_clr = (0, 60, 255)
        else:
            status_txt = "STATUS: WILAYAH AMAN (STANDBY 90°)"
            status_clr = (0, 200, 70)

        # Tambahkan status hitung mundur / indikator email damkar
        if fire_email_sent:
            status_txt += " | 🚨 EMAIL DAMKAR TERKIRIM"
        elif fire_start_time is not None:
            rem_sec = max(0.0, FIRE_EMAIL_TIMEOUT - (time.time() - fire_start_time))
            status_txt += f" | Damkar dlm: {rem_sec:.1f}s"

        cv2.putText(bar, status_txt, (240, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.48, status_clr, 2)

        cv2.imshow(window_name, np.vstack([frame, bar]))

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key in (ord('s'), ord('S')):
            save_zones_to_disk(zones)
            toast_message = "✅ Titik Kalibrasi Berhasil Disimpan!"
            toast_time = time.time()
        elif key in (ord('+'), ord('=')):
            CONF_THRESHOLD = min(0.95, CONF_THRESHOLD + 0.05)
            toast_message = f"Confidence: {CONF_THRESHOLD:.0%}"
            toast_time = time.time()
        elif key in (ord('-'), ord('_')):
            CONF_THRESHOLD = max(0.10, CONF_THRESHOLD - 0.05)
            toast_message = f"Confidence: {CONF_THRESHOLD:.0%}"
            toast_time = time.time()
        elif key == ord('c'):
            zones = load_zones()
            mouse_params["zones"] = zones
            toast_message = "Konfigurasi Area Di-reload!"
            toast_time = time.time()
        elif key == ord('b'):
            send_cmd({"action": "BEEP"})
            toast_message = "Buzzer Beep Dikirim"
            toast_time = time.time()
        elif key == ord('1'):
            test_s1_toggle = not test_s1_toggle
            target_a = 45 if test_s1_toggle else 135
            send_cmd({"action": "SET_SERVO", "tower": 1, "angle": target_a})
            toast_message = f"Test Servo 1 -> {target_a}°"
            toast_time = time.time()
        elif key == ord('2'):
            test_s2_toggle = not test_s2_toggle
            target_a = 45 if test_s2_toggle else 135
            send_cmd({"action": "SET_SERVO", "tower": 2, "angle": target_a})
            toast_message = f"Test Servo 2 -> {target_a}°"
            toast_time = time.time()
        elif key == ord('r'):
            test_relay_toggle = not test_relay_toggle
            st = 1 if test_relay_toggle else 0
            send_cmd({"action": "SET_RELAY", "relay": 1, "state": st})
            send_cmd({"action": "SET_RELAY", "relay": 2, "state": st})
            toast_message = f"Test Relays -> {'ON' if st else 'OFF'}"
            toast_time = time.time()

    cv2.destroyAllWindows()
    print("\n[EXIT] Program selesai.")

if __name__ == "__main__":
    main()
