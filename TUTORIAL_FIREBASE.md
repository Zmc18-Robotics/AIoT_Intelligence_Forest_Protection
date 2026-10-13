# 🔥 Tutorial Firebase Realtime Database
## AIoT Intelligence Forest Protection System

> **Tujuan:** Agar semua data telemetri, insiden, dan status sistem yang direkam di hutan dapat dipantau secara **publik/global** dari mana saja melalui internet — bukan hanya dari WiFi lokal.

---

## 📋 Ringkasan Arsitektur

```
ESP32 (sensor)
     │  TCP
     ▼
Python Server (server.py)
     │
     ├──► Database Lokal (forest_database.json)  ← akses lewat WiFi lokal
     │
     └──► Firebase Cloud (Realtime DB) ──────────► Dipantau dari mana saja
              ↕ REST API (python_backend/firebase_manager.py)
```

---

## 🚀 Langkah Setup (±5 menit)

### **LANGKAH 1 — Buat Akun & Proyek Firebase**

1. Buka **[https://console.firebase.google.com](https://console.firebase.google.com)**
2. Login dengan akun Google Anda
3. Klik **"Add project"** (Tambah proyek)
4. Beri nama proyek, misalnya: `aiot-forest-protection`
5. Matikan Google Analytics (opsional, klik *disable*)
6. Klik **"Create project"** → tunggu selesai → klik **"Continue"**

---

### **LANGKAH 2 — Aktifkan Realtime Database**

1. Di sidebar kiri, klik **"Build"** → **"Realtime Database"**
2. Klik tombol **"Create Database"**
3. Pilih lokasi server terdekat, misalnya: `asia-southeast1 (Singapore)` ✅
4. Di layar *Security Rules*, pilih: **"Start in test mode"** (untuk kemudahan saat development)
5. Klik **"Enable"**

> ⚠️ **"Test mode"** = siapa saja bisa baca & tulis selama 30 hari.
> Setelah sistem stabil, ubah rules agar hanya bisa ditulis oleh server.

---

### **LANGKAH 3 — Salin URL Database Anda**

Setelah database aktif, Anda akan melihat URL seperti ini di bagian atas:

```
https://aiot-forest-protection-default-rtdb.firebaseio.com/
```

> **Setiap proyek memiliki URL unik!** Salin URL ini — ini yang akan dimasukkan ke kode.

---

### **LANGKAH 4 — Masukkan URL ke Kode**

Buka file: **`data/firebase_config.json`**

```json
{
  "enabled": true,
  "database_url": "https://NAMA-PROYEK-ANDA-default-rtdb.firebaseio.com",
  "auth_token": "",
  "sync_interval_seconds": 3
}
```

**Ganti** nilai `database_url` dengan URL yang Anda salin di Langkah 3.

**Contoh konfigurasi jadi:**
```json
{
  "enabled": true,
  "database_url": "https://aiot-forest-protection-default-rtdb.firebaseio.com",
  "auth_token": "",
  "sync_interval_seconds": 3
}
```

---

### **LANGKAH 5 — Verifikasi: Jalankan Server**

```bash
cd python_backend
python server.py
```

Jika berhasil, Anda akan melihat log:
```
[FIREBASE] ✅ Data insiden #1 berhasil dikirim ke Cloud Firebase!
```

---

### **LANGKAH 6 — Pantau Data di Firebase Console**

1. Buka **[https://console.firebase.google.com](https://console.firebase.google.com)** → proyek Anda
2. Klik **"Realtime Database"** di sidebar
3. Anda akan melihat struktur data seperti ini secara realtime:

```json
forest_protection/
├── telemetry/
│   ├── distance_cm: 15.3
│   ├── flame_pin: 1
│   ├── flame_hw_danger: false
│   └── timestamp: "2026-10-13 12:00:00"
├── counters/
│   ├── pohon_jatuh_alami: 2
│   ├── pohon_ditebang: 0
│   ├── insiden_api: 1
│   └── objek_masuk_ultrasonik: 5
├── events/        ← riwayat semua insiden
├── last_incident/ ← insiden terakhir
└── system_status/
    ├── esp32_cam_connected: true
    └── esp32_main_connected: true
```

---

## 🌐 Cara Akses Publik (Tanpa Login)

Siapa pun bisa membaca data via URL langsung:

```
https://NAMA-PROYEK-default-rtdb.firebaseio.com/forest_protection.json
```

Buka di browser mana pun → data JSON sistem tampil! ✅

---

## 📊 Data yang Dikirim ke Firebase

| Jalur Firebase | Isi Data | Frekuensi Update |
|---|---|---|
| `telemetry/` | Jarak ultrasonik, sensor api, timestamp | Setiap paket dari ESP32 |
| `counters/` | Jumlah insiden per kategori | Setiap ada insiden baru |
| `last_incident/` | Detail insiden terakhir | Setiap ada insiden baru |
| `events/` | Riwayat semua insiden (push list) | Setiap ada insiden baru |
| `system_status/` | Status koneksi ESP32-CAM & Main | Setiap ada perubahan |

---

## 🔒 Keamanan (Opsional — Setelah Stabil)

Untuk membatasi **write hanya dari server** tapi **read bebas**:

1. Di Firebase Console → Realtime Database → **"Rules"**
2. Ganti dengan:

```json
{
  "rules": {
    ".read": true,
    ".write": false
  }
}
```

3. Untuk write dari server, generate **Database Secret**:
   - Klik ⚙️ (Settings) → **Project Settings** → **Service Accounts**
   - Klik **"Database secrets"** → **"Show"** → salin token
   - Masukkan ke `firebase_config.json` di field `"auth_token"`

---

## ❓ Troubleshooting

| Masalah | Solusi |
|---|---|
| Tidak ada data masuk ke Firebase | Periksa `database_url` di `firebase_config.json` — harus valid & berakhiran `.firebaseio.com` |
| Error `Permission denied` | Pastikan rules database masih "test mode" atau tambahkan `auth_token` |
| Log `[FIREBASE CLOUD] [!] Gagal kirim telemetri` | Cek koneksi internet komputer server |
| Data lama / tidak update | Refresh halaman Firebase Console |

---

*Dokumentasi ini merupakan bagian dari sistem AIoT Intelligence Forest Protection.*
*Firebase bertindak sebagai **database global** sedangkan `forest_database.json` adalah **database lokal**.*
