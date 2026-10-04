"""
=======================================================================
 AIoT Intelligence Forest Protection - Live Camera Model Testing Tool
=======================================================================
Menguji model YOLO hasil training secara REALTIME melalui KAMERA:
  - Mengarahkan kamera ke objek / foto / datasheet
  - Otomatis memunculkan kotak (bounding box) pada objek yang terdeteksi
  - Menampilkan nama kelas dan persentase keyakinan (confidence %)
  - Warna kotak:
      [0] Kuning : Pohon yang ditebang
      [1] Hijau  : Pohon jatuh alami
      [2] Merah  : Api

Mendukung 3 Pilihan Kamera:
  [1] Webcam Laptop / Kamera USB (Index 0, 1, 2)
  [2] USB Serial COM Port (ESP32-CAM via USB CH340 - Baud 460800)
  [3] ESP32-CAM WiFi TCP/IP (Stream Port 80)

Cara pakai:
  python python_backend/test_model.py
  (Pilih menu 1, 2, atau 3 di terminal)

  Atau langsung dengan argumen cepat:
  - python python_backend/test_model.py 0              # Langsung Webcam 0
  - python python_backend/test_model.py COM3           # Langsung Serial COM3
  - python python_backend/test_model.py 192.168.4.2    # Langsung ESP32-CAM WiFi
  - python python_backend/test_model.py --static        # Mode uji gambar folder

Kontrol saat jendela kamera terbuka:
  [+] / [-] : Naikkan / turunkan ambang batas keyakinan (Confidence Threshold)
  [S]       : Simpan tangkapan layar (Screenshot) hasil deteksi ke dataset/test_results/
  [F]       : Toggle Senter / Flash ESP32-CAM (jika didukung)
  [Q] / ESC : Selesai dan keluar
=======================================================================
"""

import os
import sys
import time
import socket
import struct
import threading
import argparse
import cv2
import numpy as np

# Coba import pyserial jika ada
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

# Peta warna berdasarkan NAMA KELAS (bukan index) — agar selalu cocok
# dengan model.names, tidak bergantung urutan training.
CLASS_COLOR_BY_NAME = {
    "Api"                : (30,  30,  255),   # Merah
    "api"                : (30,  30,  255),
    "Pohon yang ditebang": (0,  220,  255),   # Kuning
    "pohon yang ditebang": (0,  220,  255),
    "Pohon jatuh alami"  : (0,  210,   60),   # Hijau
    "pohon jatuh alami"  : (0,  210,   60),
}
DEFAULT_COLOR = (200, 200, 200)   # Abu-abu untuk kelas tak dikenal


def get_class_color(name: str):
    """Kembalikan warna BGR untuk nama kelas, case-insensitive."""
    col = CLASS_COLOR_BY_NAME.get(name)
    if col:
        return col
    # Coba case-insensitive
    name_lower = name.lower()
    for k, v in CLASS_COLOR_BY_NAME.items():
        if k.lower() == name_lower:
            return v
    return DEFAULT_COLOR


DEFAULT_MODEL_PATHS = [
    # Path hasil training dari folder UTS (paling umum)
    "runs/detect/runs/forest_ai/forest_protection_model/weights/best.pt",
    "runs/detect/runs/forest_ai/forest_protection_model/weights/last.pt",
    # Path alternatif jika dijalankan dari subfolder
    "runs/forest_ai/forest_protection_model/weights/best.pt",
    "runs/forest_ai/forest_protection_model/weights/last.pt",
    # Path lama / backup
    "waste_model/weights/best.pt",
    "models/best.pt",
    "best.pt",
    # JANGAN gunakan yolov8n.pt (COCO 80-class, bukan model kita!)
    # "yolov8n.pt"
]

CANVAS_W = 1000
CANVAS_H = 700
TOP_BAR_H = 65
BOTTOM_BAR_H = 45

SAVE_RESULT_DIR = "dataset/test_results"
os.makedirs(SAVE_RESULT_DIR, exist_ok=True)

latest_frame     = None
frame_lock       = threading.Lock()
is_running       = True
source_connected = False
fps_val          = 0.0
source_info_str  = ""
ser_global       = None
flash_state      = True


def find_best_model(custom_path=None):
    """Mencari file bobot model YOLO hasil training."""
    if custom_path and os.path.exists(custom_path):
        return custom_path

    for p in DEFAULT_MODEL_PATHS:
        if os.path.exists(p):
            return p

    return "yolov8n.pt"


# =====================================================================
# THREAD 1: WEBCAM / USB CAMERA (OPENCV VIDEOCAPTURE)
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
# THREAD 2: USB SERIAL COM PORT (ESP32-CAM VIA USB CH340 @ 460800)
# =====================================================================
def serial_thread(port_name, baud_rate=460800):
    global latest_frame, source_connected, fps_val, is_running, ser_global
    if not HAS_SERIAL:
        print("[SERIAL ERROR] Modul pyserial belum terpasang. Jalankan: pip install pyserial")
        return

    while is_running:
        ser = None
        try:
            print(f"\n[SERIAL] Membuka {port_name} pada Baud {baud_rate}...")
            ser = serial.Serial(port_name, baud_rate, timeout=2.0)
            ser_global = ser
            time.sleep(1.0)
            ser.reset_input_buffer()

            ser.write(b"START_SERIAL_STREAM\n")
            ser.flush()

            source_connected = True
            print(f"[SERIAL] Terhubung ke {port_name}! Menerima video stream...")

            prev_time = time.time()
            MAGIC = b"\xaa\xbb\xcc\xdd"

            while is_running:
                byte1 = ser.read(1)
                if not byte1:
                    continue
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
                                    if not chunk:
                                        break
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
            print(f"[SERIAL ERROR] Error pada {port_name}: {e}")
            source_connected = False
        finally:
            if ser and ser.is_open:
                try:
                    ser.write(b"STOP_SERIAL_STREAM\n")
                    ser.close()
                except Exception:
                    pass
            ser_global = None
            source_connected = False
            time.sleep(2.0)


# =====================================================================
# THREAD 3: TCP/IP WIFI STREAM (ESP32-CAM PORT 80 - CAM BERHASIL)
# =====================================================================
def connect_cam_tcp(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((ip, port))
    sock.settimeout(15)
    return sock


def recv_exact(sock, n):
    buf = bytearray(n)
    view = memoryview(buf)
    pos = 0
    while pos < n and is_running:
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


def tcp_wifi_thread(ip, port=80):
    global latest_frame, source_connected, fps_val, is_running

    while is_running:
        sock = None
        try:
            print(f"\n[TCP] Menghubungkan ke ESP32-CAM di {ip}:{port}...")
            sock = connect_cam_tcp(ip, port)
            source_connected = True
            print(f"[TCP] Terhubung ke {ip}:{port}! Menerima stream...")

            prev_time = time.time()
            while is_running:
                len_bytes = recv_exact(sock, 4)
                if not len_bytes:
                    print("[TCP] Terputus atau gagal membaca frame.")
                    break

                frame_len = struct.unpack(">I", len_bytes)[0]
                if frame_len == 0 or frame_len > 1_000_000:
                    continue

                jpeg_data = recv_exact(sock, frame_len)
                if not jpeg_data or len(jpeg_data) != frame_len:
                    print("[TCP] Data frame tidak lengkap.")
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

        except socket.timeout:
            print(f"[TCP] Timeout menghubungkan ke {ip}:{port}.")
        except ConnectionRefusedError:
            print(f"[TCP] Connection Refused pada {ip}:{port}.")
        except Exception as e:
            print(f"[TCP] Koneksi error: {e}")
        finally:
            source_connected = False
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            time.sleep(1.0)


def toggle_flash():
    global flash_state, ser_global
    flash_state = not flash_state
    if ser_global and ser_global.is_open:
        cmd = f"FLASH:{1 if flash_state else 0}\n".encode("utf-8")
        try:
            ser_global.write(cmd)
            print(f"[*] Senter/Flash diubah ke: {'ON' if flash_state else 'OFF'}")
        except Exception:
            pass


def get_available_com_ports():
    if not HAS_SERIAL:
        return []
    return [p.device for p in serial.tools.list_ports.comports()]


# =====================================================================
# LIVE CAMERA AI DETECTION RUNNER
# =====================================================================
def run_live_camera_test(model_path, conf_thresh=0.40):
    global is_running, source_info_str

    try:
        from ultralytics import YOLO
    except ImportError:
        print("[ERROR] Modul 'ultralytics' belum terpasang. Jalankan: pip install ultralytics")
        return

    print("=" * 65)
    print(" 🌲 AIoT Forest Protection — Live Camera AI Object Detection")
    print("=" * 65)
    print(f"[*] Model Bobot   : {model_path}")
    print(f"[*] Ambang Batas  : {conf_thresh * 100:.0f}%")
    print("=" * 65)

    # 1. Load YOLO Model
    print("[AI] Memuat model YOLO...")
    model = YOLO(model_path)
    print("[AI] Model siap mendeteksi secara realtime!\n")

    # 2. Tentukan Sumber Kamera
    selected_mode = None
    target_param  = None

    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        arg = sys.argv[1].strip()
        if arg.isdigit():
            selected_mode = "1"
            target_param = int(arg)
        elif arg.upper().startswith("COM"):
            selected_mode = "2"
            target_param = arg.upper()
        elif "." in arg:
            selected_mode = "3"
            target_param = arg

    if selected_mode is None:
        com_list = get_available_com_ports()
        com_hint = f" (Terdeteksi: {', '.join(com_list)})" if com_list else ""

        print("PILIH SUMBER KAMERA:")
        print("  [1] Webcam Laptop / Kamera USB (Index 0, 1, 2)  <-- Rekomendasi")
        print(f"  [2] USB Serial COM Port (Baud 460800){com_hint}")
        print("  [3] ESP32-CAM WiFi (TCP/IP Stream Port 80)")
        print("=" * 65)

        pilihan = input("Pilihan (1/2/3) [Default 1]: ").strip() or "1"
        selected_mode = pilihan

    worker_thread = None

    if selected_mode == "1":
        cam_idx = target_param if isinstance(target_param, int) else 0
        if target_param is None and len(sys.argv) <= 1:
            idx_in = input(f"Index Kamera [Default {cam_idx}]: ").strip()
            if idx_in.isdigit():
                cam_idx = int(idx_in)
        source_info_str = f"Webcam (Index {cam_idx})"
        worker_thread = threading.Thread(target=webcam_thread, args=(cam_idx,), daemon=True)

    elif selected_mode == "2":
        com_ports = get_available_com_ports()
        default_com = com_ports[0] if com_ports else "COM3"
        com_name = target_param if isinstance(target_param, str) and target_param.startswith("COM") else default_com
        if target_param is None and len(sys.argv) <= 1:
            cin = input(f"Port COM [Default {default_com}]: ").strip()
            if cin:
                com_name = cin.upper()
        source_info_str = f"Serial ({com_name} @ 460800)"
        worker_thread = threading.Thread(target=serial_thread, args=(com_name, 460800), daemon=True)

    elif selected_mode == "3":
        ip = target_param if isinstance(target_param, str) and "." in target_param else "192.168.4.2"
        if target_param is None and len(sys.argv) <= 1:
            ipin = input("IP ESP32-CAM [Default 192.168.4.2]: ").strip()
            if ipin:
                ip = ipin
        source_info_str = f"ESP32-CAM ({ip}:80)"
        worker_thread = threading.Thread(target=tcp_wifi_thread, args=(ip, 80), daemon=True)

    else:
        print("[!] Pilihan tidak valid.")
        return

    worker_thread.start()

    window_name = f"AIoT Forest — Live Detection ({source_info_str})"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, CANVAS_W, CANVAS_H)

    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(placeholder, f"Menghubungkan ke {source_info_str}...", (30, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 0.70, (140, 140, 140), 2)

    toast_msg = f"Model {os.path.basename(model_path)} aktif"
    toast_time = time.time()
    shot_counter = 0

    print("\n[INFO] Membuka jendela deteksi realtime...")
    print("  [+] / [-] : Ubah Ambang Batas Keyakinan (Confidence %)")
    print("  [S]       : Simpan Foto Hasil Deteksi")
    print("  [F]       : Toggle Flash / Senter")
    print("  [Q] / ESC : Keluar\n")

    try:
        while True:
            with frame_lock:
                frame = latest_frame.copy() if latest_frame is not None else None

            if frame is None:
                display = placeholder.copy()
                detections = []
                inf_time_ms = 0.0
            else:
                # ── JALANKAN INFERENSI YOLO REALTIME ──
                start_inf = time.time()
                results = model(frame, conf=conf_thresh, verbose=False)
                inf_time_ms = (time.time() - start_inf) * 1000

                detections = []
                for r in results:
                    boxes = r.boxes
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        conf = float(box.conf[0].item())
                        xyxy = box.xyxy[0].cpu().numpy().astype(int)
                        x1, y1, x2, y2 = xyxy

                        # Gunakan nama kelas langsung dari MODEL (bukan hardcode)
                        lbl = model.names.get(cls_id, f"Kelas {cls_id}")
                        detections.append({
                            "cls": cls_id,
                            "label": lbl,
                            "conf": conf,
                            "bbox": [x1, y1, x2, y2]
                        })

                # ── GAMBAR BOUNDING BOX & BADGE PERSENTASE ──
                for det in detections:
                    cls_id = det["cls"]
                    conf = det["conf"]
                    lbl_name = det["label"]
                    x1, y1, x2, y2 = det["bbox"]

                    # Ambil warna dari nama kelas (bukan index)
                    col = get_class_color(lbl_name)
                    conf_pct = conf * 100.0

                    # Kotak deteksi — garis 2px
                    cv2.rectangle(frame, (x1, y1), (x2, y2), col, 2)

                    # Badge Label + Persentase, contoh: "Api : 40.7%"
                    badge_text = f"{lbl_name} : {conf_pct:.1f}%"
                    font_scale = 0.60
                    font_thick = 2
                    t_size, _ = cv2.getTextSize(
                        badge_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thick)
                    bw = t_size[0] + 16
                    bh = t_size[1] + 12
                    by = max(0, y1 - bh - 2)

                    # Latar badge penuh warna kelas
                    cv2.rectangle(frame, (x1, by), (x1 + bw, by + bh), col, -1)
                    # Teks hitam kontras di atas badge
                    cv2.putText(frame, badge_text,
                                (x1 + 7, by + bh - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                                (10, 10, 10), font_thick, cv2.LINE_AA)

                display = frame

            # ── BUAT CANVAS BESAR DENGAN HUD ──
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

            # ── HEADER ATAS (HUD) ──
            cv2.rectangle(canvas, (0, 0), (CANVAS_W, TOP_BAR_H), (12, 12, 12), -1)
            cv2.line(canvas, (0, TOP_BAR_H), (CANVAS_W, TOP_BAR_H), (40, 40, 40), 1)

            det_count = len(detections)
            status_text = f"TERDETEKSI: {det_count} Objek" if det_count > 0 else "Menunggu Objek..."
            status_col = (0, 255, 120) if det_count > 0 else (160, 160, 160)

            cv2.putText(canvas, f"STATUS: {status_text}", (15, 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.58, status_col, 2, cv2.LINE_AA)

            fps_str = f"{fps_val:.1f} FPS" if source_connected else "Offline"
            inf_str = f"Inference: {inf_time_ms:.1f}ms" if inf_time_ms > 0 else ""
            cv2.putText(canvas, f"Kamera: {source_info_str}  |  {fps_str}  |  {inf_str}",
                        (15, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180, 180, 180), 1, cv2.LINE_AA)

            # Info Threshold di Kanan Atas
            bx = CANVAS_W - 310
            cv2.putText(canvas, f"Model: {os.path.basename(model_path)}", (bx, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.44, (200, 220, 255), 1, cv2.LINE_AA)
            cv2.putText(canvas, f"Ambang Batas Conf: {conf_thresh * 100:.0f}%  [+/-]", (bx, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 230, 255), 2, cv2.LINE_AA)

            # ── FOOTER BAWAH (PANDUAN TOMBOL) ──
            foot_y = CANVAS_H - BOTTOM_BAR_H
            cv2.rectangle(canvas, (0, foot_y), (CANVAS_W, CANVAS_H), (12, 12, 12), -1)
            cv2.line(canvas, (0, foot_y), (CANVAS_W, foot_y), (40, 40, 40), 1)

            keys_text = "[+] / [-] Ubah Ambang Batas Conf %   |   [S] Simpan Foto Hasil Deteksi   |   [F] Flash   |   [Q / ESC] Keluar"
            cv2.putText(canvas, keys_text, (20, foot_y + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.44, (190, 225, 255), 1, cv2.LINE_AA)

            # Toast Popup
            if toast_msg and (time.time() - toast_time) < 2.0:
                t_size, _ = cv2.getTextSize(toast_msg, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 1)
                tw = t_size[0] + 24
                th = 30
                tx = (CANVAS_W - tw) // 2
                ty = TOP_BAR_H + 10

                cv2.rectangle(canvas, (tx, ty), (tx + tw, ty + th), (20, 20, 20), -1)
                cv2.rectangle(canvas, (tx, ty), (tx + tw, ty + th), (0, 255, 120), 2)
                cv2.putText(canvas, toast_msg, (tx + 12, ty + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 120), 1, cv2.LINE_AA)

            cv2.imshow(window_name, canvas)

            key = cv2.waitKey(15) & 0xFF

            if key in (ord('q'), ord('Q'), 27):
                break
            elif key in (ord('+'), ord('=')):
                conf_thresh = min(0.95, conf_thresh + 0.05)
                toast_msg = f"Confidence Threshold: {conf_thresh * 100:.0f}%"
                toast_time = time.time()
                print(f"[*] Threshold keyakinan: {conf_thresh * 100:.0f}%")
            elif key in (ord('-'), ord('_')):
                conf_thresh = max(0.05, conf_thresh - 0.05)
                toast_msg = f"Confidence Threshold: {conf_thresh * 100:.0f}%"
                toast_time = time.time()
                print(f"[*] Threshold keyakinan: {conf_thresh * 100:.0f}%")
            elif key in (ord('s'), ord('S')):
                shot_counter += 1
                out_path = os.path.join(SAVE_RESULT_DIR, f"live_det_{int(time.time())}_{shot_counter:03d}.jpg")
                cv2.imwrite(out_path, canvas)
                toast_msg = f"Screenshot disimpan: {out_path}"
                toast_time = time.time()
                print(f"[+] Foto hasil deteksi disimpan ke: {out_path}")
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

    run_live_camera_test(model_file, conf_thresh=args.conf)


if __name__ == "__main__":
    main()
