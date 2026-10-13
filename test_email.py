"""
=============================================================================
 AIoT Forest Protection - Script Pengujian & Verifikasi Pengiriman Email
=============================================================================
Jalankan file ini untuk mengetes apakah notifikasi email benar-benar bisa
terkirim dan masuk ke Inbox email Anda:
    python test_email.py
=============================================================================
"""

import os
import sys
import json
from email_notifier import (
    load_email_config,
    save_email_config,
    send_fire_alert_email_worker,
    send_tree_fall_email_worker,
    send_illegal_logging_email_worker,
    CONFIG_PATH
)

def main():
    print("=" * 75)
    print(" [DIAGNOSTIK & TEST PENGIRIMAN EMAIL NOTIFIKASI TERPADU]")
    print("=" * 75)

    cfg = load_email_config()
    sender_email = cfg.get("sender_email", "").strip()
    sender_password = cfg.get("sender_password", "").strip()
    recipients = cfg.get("recipient_emails", [])
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",") if r.strip()]

    print(f"File Konfigurasi : {CONFIG_PATH}")
    print(f"1. Email Pengirim  (sender_email)    : {sender_email}")
    print(f"2. Password App    (sender_password) : {'[SUDAH DIISI]' if sender_password else '[MASIH KOSONG / BELUM DIISI!]'}")
    print(f"3. Email Penerima  (recipient_emails): {', '.join(recipients)}")
    print("-" * 75)

    if not sender_password or sender_email == "sistem.aiot.forest@gmail.com":
        print("[!] PERHATIAN: Sandi aplikasi Gmail belum diisi.")
        print("   Email akan dicatat ke berkas log lokal data/email_alerts.log (Mode Simulasi).")
        print("   Untuk mengirim email asli ke Inbox:")
        print("   1. Buka https://myaccount.google.com/apppasswords")
        print("   2. Buat App Password (16 digit)")
        print("   3. Masukkan ke file: data/email_config.json")
        print("=" * 75)

    print("\nPilih jenis email yang ingin diuji:")
    print("1. 🚨 Laporan Darurat Kebakaran Hutan (Damkar)")
    print("2. 🍃 Laporan Pohon Jatuh Alami (Konservasi)")
    print("3. 🪓 Peringatan Pembalakan Liar / Pohon Ditebang (Polisi Kehutanan)")
    print("4. 🔥 Uji Semua Jenis Sekaligus (1, 2, dan 3)")

    try:
        pilihan = input("\nMasukkan nomor pilihan (1/2/3/4) [Default 1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        pilihan = "1"

    if not pilihan:
        pilihan = "1"

    print("-" * 75)
    if pilihan == "1" or pilihan == "4":
        print("[>] Mengirimkan Uji Coba: Laporan Darurat Kebakaran Hutan (Damkar)...")
        send_fire_alert_email_worker(
            area_name="Area 1 (SEKTOR BARAT - UJI DAMKAR)",
            duration_sec=16.5,
            angle_info="Servo 1 Terarah pada 82°",
            frame_bgr=None
        )

    if pilihan == "2" or pilihan == "4":
        print("\n[>] Mengirimkan Uji Coba: Laporan Pohon Jatuh Alami (Konservasi)...")
        send_tree_fall_email_worker(
            area_name="Area 2 (SEKTOR TIMUR - POHON TUMBANG)",
            conf=0.94,
            frame_bgr=None
        )

    if pilihan == "3" or pilihan == "4":
        print("\n[>] Mengirimkan Uji Coba: Peringatan Pohon Ditebang / Logging (Polhut)...")
        send_illegal_logging_email_worker(
            area_name="Area 1 (SEKTOR HUTAN LINDUNG - UJI PATROLI)",
            conf=0.88,
            frame_bgr=None
        )

    print("\n" + "=" * 75)
    print("[SELESAI] Silakan periksa Kotak Masuk (Inbox) / Folder Spam email penerima:")
    print(f"          {recipients}")
    print("          Dan periksa berkas log rekam jejak: data/email_alerts.log")
    print("=" * 75)

if __name__ == "__main__":
    main()
