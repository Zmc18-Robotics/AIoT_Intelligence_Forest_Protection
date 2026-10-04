"""
=======================================================================
 AIoT Intelligence Forest Protection - Multi-Source Dataset Capture Tool
=======================================================================
Mendukung 3 Jalur Input Kamera:
  [1] Webcam Laptop / Kamera USB (OpenCV VideoCapture Index 0, 1, 2)
  [2] USB Serial COM Port (ESP32-CAM via USB CH340/FTDI - Baud 460800)
  [3] ESP32-CAM WiFi TCP/IP (Stream Port 80, arsitektur CAM BERHASIL)

Cara pakai:
  python python_backend/capture_dataset.py
  (Pilih menu 1, 2, atau 3 di terminal)

  Atau langsung dengan argumen cepat:
  - python python_backend/capture_dataset.py 0              # Langsung Webcam 0
  - python python_backend/capture_dataset.py COM3           # Langsung Serial COM3 (Baud 460800)
  - python python_backend/capture_dataset.py 192.168.4.2    # Langsung TCP/IP

Kontrol saat jendela kamera terbuka:
  [SPACE]   : Ambil & simpan 1 foto ke dataset/images/
  [A]       : Toggle Auto-Capture (otomatis ambil foto tiap X detik)
  [+] / [-] : Tambah / kurangi interval auto-capture (misal 1s, 2s, 3s)
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
import cv2
import numpy as np

# Coba import pyserial jika ada
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

# ──────────────── KONFIGURASI ────────────────
SAVE_DIR         = "dataset/images"
IMG_PREFIX       = "forest"
DEFAULT_CAM_IP   = "192.168.4.2"
DEFAULT_TCP_PORT = 80
SERIAL_BAUD_RATE = 460800  # Sesuai firmware ESP32-CAM terbaru (460800 baud)
# ─────────────────────────────────────────────

os.makedirs(SAVE_DIR, exist_ok=True)

latest_frame     = None
frame_lock       = threading.Lock()
is_running       = True
source_connected = False
fps_val          = 0.0
source_info_str  = ""
ser_global       = None
flash_state      = True


def count_existing_images():
    return len([f for f in os.listdir(SAVE_DIR)
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp"))])


def get_next_filename(counter):
    return os.path.join(SAVE_DIR, f"{IMG_PREFIX}_{counter:04d}.jpg")


def save_frame(frame, counter):
    filename = get_next_filename(counter)
    cv2.imwrite(filename, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"  [+] Foto tersimpan ({counter + 1}): {filename}")
    return filename


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
    print(f"[WEBCAM] Kamera index {cam_index} aktif & berjalan!")

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
    print("[WEBCAM] Kamera ditutup.")


# =====================================================================
# THREAD 2: USB SERIAL COM PORT (ESP32-CAM VIA USB CH340/FTDI @ 460800)
# =====================================================================
def serial_thread(port_name, baud_rate=SERIAL_BAUD_RATE):
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

            # Aktifkan stream di ESP32-CAM
            ser.write(b"START_SERIAL_STREAM\n")
            ser.flush()

            source_connected = True
            print(f"[SERIAL] Terhubung ke {port_name}! Menerima serial video stream...")

            prev_time = time.time()
            MAGIC = b"\xaa\xbb\xcc\xdd"

            while is_running:
                # Cari Magic Header (4 byte)
                byte1 = ser.read(1)
                if not byte1:
                    continue
                if byte1 == b"\xaa":
                    rest = ser.read(3)
                    if rest == b"\xbb\xcc\xdd":
                        # Baca 4 byte panjang frame
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
# THREAD 3: TCP/IP WIFI STREAM (PERSIS SEPERTI DI CAM BERHASIL / CAM.PY)
# =====================================================================
def connect_cam_tcp(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((ip, port))
    sock.settimeout(15)
    return sock


def recv_exact(sock, n):
    """Membaca data persis sejumlah n bytes dari socket TCP (Sesuai CAM.py)."""
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
            print(f"[TCP] Terhubung ke {ip}:{port}! Menerima stream live...")

            prev_time = time.time()
            while is_running:
                # 1. Baca panjang frame (4 byte big-endian)
                len_bytes = recv_exact(sock, 4)
                if not len_bytes:
                    print("[TCP] Terputus atau gagal membaca panjang frame.")
                    break

                frame_len = struct.unpack(">I", len_bytes)[0]
                if frame_len == 0 or frame_len > 1_000_000:
                    continue

                # 2. Baca data JPEG sesuai ukuran frame
                jpeg_data = recv_exact(sock, frame_len)
                if not jpeg_data or len(jpeg_data) != frame_len:
                    print("[TCP] Data frame tidak lengkap.")
                    break

                # 3. Decode frame dengan OpenCV
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
            print(f"[TCP] Connection Refused pada {ip}:{port} (ESP32-CAM server belum siap).")
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


# =====================================================================
# OVERLAY HUD & DISPLAY
# =====================================================================
def draw_hud(frame, saved_count, auto_on, auto_interval, auto_timer, connected, source_text):
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 68), (18, 18, 18), -1)
    frame = cv2.addWeighted(overlay, 0.72, frame, 0.28, 0)

    status_color = (0, 255, 120) if connected else (80, 100, 255)
    status_text  = f"{source_text}  ({fps_val:.1f} FPS)" if connected else f"Menghubungkan ke {source_text}..."
    cv2.putText(frame, f"Sumber: {status_text}", (10, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, status_color, 1, cv2.LINE_AA)
    cv2.putText(frame, f"Tersimpan: {saved_count} foto  |  Folder: {SAVE_DIR}/",
                (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)

    if auto_on:
        sisa = max(0.0, auto_interval - (time.time() - auto_timer))
        cv2.putText(frame, f"[A] AUTO ON  Interval={auto_interval}s  Next={sisa:.1f}s  |  [F] Flash  |  [Q] Keluar",
                    (10, 63), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 255, 140), 1, cv2.LINE_AA)
    else:
        cv2.putText(frame, "[SPACE] Ambil Foto  [A] Auto  [+/-] Interval  [F] Flash  [Q] Keluar",
                    (10, 63), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (200, 225, 255), 1, cv2.LINE_AA)

    dot_color = (0, 0, 255) if connected else (100, 100, 100)
    cv2.circle(frame, (w - 20, 18), 7, dot_color, -1)
    cv2.putText(frame, "LIVE" if connected else "OFF", (w - 55, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, dot_color, 1, cv2.LINE_AA)
    return frame


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


def main():
    global is_running, source_info_str

    print("=" * 62)
    print(" 🌲 AIoT Forest Protection — Multi-Source Dataset Capture")
    print("=" * 62)
    print(f"[*] Folder Penyimpanan  : {SAVE_DIR}/")
    print(f"[*] Jumlah Foto Saat Ini: {count_existing_images()} foto")
    print("=" * 62)

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
        com_hint = f" (Terdeteksi: {', '.join(com_list)})" if com_list else " (Tidak ada COM terdeteksi)"

        print("\nPILIH SUMBER KAMERA:")
        print("  [1] Webcam Laptop / Kamera USB (Index 0, 1, 2)")
        print(f"  [2] USB Serial COM Port (Baud 460800){com_hint}")
        print(f"  [3] ESP32-CAM WiFi (TCP/IP Stream Port 80)")
        print("=" * 62)

        pilihan = input("Masukkan Pilihan (1/2/3) [Default 1]: ").strip() or "1"
        selected_mode = pilihan

    worker_thread = None

    if selected_mode == "1":
        cam_idx = target_param if isinstance(target_param, int) else 0
        if target_param is None and len(sys.argv) <= 1:
            idx_input = input(f"Masukkan Index Kamera [Default {cam_idx}]: ").strip()
            if idx_input.isdigit():
                cam_idx = int(idx_input)
        source_info_str = f"Webcam (Index {cam_idx})"
        worker_thread = threading.Thread(target=webcam_thread, args=(cam_idx,), daemon=True)

    elif selected_mode == "2":
        com_ports = get_available_com_ports()
        default_com = com_ports[0] if com_ports else "COM3"
        com_name = target_param if isinstance(target_param, str) and target_param.startswith("COM") else default_com
        if target_param is None and len(sys.argv) <= 1:
            com_input = input(f"Masukkan Port COM [Default {default_com}]: ").strip()
            if com_input:
                com_name = com_input.upper()
        source_info_str = f"Serial ({com_name} @ {SERIAL_BAUD_RATE})"
        worker_thread = threading.Thread(target=serial_thread, args=(com_name, SERIAL_BAUD_RATE), daemon=True)

    elif selected_mode == "3":
        ip = target_param if isinstance(target_param, str) and "." in target_param else DEFAULT_CAM_IP
        if target_param is None and len(sys.argv) <= 1:
            ip_input = input(f"Masukkan IP ESP32-CAM [Default {DEFAULT_CAM_IP}]: ").strip()
            if ip_input:
                ip = ip_input
        source_info_str = f"ESP32-CAM ({ip}:{DEFAULT_TCP_PORT})"
        worker_thread = threading.Thread(target=tcp_wifi_thread, args=(ip, DEFAULT_TCP_PORT), daemon=True)

    else:
        print("[!] Pilihan tidak valid, keluar.")
        return

    worker_thread.start()

    window_name = f"Dataset Capture — {source_info_str}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 760, 560)

    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(placeholder, f"Menghubungkan ke {source_info_str}...", (30, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (140, 140, 140), 2)

    img_counter   = count_existing_images()
    auto_capture  = False
    auto_interval = 2
    auto_timer    = time.time()

    print("\n[INFO] Menampilkan jendela kamera...")
    print("  [SPACE]   : Ambil Foto")
    print("  [A]       : Toggle Auto-Capture")
    print("  [+] / [-] : Ganti Interval Auto-Capture")
    print("  [F]       : Toggle Flash / Senter")
    print("  [Q] / ESC : Keluar")
    print("-" * 62)

    try:
        while True:
            with frame_lock:
                frame = latest_frame.copy() if latest_frame is not None else None

            display = frame if frame is not None else placeholder.copy()

            if auto_capture and source_connected and frame is not None:
                if (time.time() - auto_timer) >= auto_interval:
                    save_frame(frame, img_counter)
                    img_counter += 1
                    auto_timer = time.time()

            display = draw_hud(display, img_counter, auto_capture,
                               auto_interval, auto_timer, source_connected, source_info_str)
            cv2.imshow(window_name, display)

            key = cv2.waitKey(20) & 0xFF
            if key in (ord('q'), 27):
                break
            elif key == ord(' '):
                if frame is not None:
                    save_frame(frame, img_counter)
                    img_counter += 1
                else:
                    print("[!] Belum ada frame video aktif.")
            elif key == ord('a'):
                auto_capture = not auto_capture
                auto_timer   = time.time()
                print(f"[*] Auto-Capture: {'AKTIF' if auto_capture else 'NONAKTIF'} (setiap {auto_interval} detik)")
            elif key in (ord('+'), ord('=')):
                auto_interval = min(30, auto_interval + 1)
                print(f"[*] Interval: {auto_interval}s")
            elif key == ord('-'):
                auto_interval = max(1, auto_interval - 1)
                print(f"[*] Interval: {auto_interval}s")
            elif key == ord('f'):
                toggle_flash()

    except KeyboardInterrupt:
        pass
    finally:
        is_running = False
        cv2.destroyAllWindows()
        print(f"\n[SELESAI] Total {count_existing_images()} foto tersimpan di '{SAVE_DIR}'.")
        print("Langkah selanjutnya: Jalankan 'python python_backend/labeling_tool.py' untuk melabeli foto.\n")


if __name__ == "__main__":
    main()
