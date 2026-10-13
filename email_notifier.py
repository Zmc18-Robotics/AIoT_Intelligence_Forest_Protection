"""
=============================================================================
 AIoT Forest Protection - Modul Notifikasi Email Petugas Cerdas Terpadu
=============================================================================
Fungsi:
  1. Notifikasi Darurat Damkar:
     - Mengirimkan email darurat jika api terdeteksi tidak kunjung padam (> 15s).
  2. Notifikasi Pohon Jatuh Alami:
     - Mengirimkan email laporan insiden pohon tumbang alami ke Petugas Konservasi.
  3. Notifikasi Pohon Ditebang (Illegal Logging):
     - Mengirimkan email peringatan darurat ke Polisi Kehutanan / Tim Patroli.
  - Fitur:
     - Anti-Spam / Cooldown otomatis (mencegah penumpukan email per zona).
     - Lampiran foto bukti snapshot kamera otomatis (.jpg).
     - Format laporan resmi teks rapi dan HTML profesional.
     - Asynchronous background thread (tidak memblokir inferensi AI & kontrol servo).
     - Pencatatan rekam jejak resmi ke berkas data/email_alerts.log.
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
TREE_SNAPSHOT_DIR = os.path.join(ROOT_DIR, "data", "tree_alerts")

DEFAULT_EMAIL_CONFIG = {
    "enabled": True,
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "use_tls": True,
    "sender_email": "-",
    "sender_password": "-",
    "recipient_emails": [
        "-"
    ],
    "fire_timeout_seconds": 15,
    "cooldown_seconds": 30
}

# Cooldown tracker anti-spam per-kategori dan per-area
_cooldown_lock = threading.Lock()
_last_sent_times = {
    "tree_fall": {},
    "illegal_logging": {},
    "fire": 0.0
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


def safe_print(text):
    try:
        print(text)
    except Exception:
        try:
            print(text.encode(sys.stdout.encoding or "ascii", errors="replace").decode(sys.stdout.encoding or "ascii"))
        except Exception:
            pass


# =============================================================================
#  PEMBUAT KONTEN EMAIL (HTML & TEXT)
# =============================================================================

def build_email_content(area_name, duration_sec, angle_info, timestamp_str):
    """Laporan Darurat Kebakaran Hutan ke Damkar."""
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
          <td class="value">ESP32-CAM (AI Vision Tracking)</td>
        </tr>
      </table>

      <div class="instructions">
        <h4>📋 Protokol Petugas Damkar:</h4>
        <ol>
          <li>Segera luncurkan armada damkar sektor terdekat menuju <strong>{area_name}</strong>.</li>
          <li>Bawa pasokan tangki air cadangan untuk memadamkan bara inti.</li>
          <li>Lakukan penyisiran dan pemutusan vegetasi kering di sekitar titik panas.</li>
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


def build_tree_fall_content(area_name, conf, timestamp_str):
    """Laporan Deteksi Pohon Jatuh Alami ke Petugas Konservasi."""
    conf_pct = int(conf * 100) if conf <= 1.0 else int(conf)
    plain_text = f"""
================================================================================
        LAPORAN INSIDEN: POHON JATUH ALAMI (NATURAL TREE FALL DETECTED)
================================================================================
STATUS         : TERDETEKSI - POHON TUMBANG SECARA ALAMI
SISTEM DETEKSI : AIoT Forest Protection Vision Engine (ESP32-CAM)
WAKTU INSIDEN  : {timestamp_str}
SEKTOR LOKASI  : {area_name}
TINGKAT AKURASI: {conf_pct}%
--------------------------------------------------------------------------------
DESKRIPSI SITUASI:
Kamera pengawas AI mendeteksi keberadaan pohon tumbang atau roboh secara alami
akibat faktor usia, pelapukan akar, atau hembusan angin kencang di {area_name}.
Data insiden telah otomatis dicatat ke database lokal sistem.

TINDAKAN YANG DIREKOMENDASIKAN:
1. Lakukan pemantauan dan pengecekan jalur lintasan di sektor {area_name}.
2. Pastikan pohon tumbang tidak menimpa kabel instalasi sensor atau menghalangi akses satwa.
3. Lakukan pemangkasan dahan jika mengganggu jalur patroli konservasi.
================================================================================
Sistem Otomasi AIoT Kehutanan - Laporan Konservasi Lingkungan
"""

    html_text = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f0fdf4; color: #1e293b; margin: 0; padding: 20px; }}
    .container {{ max-width: 650px; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin: auto; border-top: 6px solid #10b981; }}
    .header {{ background: #059669; color: #ffffff; padding: 24px 30px; }}
    .header h1 {{ margin: 0; font-size: 21px; }}
    .header p {{ margin: 6px 0 0; font-size: 14px; opacity: 0.95; }}
    .badge {{ display: inline-block; background: #d1fae5; color: #065f46; font-weight: bold; padding: 4px 12px; border-radius: 20px; font-size: 13px; margin-top: 10px; }}
    .body {{ padding: 25px 30px; }}
    .table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
    .table td {{ padding: 10px 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; }}
    .table td.label {{ font-weight: bold; color: #475569; width: 35%; background: #f8fafc; }}
    .table td.value {{ color: #0f172a; font-weight: 600; }}
    .info-box {{ background: #ecfdf5; border-left: 4px solid #10b981; padding: 14px 18px; border-radius: 6px; margin: 18px 0; }}
    .info-box h3 {{ margin: 0 0 6px; color: #047857; font-size: 16px; }}
    .info-box p {{ margin: 0; font-size: 14px; line-height: 1.5; color: #064e3b; }}
    .instructions {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px 18px; border-radius: 6px; margin: 20px 0; }}
    .instructions h4 {{ margin: 0 0 8px; color: #334155; font-size: 15px; }}
    .instructions ul {{ margin: 0; padding-left: 20px; font-size: 14px; color: #475569; line-height: 1.6; }}
    .footer {{ background: #f8fafc; padding: 16px 30px; font-size: 12px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🍃 LAPORAN POHON JATUH ALAMI</h1>
      <p>Sistem Pengawasan Konservasi Hutan Otomatis</p>
      <div class="badge">STATUS: TERCATAT KE DATABASE LOKAL</div>
    </div>
    <div class="body">
      <div class="info-box">
        <h3>ℹ️ Deteksi Pohon Tumbang Alami</h3>
        <p>Telah terdeteksi pohon roboh secara alami di <strong>{area_name}</strong>. Data telah dimasukkan ke database inventaris pohon tumbang untuk analisis vegetasi berkala.</p>
      </div>

      <table class="table">
        <tr>
          <td class="label">Sektor Wilayah</td>
          <td class="value" style="color: #059669;">{area_name}</td>
        </tr>
        <tr>
          <td class="label">Waktu Deteksi</td>
          <td class="value">{timestamp_str}</td>
        </tr>
        <tr>
          <td class="label">Tingkat Akurasi AI</td>
          <td class="value">{conf_pct}% (Confidence)</td>
        </tr>
        <tr>
          <td class="label">Kategori</td>
          <td class="value">Pohon Jatuh Alami (Natural Fall)</td>
        </tr>
      </table>

      <div class="instructions">
        <h4>📋 Langkah Petugas Konservasi:</h4>
        <ul>
          <li>Lakukan verifikasi visual lapangan saat jadwal patroli rutin berikutnya.</li>
          <li>Periksa apakah jalur pergerakan satwa atau aliran sungai tertutup material batang pohon.</li>
          <li>Perbarui catatan status di sistem database jika pohon telah dievakuasi.</li>
        </ul>
      </div>
      <p style="font-size: 13px; color: #64748b;"><em>*Foto bukti deteksi terlampir pada email ini.</em></p>
    </div>
    <div class="footer">
      AIoT Forest Intelligence Protection System &copy; {datetime.now().year}
    </div>
  </div>
</body>
</html>
"""
    return plain_text, html_text


def build_illegal_logging_content(area_name, conf, timestamp_str):
    """Laporan Darurat Pohon Ditebang / Pembalakan Liar ke Polisi Kehutanan."""
    conf_pct = int(conf * 100) if conf <= 1.0 else int(conf)
    plain_text = f"""
================================================================================
     PERINGATAN DARURAT: POHON DITEBANG / PEMBALAKAN LIAR (ILLEGAL LOGGING)
================================================================================
STATUS         : KRITIS - AKTIVITAS PENEBANGAN POHON TERDETEKSI
SISTEM DETEKSI : AIoT Forest Protection Vision Engine (ESP32-CAM & YOLOv8)
WAKTU INSIDEN  : {timestamp_str}
SEKTOR LOKASI  : {area_name}
TINGKAT AKURASI: {conf_pct}%
--------------------------------------------------------------------------------
DESKRIPSI SITUASI:
Sistem mendeteksi adanya pohon yang ditebang, batang kayu terpotong, atau
indikasi aktivitas pembalakan liar (illegal logging) di sektor lindung {area_name}.
Kejadian ini telah dicatat ke database lokal sebagai insiden keamanan hutan.

TINDAKAN YANG DIPERLUKAN:
1. Kerahkan segera regu Polisi Kehutanan / Satuan Tugas Patroli ke sektor {area_name}.
2. Lakukan penyisiran jalan keluar hutan dan perimeter sekitar lokasi.
3. Amankan barang bukti dan lakukan pendataan kerusakan vegetasi.
================================================================================
Sistem Otomasi AIoT Kehutanan - Peringatan Darurat Keamanan Hutan
"""

    html_text = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #fff7ed; color: #1e293b; margin: 0; padding: 20px; }}
    .container {{ max-width: 650px; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1); margin: auto; border-top: 6px solid #ea580c; }}
    .header {{ background: #ea580c; color: #ffffff; padding: 24px 30px; }}
    .header h1 {{ margin: 0; font-size: 21px; }}
    .header p {{ margin: 6px 0 0; font-size: 14px; opacity: 0.95; }}
    .badge {{ display: inline-block; background: #ffedd5; color: #9a3412; font-weight: bold; padding: 4px 12px; border-radius: 20px; font-size: 13px; margin-top: 10px; }}
    .body {{ padding: 25px 30px; }}
    .table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
    .table td {{ padding: 10px 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; }}
    .table td.label {{ font-weight: bold; color: #475569; width: 35%; background: #f8fafc; }}
    .table td.value {{ color: #0f172a; font-weight: 600; }}
    .danger-box {{ background: #fff7ed; border-left: 4px solid #f97316; padding: 14px 18px; border-radius: 6px; margin: 18px 0; }}
    .danger-box h3 {{ margin: 0 0 6px; color: #c2410c; font-size: 16px; }}
    .danger-box p {{ margin: 0; font-size: 14px; line-height: 1.5; color: #7c2d12; }}
    .instructions {{ background: #fef2f2; border: 1px solid #fecaca; padding: 15px 18px; border-radius: 6px; margin: 20px 0; }}
    .instructions h4 {{ margin: 0 0 8px; color: #991b1b; font-size: 15px; }}
    .instructions ol {{ margin: 0; padding-left: 20px; font-size: 14px; color: #7f1d1d; line-height: 1.6; }}
    .footer {{ background: #f8fafc; padding: 16px 30px; font-size: 12px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🪓 PERINGATAN PEMBALAKAN LIAR / POHON DITEBANG</h1>
      <p>Sistem Pengawasan Keamanan Hutan & Anti-Illegal Logging</p>
      <div class="badge">STATUS: INSIDEN KEAMANAN KRITIS</div>
    </div>
    <div class="body">
      <div class="danger-box">
        <h3>⚠️ Aktivitas Penebangan Pohon Terdeteksi</h3>
        <p>Kamera AI mendeteksi sisa potongan pohon atau penebangan di <strong>{area_name}</strong>. Diperlukan tindakan cepat regu patroli untuk mencegah kerusakan lebih lanjut.</p>
      </div>

      <table class="table">
        <tr>
          <td class="label">Sektor Wilayah</td>
          <td class="value" style="color: #ea580c;">{area_name}</td>
        </tr>
        <tr>
          <td class="label">Waktu Deteksi</td>
          <td class="value">{timestamp_str}</td>
        </tr>
        <tr>
          <td class="label">Tingkat Akurasi AI</td>
          <td class="value">{conf_pct}% (Confidence)</td>
        </tr>
        <tr>
          <td class="label">Kategori Insiden</td>
          <td class="value">Pohon Ditebang (Illegal Logging)</td>
        </tr>
      </table>

      <div class="instructions">
        <h4>📋 Protokol Petugas Patroli / Polhut:</h4>
        <ol>
          <li>Segera kirimkan regu patroli berseragam ke sektor <strong>{area_name}</strong>.</li>
          <li>Tutup dan periksa pintu keluar-masuk kendaraan logistik di sekitar area.</li>
          <li>Amankan barang bukti gergaji mesin, kendaraan, atau kayu tebangan di lokasi.</li>
        </ol>
      </div>
      <p style="font-size: 13px; color: #64748b;"><em>*Foto bukti snapshot kamera AI terlampir pada email ini.</em></p>
    </div>
    <div class="footer">
      AIoT Forest Intelligence Protection System &copy; {datetime.now().year}
    </div>
  </div>
</body>
</html>
"""
    return plain_text, html_text


# =============================================================================
#  PENGIRIM EMAIL GENERIK (SMTP WITH TLS/SSL FALLBACK)
# =============================================================================

def _send_smtp_email_worker(subject, plain_body, html_body, snapshot_path, log_tag, area_name, details_info):
    """Fungsi pembantu pengiriman email via SMTP dengan pencatatan log lokal."""
    cfg = load_email_config()
    if not cfg.get("enabled", True):
        safe_print(f"[{log_tag}] Pengiriman email dinonaktifkan di konfigurasi.")
        return False

    timestamp_str = datetime.now().strftime("%d %B %Y, %H:%M:%S WIB")

    # 1. Catat ke file log lokal (rekam jejak permanen)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*75}\n")
            f.write(f"LOG DISPATCH [{log_tag}]: {timestamp_str}\n")
            f.write(f"Area: {area_name} | Info: {details_info}\n")
            if snapshot_path:
                f.write(f"Foto Lampiran: {snapshot_path}\n")
            f.write(plain_body)
    except Exception as e:
        safe_print(f"[{log_tag} LOG ERROR] {e}")

    sender_email = cfg.get("sender_email", "").strip()
    sender_password = cfg.get("sender_password", "").strip()
    recipient_emails = cfg.get("recipient_emails", [])
    if isinstance(recipient_emails, str):
        recipient_emails = [r.strip() for r in recipient_emails.split(",") if r.strip()]

    # Jika sandi belum diisi, simpan log simulasi
    if not sender_password:
        safe_print("\n" + "=" * 75)
        safe_print(f" [{log_tag}] BERHASIL DIPROSES (SIMULASI / LOG LOKAL TERSIMPAN)")
        safe_print(f" Tujuan   : {', '.join(recipient_emails)}")
        safe_print(f" Subjek   : {subject}")
        safe_print(f" Log File : {LOG_PATH}")
        safe_print(" *Catatan : Untuk mengirim email sungguhan via Gmail, isi 'sender_password'")
        safe_print("            (App Password) di file: data/email_config.json")
        safe_print("=" * 75 + "\n")
        return True

    # 2. Kirim via SMTP asli
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
                    img_part.add_header("Content-Disposition", "attachment", filename=os.path.basename(snapshot_path))
                    msg.attach(img_part)
            except Exception as e:
                safe_print(f"[{log_tag}] Gagal melampirkan foto: {e}")

        smtp_server = cfg.get("smtp_server", "smtp.gmail.com")
        smtp_port = int(cfg.get("smtp_port", 587))
        use_tls = cfg.get("use_tls", True)

        sent = False
        last_err = None

        # Percobaan 1: Port 587 STARTTLS
        try:
            safe_print(f"[{log_tag}] Menghubungkan ke SMTP {smtp_server}:{smtp_port}...")
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
            safe_print(f"[{log_tag}] Port {smtp_port} gagal ({e1}), mencoba fallback ke port {fallback_port}...")
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
            safe_print(f"\n[+] EMAIL [{log_tag}] BERHASIL DIKIRIM KE: {recipient_emails}")
            return True
        else:
            safe_print(f"\n[!] Gagal mengirim email via SMTP ({last_err}). Log tersimpan di {LOG_PATH}")
            return False

    except Exception as e:
        safe_print(f"\n[!] Gagal menyiapkan email ({e}). Log tersimpan di {LOG_PATH}")
        return False


# =============================================================================
#  ENDPOINT PUBLIK NOTIFIKASI
# =============================================================================

# --- 1. EMAIL DAMKAR (FIRE ESCALATION) ---
def send_fire_alert_email_worker(area_name, duration_sec, angle_info, frame_bgr=None):
    timestamp_str = datetime.now().strftime("%d %B %Y, %H:%M:%S WIB")
    timestamp_filename = datetime.now().strftime("%Y%m%d_%H%M%S")

    snapshot_path = None
    if frame_bgr is not None:
        try:
            os.makedirs(SNAPSHOT_DIR, exist_ok=True)
            snapshot_path = os.path.join(SNAPSHOT_DIR, f"kebakaran_{timestamp_filename}.jpg")
            cv2.imwrite(snapshot_path, frame_bgr)
            safe_print(f"[EMAIL DAMKAR] Foto bukti kebakaran disimpan ke: {snapshot_path}")
        except Exception as e:
            safe_print(f"[EMAIL DAMKAR] Gagal simpan foto: {e}")

    plain_body, html_body = build_email_content(area_name, duration_sec, angle_info, timestamp_str)
    subject = f"[DARURAT DAMKAR] Kebakaran di {area_name} Belum Padam ({duration_sec:.0f}s)"

    return _send_smtp_email_worker(
        subject=subject,
        plain_body=plain_body,
        html_body=html_body,
        snapshot_path=snapshot_path,
        log_tag="EMAIL DAMKAR",
        area_name=area_name,
        details_info=f"Durasi: {duration_sec:.1f}s | Sudut: {angle_info}"
    )


def send_fire_alert_email_async(area_name, duration_sec, angle_info, frame_bgr=None):
    frame_copy = frame_bgr.copy() if frame_bgr is not None else None
    th = threading.Thread(
        target=send_fire_alert_email_worker,
        args=(area_name, duration_sec, angle_info, frame_copy),
        daemon=True
    )
    th.start()
    return th


# --- 2. EMAIL POHON JATUH ALAMI (NATURAL TREE FALL) ---
def send_tree_fall_email_worker(area_name, conf=0.0, frame_bgr=None):
    # Cek Cooldown Anti-Spam
    now = time.time()
    cfg = load_email_config()
    cooldown = cfg.get("cooldown_seconds", 30)

    with _cooldown_lock:
        last_t = _last_sent_times["tree_fall"].get(area_name, 0.0)
        if now - last_t < cooldown:
            safe_print(f"[EMAIL POHON JATUH] Cooldown aktif untuk {area_name} ({int(cooldown - (now - last_t))}s lagi). Dilewati.")
            return False
        _last_sent_times["tree_fall"][area_name] = now

    timestamp_str = datetime.now().strftime("%d %B %Y, %H:%M:%S WIB")
    timestamp_filename = datetime.now().strftime("%Y%m%d_%H%M%S")

    snapshot_path = None
    if frame_bgr is not None:
        try:
            os.makedirs(TREE_SNAPSHOT_DIR, exist_ok=True)
            snapshot_path = os.path.join(TREE_SNAPSHOT_DIR, f"pohon_jatuh_{timestamp_filename}.jpg")
            cv2.imwrite(snapshot_path, frame_bgr)
            safe_print(f"[EMAIL POHON JATUH] Foto bukti disimpan: {snapshot_path}")
        except Exception as e:
            safe_print(f"[EMAIL POHON JATUH] Gagal simpan foto: {e}")

    plain_body, html_body = build_tree_fall_content(area_name, conf, timestamp_str)
    conf_pct = int(conf * 100) if conf <= 1.0 else int(conf)
    subject = f"[INFO KONSERVASI] Pohon Jatuh Alami Terdeteksi di {area_name} ({conf_pct}%)"

    return _send_smtp_email_worker(
        subject=subject,
        plain_body=plain_body,
        html_body=html_body,
        snapshot_path=snapshot_path,
        log_tag="POHON JATUH ALAMI",
        area_name=area_name,
        details_info=f"Confidence: {conf_pct}%"
    )


def send_tree_fall_email_async(area_name, conf=0.0, frame_bgr=None):
    frame_copy = frame_bgr.copy() if frame_bgr is not None else None
    th = threading.Thread(
        target=send_tree_fall_email_worker,
        args=(area_name, conf, frame_copy),
        daemon=True
    )
    th.start()
    return th


# --- 3. EMAIL POHON DITEBANG / ILLEGAL LOGGING ---
def send_illegal_logging_email_worker(area_name, conf=0.0, frame_bgr=None):
    # Cek Cooldown Anti-Spam
    now = time.time()
    cfg = load_email_config()
    cooldown = cfg.get("cooldown_seconds", 30)

    with _cooldown_lock:
        last_t = _last_sent_times["illegal_logging"].get(area_name, 0.0)
        if now - last_t < cooldown:
            safe_print(f"[EMAIL ILLEGAL LOGGING] Cooldown aktif untuk {area_name} ({int(cooldown - (now - last_t))}s lagi). Dilewati.")
            return False
        _last_sent_times["illegal_logging"][area_name] = now

    timestamp_str = datetime.now().strftime("%d %B %Y, %H:%M:%S WIB")
    timestamp_filename = datetime.now().strftime("%Y%m%d_%H%M%S")

    snapshot_path = None
    if frame_bgr is not None:
        try:
            os.makedirs(TREE_SNAPSHOT_DIR, exist_ok=True)
            snapshot_path = os.path.join(TREE_SNAPSHOT_DIR, f"pohon_ditebang_{timestamp_filename}.jpg")
            cv2.imwrite(snapshot_path, frame_bgr)
            safe_print(f"[EMAIL ILLEGAL LOGGING] Foto bukti disimpan: {snapshot_path}")
        except Exception as e:
            safe_print(f"[EMAIL ILLEGAL LOGGING] Gagal simpan foto: {e}")

    plain_body, html_body = build_illegal_logging_content(area_name, conf, timestamp_str)
    conf_pct = int(conf * 100) if conf <= 1.0 else int(conf)
    subject = f"[DARURAT PATROLI] Pembalakan Liar / Pohon Ditebang di {area_name} ({conf_pct}%)"

    return _send_smtp_email_worker(
        subject=subject,
        plain_body=plain_body,
        html_body=html_body,
        snapshot_path=snapshot_path,
        log_tag="ILLEGAL LOGGING",
        area_name=area_name,
        details_info=f"Confidence: {conf_pct}%"
    )


def send_illegal_logging_email_async(area_name, conf=0.0, frame_bgr=None):
    frame_copy = frame_bgr.copy() if frame_bgr is not None else None
    th = threading.Thread(
        target=send_illegal_logging_email_worker,
        args=(area_name, conf, frame_copy),
        daemon=True
    )
    th.start()
    return th


if __name__ == "__main__":
    print("Menguji modul email terpadu (Damkar, Pohon Jatuh, Pohon Ditebang)...")
    send_tree_fall_email_worker(
        area_name="Area 1 (Hutan Konservasi Sektor Barat)",
        conf=0.92,
        frame_bgr=None
    )
