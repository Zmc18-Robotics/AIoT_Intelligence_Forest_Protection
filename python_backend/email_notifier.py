"""
=============================================================================
 AIoT Forest Protection - Modul Pengiriman Email Darurat Petugas Damkar
=============================================================================
Fungsi:
  - Mengirimkan email peringatan darurat ke Petugas Pemadam Kebakaran (Damkar)
    apabila api terdeteksi dan tidak kunjung padam dalam waktu tertentu (15 detik).
  - Anti-Spam: Hanya dikirim 1 KALI per insiden kebakaran.
  - Lengkap dengan teks laporan resmi, waktu kejadian, status sektor, arah sudut,
    dan lampiran foto snapshot kamera saat api terdeteksi.
=============================================================================
"""

import os
import sys
import smtplib
import ssl
import json
import time
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import cv2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "python_backend" else SCRIPT_DIR
CONFIG_PATHS = [
    os.path.join(ROOT_DIR, "data", "email_config.json"),
    os.path.join(ROOT_DIR, "python_backend", "data", "email_config.json")
]
CONFIG_PATH = CONFIG_PATHS[0]
LOG_PATH = os.path.join(ROOT_DIR, "data", "email_alerts.log")
SNAPSHOT_DIR = os.path.join(ROOT_DIR, "data", "fire_alerts")

DEFAULT_EMAIL_CONFIG = {
    "enabled": True,
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "use_tls": True,
    "sender_email": "mzidaneakbari3@gmail.com",
    "sender_password": "feng ovbf vcjd epqg",  # Masukkan App Password Gmail jika ingin kirim email sungguhan
    "recipient_emails": [
        "mzidaneakbari2@gmail.com"
    ],
    "fire_timeout_seconds": 15
}


def load_email_config():
    """Memuat konfigurasi email atau membuat file template bawaan."""
    cfg = DEFAULT_EMAIL_CONFIG.copy()
    loaded_any = False
    for cp in CONFIG_PATHS:
        if os.path.exists(cp):
            try:
                with open(cp, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    cfg.update(loaded)
                    loaded_any = True
                    break
            except Exception as e:
                print(f"[EMAIL] Gagal membaca {cp}: {e}")

    # Jika DEFAULT_EMAIL_CONFIG di file python diubah sandi/emailnya oleh user, sinkronkan ke JSON
    if DEFAULT_EMAIL_CONFIG.get("sender_password") and DEFAULT_EMAIL_CONFIG.get("sender_password") != cfg.get("sender_password"):
        cfg["sender_password"] = DEFAULT_EMAIL_CONFIG["sender_password"]
        save_email_config(cfg)
    elif not loaded_any:
        save_email_config(cfg)

    return cfg


def save_email_config(cfg):
    for cp in CONFIG_PATHS:
        try:
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            print(f"[EMAIL] Gagal menyimpan {cp}: {e}")


def build_email_content(area_name, duration_sec, angle_info, timestamp_str):
    """
    Membuat format teks laporan resmi yang lengkap dan rapi (Plain text & HTML).
    """
    plain_text = f"""
================================================================================
          LAPORAN DARURAT KEBAKARAN HUTAN (DISPATCH PETUGAS DAMKAR)
================================================================================
STATUS         : KRITIS - API TIDAK KUNJUNG PADAM (ESKALASI DARURAT)
SISTEM DETEKSI : AIoT Forest Protection Node (ESP32-CAM & YOLOv8)
WAKTU INSIDEN  : {timestamp_str}
DURASI API     : {duration_sec:.1f} Detik (Melebihi Ambang Batas 15 Detik)
SEKTOR LOKASI  : {area_name}
POSISI SUDUT   : {angle_info}
--------------------------------------------------------------------------------
DESKRIPSI SITUASI:
Sistem pemadam otomatis lokal telah mendeteksi kobaran api dan mengaktifkan
nozzle semprotan air terarah selama {duration_sec:.1f} detik. Namun hingga saat ini
api terdeteksi BELUM PADAM sepenuhnya.

Diperlukan kehadiran fisik unit armada Pemadam Kebakaran untuk melakukan
pemadaman manual dan pendinginan area sebelum api merambat ke vegetasi lain.

TINDAKAN YANG DIPERLUKAN:
1. Kerahkan unit pemadam kebakaran terdekat ke koordinat sektor {area_name}.
2. Bawa pasokan tangki air tambahan untuk mendukung nozzle otomatis.
3. Lakukan penyisiran radius 50 meter di sekitar lokasi api.
================================================================================
Sistem Otomasi AIoT Kehutanan - Laporan Resmi Otomatis (Tanpa Balasan)
"""

    html_text = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f4f6f9; color: #1e293b; margin: 0; padding: 20px; }}
    .container {{ max-width: 650px; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1); margin: auto; border-top: 6px solid #dc2626; }}
    .header {{ background: #dc2626; color: #ffffff; padding: 24px 30px; }}
    .header h1 {{ margin: 0; font-size: 22px; letter-spacing: 0.5px; }}
    .header p {{ margin: 6px 0 0; font-size: 14px; opacity: 0.9; }}
    .badge {{ display: inline-block; background: #fee2e2; color: #b91c1c; font-weight: bold; padding: 4px 12px; border-radius: 20px; font-size: 13px; margin-top: 10px; }}
    .body {{ padding: 25px 30px; }}
    .table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
    .table td {{ padding: 10px 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; }}
    .table td.label {{ font-weight: bold; color: #475569; width: 35%; background: #f8fafc; }}
    .table td.value {{ color: #0f172a; font-weight: 600; }}
    .alert-box {{ background: #fff1f2; border-left: 4px solid #e11d48; padding: 15px 18px; border-radius: 6px; margin: 20px 0; }}
    .alert-box h3 {{ margin: 0 0 8px; color: #9f1239; font-size: 16px; }}
    .alert-box p {{ margin: 0; font-size: 14px; line-height: 1.5; color: #4c0519; }}
    .instructions {{ background: #f0fdf4; border: 1px solid #bbf7d0; padding: 15px 18px; border-radius: 6px; margin: 20px 0; }}
    .instructions h4 {{ margin: 0 0 10px; color: #166534; font-size: 15px; }}
    .instructions ol {{ margin: 0; padding-left: 20px; font-size: 14px; color: #14532d; line-height: 1.6; }}
    .footer {{ background: #f8fafc; padding: 16px 30px; font-size: 12px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🚨 PERINGATAN DARURAT KEBAKARAN HUTAN</h1>
      <p>Panggilan Otomatis Petugas Pemadam Kebakaran (Damkar)</p>
      <div class="badge">STATUS: KRITIS — API MELEBIHI 15 DETIK</div>
    </div>
    <div class="body">
      <div class="alert-box">
        <h3>⚠️ Tindakan Segera Diperlukan</h3>
        <p>Sistem pemadam otomatis lokal telah menyemprotkan air selama <strong>{duration_sec:.1f} detik</strong>, namun api di sektor ini <strong>belum berhasil dipadamkan</strong>. Potensi perambatan api tinggi.</p>
      </div>

      <table class="table">
        <tr>
          <td class="label">Sektor Lokasi</td>
          <td class="value" style="color: #dc2626;">{area_name}</td>
        </tr>
        <tr>
          <td class="label">Waktu Deteksi</td>
          <td class="value">{timestamp_str}</td>
        </tr>
        <tr>
          <td class="label">Durasi Terbakar</td>
          <td class="value">{duration_sec:.1f} Detik (Melebihi Ambang Batas 15s)</td>
        </tr>
        <tr>
          <td class="label">Arah Target Servo</td>
          <td class="value">{angle_info}</td>
        </tr>
        <tr>
          <td class="label">Unit Deteksi</td>
          <td class="value">ESP32-CAM (AI YOLOv8 Model)</td>
        </tr>
      </table>

      <div class="instructions">
        <h4>📋 Protokol Petugas Damkar:</h4>
        <ol>
          <li>Segera luncurkan armada damkar sektor terdekat menuju <strong>{area_name}</strong>.</li>
          <li>Bawa pasokan tangki air cadangan untuk memadamkan bara inti.</li>
          <li>Lakukan pemutusan vegetasi kering di sekitar titik panas.</li>
        </ol>
      </div>
      <p style="font-size: 13px; color: #64748b;"><em>*Foto bukti deteksi visual dari kamera pengawas terlampir pada email ini.</em></p>
    </div>
    <div class="footer">
      AIoT Forest Intelligence Protection System &copy; {datetime.now().year}<br>
      Pesan ini dikirimkan otomatis oleh sistem mikrokontroler & AI.
    </div>
  </div>
</body>
</html>
"""
    return plain_text, html_text


def safe_print(text):
    try:
        print(text)
    except Exception:
        try:
            print(text.encode(sys.stdout.encoding or "ascii", errors="replace").decode(sys.stdout.encoding or "ascii"))
        except Exception:
            pass

def send_fire_alert_email_worker(area_name, duration_sec, angle_info, frame_bgr=None):
    """
    Worker background thread untuk mengirimkan email via SMTP tanpa memblokir kamera.
    """
    cfg = load_email_config()
    if not cfg.get("enabled", True):
        safe_print("[EMAIL] Pengiriman email dinonaktifkan di konfigurasi.")
        return

    timestamp_str = datetime.now().strftime("%d %B %Y, %H:%M:%S WIB")
    timestamp_filename = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Simpan tangkapan foto jika ada frame
    snapshot_path = None
    if frame_bgr is not None:
        try:
            os.makedirs(SNAPSHOT_DIR, exist_ok=True)
            snapshot_path = os.path.join(SNAPSHOT_DIR, f"kebakaran_{timestamp_filename}.jpg")
            cv2.imwrite(snapshot_path, frame_bgr)
            safe_print(f"[EMAIL] Foto bukti disimpan ke: {snapshot_path}")
        except Exception as e:
            safe_print(f"[EMAIL] Gagal menyimpan foto: {e}")

    # 2. Siapkan konten pesan
    plain_body, html_body = build_email_content(area_name, duration_sec, angle_info, timestamp_str)
    subject = f"[DARURAT DAMKAR] Kebakaran di {area_name} Tidak Padam ({duration_sec:.0f}s)"

    # 3. Catat ke file log lokal (selalu tersimpan sebagai rekam jejak resmi)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*75}\n")
            f.write(f"LOG DISPATCH DAMKAR: {timestamp_str}\n")
            f.write(f"Area: {area_name} | Durasi: {duration_sec:.1f}s | Sudut: {angle_info}\n")
            if snapshot_path:
                f.write(f"Foto: {snapshot_path}\n")
            f.write(plain_body)
    except Exception as e:
        safe_print(f"[EMAIL LOG ERROR] {e}")

    # 4. Kirim melalui SMTP jika sender_password diisi
    sender_email = cfg.get("sender_email", "").strip()
    sender_password = cfg.get("sender_password", "").strip()
    recipient_emails = cfg.get("recipient_emails", [])
    if isinstance(recipient_emails, str):
        recipient_emails = [r.strip() for r in recipient_emails.split(",") if r.strip()]

    if not sender_password:
        safe_print("\n" + "=" * 75)
        safe_print(" [EMAIL DAMKAR] BERHASIL DIPROSES (SIMULASI / LOG LOKAL TERSIMPAN)")
        safe_print(f" Tujuan   : {', '.join(recipient_emails)}")
        safe_print(f" Subjek   : {subject}")
        safe_print(f" Log File : {LOG_PATH}")
        safe_print(" *Catatan : Untuk mengirim email sungguhan via Gmail, isi 'sender_password'")
        safe_print("            (App Password) di file: data/email_config.json")
        safe_print("=" * 75 + "\n")
        return

    # Kirim via SMTP asli
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"AIoT Forest Protection <{sender_email}>"
        msg["To"] = ", ".join(recipient_emails)

        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Lampirkan foto jika ada
        if snapshot_path and os.path.exists(snapshot_path):
            try:
                with open(snapshot_path, "rb") as img_f:
                    img_data = img_f.read()
                    img_part = MIMEImage(img_data, name=os.path.basename(snapshot_path))
                    img_part.add_header("Content-ID", "<snapshot_fire>")
                    img_part.add_header("Content-Disposition", "attachment", filename="bukti_kebakaran.jpg")
                    msg.attach(img_part)
            except Exception as e:
                safe_print(f"[EMAIL] Gagal melampirkan foto: {e}")

        smtp_server = cfg.get("smtp_server", "smtp.gmail.com")
        smtp_port = int(cfg.get("smtp_port", 587))
        use_tls = cfg.get("use_tls", True)

        sent = False
        last_err = None

        # Percobaan 1: Menggunakan konfigurasi utama (default 587 STARTTLS)
        try:
            safe_print(f"[EMAIL] Menghubungkan ke SMTP {smtp_server}:{smtp_port}...")
            if use_tls and smtp_port != 465:
                context = ssl.create_default_context()
                with smtplib.SMTP(smtp_server, smtp_port, timeout=12) as server:
                    server.starttls(context=context)
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, recipient_emails, msg.as_string())
                sent = True
            else:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(smtp_server, 465, context=context, timeout=12) as server:
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, recipient_emails, msg.as_string())
                sent = True
        except Exception as e1:
            last_err = e1
            fallback_port = 465 if smtp_port != 465 else 587
            safe_print(f"[EMAIL] Port {smtp_port} gagal ({e1}), mencoba fallback ke port {fallback_port}...")
            try:
                context = ssl.create_default_context()
                if fallback_port == 465:
                    with smtplib.SMTP_SSL(smtp_server, 465, context=context, timeout=12) as server:
                        server.login(sender_email, sender_password)
                        server.sendmail(sender_email, recipient_emails, msg.as_string())
                    sent = True
                else:
                    with smtplib.SMTP(smtp_server, 587, timeout=12) as server:
                        server.starttls(context=context)
                        server.login(sender_email, sender_password)
                        server.sendmail(sender_email, recipient_emails, msg.as_string())
                    sent = True
            except Exception as e2:
                last_err = e2

        if sent:
            safe_print(f"\n[+] EMAIL DARURAT BERHASIL DIKIRIMKAN KE DAMKAR: {recipient_emails}")
        else:
            safe_print(f"\n[!] Gagal mengirim email via SMTP ({last_err}). Log laporan tetap tersimpan di {LOG_PATH}")

    except Exception as e:
        safe_print(f"\n[!] Gagal menyiapkan email ({e}). Log laporan tetap tersimpan di {LOG_PATH}")


def send_fire_alert_email_async(area_name, duration_sec, angle_info, frame_bgr=None):
    """
    Memulai pengiriman email di thread terpisah agar proses AI & Servo tidak terhambat.
    """
    # Salin frame agar aman dari race condition thread
    frame_copy = frame_bgr.copy() if frame_bgr is not None else None
    th = threading.Thread(
        target=send_fire_alert_email_worker,
        args=(area_name, duration_sec, angle_info, frame_copy),
        daemon=True
    )
    th.start()
    return th


if __name__ == "__main__":
    # Test pengiriman / pembuatan format email
    print("Menguji modul email darurat damkar...")
    test_frame = None
    send_fire_alert_email_worker(
        area_name="Area 2 (Wilayah Hutan Lindung)",
        duration_sec=15.2,
        angle_info="Servo 2 Terarah pada 68°",
        frame_bgr=test_frame
    )
