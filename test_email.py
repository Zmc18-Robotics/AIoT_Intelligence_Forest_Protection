"""
=============================================================================
 AIoT Forest Protection - Script Pengujian & Verifikasi Pengiriman Email
=============================================================================
Jalankan file ini untuk mengetes apakah email darurat benar-benar bisa
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
    CONFIG_PATH
)

def main():
    print("=" * 75)
    print(" [DIAGNOSTIK & TEST PENGIRIMAN EMAIL DARURAT DAMKAR]")
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
        print("[!] PENYEBAB EMAIL TIDAK MASUK KE INBOX:")
        print("   Google/Gmail membutuhkan akun Gmail asli dan 'Sandi Aplikasi' (16 digit)")
        print("   untuk bisa mengirim email lewat internet.")
        print()
        print("   Saat ini:")
        if sender_email == "sistem.aiot.forest@gmail.com":
            print("   - 'sender_email' masih menggunakan email contoh (sistem.aiot.forest@gmail.com)")
        if not sender_password:
            print("   - 'sender_password' masih KOSONG (\"\")")
        print()
        print("=" * 75)
        print("CARA MENGAKTIFKAN EMAIL ASLI GMAIL (HANYA BUTUH 1 MENIT):")
        print("=" * 75)
        print("1. Buka browser: https://myaccount.google.com/apppasswords")
        print("   (Pastikan Verifikasi 2 Langkah / 2-Step Verification pada akun Google Anda sudah AKTIF)")
        print("2. Masukkan nama aplikasi, contoh: AIoT UTS")
        print("3. Google akan memberikan 16 digit huruf (contoh: abcd efgh ijkl mnop)")
        print("4. Buka file: data/email_config.json")
        print("   Lalu isi:")
        print('   "sender_email": "email_anda@gmail.com",')
        print('   "sender_password": "16 digit sandi aplikasi tadi",')
        print('   "recipient_emails": ["email_anda@gmail.com"]')
        print("=" * 75)

        # Beri opsi input interaktif jika dijalankan manual di terminal
        try:
            print("\nApakah Anda ingin mengisi email & sandi sekarang di terminal ini? (y/n)")
            ans = input("Pilihan: ").strip().lower()
            if ans == 'y':
                new_sender = input("Masukkan Email Pengirim (Gmail): ").strip()
                new_pass = input("Masukkan Sandi Aplikasi Google (16 huruf): ").strip()
                new_recp = input("Masukkan Email Penerima (bisa sama dengan pengirim): ").strip()

                if new_sender and new_pass and new_recp:
                    cfg["sender_email"] = new_sender
                    cfg["sender_password"] = new_pass
                    cfg["recipient_emails"] = [new_recp]
                    save_email_config(cfg)
                    print("\n[+] Konfigurasi berhasil disimpan ke data/email_config.json!")
                    sender_email = new_sender
                    sender_password = new_pass
                    recipients = [new_recp]
                else:
                    print("[!] Input tidak lengkap. Pembatalan.")
                    return
            else:
                return
        except (EOFError, KeyboardInterrupt):
            return

    # Kirim test email sekarang jika password sudah ada
    print(f"\n[>] Mengirimkan Email Uji Coba ke {recipients} sekarang...")
    send_fire_alert_email_worker(
        area_name="Area 2 (SEKTOR TIMUR - UJI COBA)",
        duration_sec=15.0,
        angle_info="Servo 2 Terarah pada 45°",
        frame_bgr=None
    )
    print("\n[SELESAI] Silakan cek kotak masuk (Inbox) atau folder Spam pada email penerima.")

if __name__ == "__main__":
    main()
