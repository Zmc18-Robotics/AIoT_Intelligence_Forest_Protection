# 📸 Tutorial Pengambilan Dataset Gambar
## AIoT Intelligence Forest Protection — YOLOv8 Training Dataset

> Tutorial ini mencakup seluruh alur dari **pengambilan foto** di lapangan hingga **dataset siap training** YOLOv8.

---

## Alur Kerja 3 Script

```
[1] capture_dataset.py   → Ambil gambar dari ESP32-CAM → dataset/images/
         ↓
[2] labeling_tool.py     → Labeli bounding box tiap gambar → dataset/labels/
         ↓
[3] train_yolo.py        → Training YOLOv8 → model best.pt siap deploy
```

---

## 📋 Daftar Isi

1. [Kelas Objek yang Dilabeli](#1-kelas-objek-yang-dilabeli)
2. [Persiapan Alat & Software](#2-persiapan-alat--software)
3. [Cara Mengambil Gambar yang Baik](#3-cara-mengambil-gambar-yang-baik)
4. [Metode 1 — Capture via ESP32-CAM (capture_dataset.py)](#4-metode-1--capture-via-esp32-cam-capture_datasetpy)
5. [Metode 2 — Foto Manual dari HP/Kamera](#5-metode-2--foto-manual-dari-hpkamera)
6. [Labeling Bounding Box (labeling_tool.py)](#6-labeling-bounding-box-labeling_toolpy)
7. [Struktur Folder Dataset](#7-struktur-folder-dataset)
8. [Training YOLOv8 (train_yolo.py)](#8-training-yolov8-train_yolopy)
9. [Tips Kualitas Dataset](#9-tips-kualitas-dataset)
10. [Checklist Sebelum Training](#10-checklist-sebelum-training)

---

## 1. Kelas Objek yang Dilabeli

Sistem ini mengenali **3 kelas** objek di dalam hutan:

| ID Kelas | Nama Kelas | Keterangan | Warna Kotak |
|:---:|---|---|:---:|
| `0` | **Pohon yang ditebang** | Illegal logging — ada bekas potongan gergaji, tunggul pohon, atau pohon baru rebah dengan potongan rata | Orange |
| `1` | **Pohon jatuh alami** | Pohon tumbang karena angin, usia tua, atau tanah longsor — potongan tidak rata, akar terangkat | Kuning |
| `2` | **Api** | Kebakaran hutan — nyala api, asap tebal, atau area terbakar yang terlihat | Merah |

> [!IMPORTANT]
> Bedakan **pohon ditebang** vs **jatuh alami** dengan melihat **bagian bawah pohon**:
> - Ditebang: potongan **datar & rata** seperti bekas gergaji
> - Jatuh alami: patahan **tidak rata**, akar bisa terangkat dari tanah

---

## 2. Persiapan Alat & Software

### Hardware
- ESP32-CAM (OV2640, resolusi hingga 1600x1200) atau HP dengan kamera
- Laptop/PC untuk labeling
- Kabel USB-to-TTL (jika menggunakan ESP32-CAM)

### Install Dependensi (sekali saja)
```powershell
cd "C:\Users\Muhammad Zidane A\Documents\PTN\Semester 5\IoT\UTS"
pip install -r requirements.txt
```

---

## 3. Cara Mengambil Gambar yang Baik

### Yang Harus Dilakukan

| Aspek | Panduan |
|---|---|
| **Jumlah gambar** | Minimal **50 gambar per kelas** (ideal 100–200+) |
| **Variasi sudut** | Dari depan, samping, agak atas (sesuai posisi tower) |
| **Variasi cahaya** | Pagi, siang terik, sore, mendung |
| **Variasi jarak** | Dekat (2–5m), sedang (5–15m), jauh (15–30m) |
| **Variasi latar** | Hutan lebat, hutan jarang, tepi sungai |
| **Resolusi** | Minimal **640x480** — lebih baik 1280x720 ke atas |

### Yang Harus Dihindari

- Gambar buram/goyang (motion blur)
- Objek terlalu kecil di frame (kurang dari 20x20 piksel)
- Gambar duplikat persis dari video

### Sudut Kamera Tower

Karena ESP32-CAM dipasang di tower, ambil foto dengan kemiringan ke bawah **15–45 derajat** dan jarak pandang **5–25 meter**.

---

## 4. Metode 1 — Ambil Foto dengan `capture_dataset.py` (Multi-Source)

Script capture mendukung **3 pilihan jalur input**:
1. **Webcam / Kamera USB / DroidCam** (Index 0, 1, 2) — *Paling mudah & cepat!*
2. **USB Serial COM Port** (COM3, COM4, dll)
3. **ESP32-CAM WiFi (TCP/IP Stream Port 80)**

**Cara Menjalankan:**
```powershell
cd "C:\Users\Muhammad Zidane A\Documents\PTN\Semester 5\IoT\UTS"

# Opsi A: Jalankan menu interaktif (akan ditanya pilih 1, 2, atau 3)
python python_backend/capture_dataset.py

# Opsi B: Langsung pakai Webcam Laptop (Index 0)
python python_backend/capture_dataset.py 0

# Opsi C: Langsung pakai Port Serial USB
python python_backend/capture_dataset.py COM3

# Opsi D: Langsung pakai IP ESP32-CAM
python python_backend/capture_dataset.py 192.168.1.102
```

**Kontrol saat Jendela Kamera Terbuka:**

| Tombol | Fungsi |
|:---:|---|
| `SPACE` | Simpan frame saat ini ke `dataset/images/` |
| `A` | Toggle auto-capture (simpan otomatis tiap X detik) |
| `+` / `-` | Naikkan / turunkan interval auto-capture |
| `Q` / `ESC` | Keluar |

**Step 5** — Arahkan kamera ESP32-CAM ke berbagai kondisi:
- Simulasikan pohon tumbang (taruh batang kayu di tanah)
- Nyalakan api kecil yang aman (lilin, korek) untuk kelas Api
- Gunakan potongan kayu gergajian untuk kelas Ditebang

> [!TIP]
> Gunakan **auto-capture interval 2–3 detik** sambil menggerakkan/merotasi objek perlahan untuk mendapat variasi sudut secara otomatis.

---

## 5. Metode 2 — Foto Manual dari HP/Kamera

**Step 1** — Foto objek sesuai panduan di Bagian 3.

**Step 2** — Salin semua foto ke folder:
```
dataset/images/
```
Format yang didukung: `.jpg`, `.jpeg`, `.png`

**Step 3** — Rename file agar teratur (opsional tapi disarankan):
```powershell
$i=1
Get-ChildItem "dataset\images\*.jpg" | Rename-Item -NewName {"forest_{0:D4}.jpg" -f $script:i++}
```

---

## 6. Labeling Bounding Box dengan Labeling Tool

### Jalankan Tool

```powershell
cd "C:\Users\Muhammad Zidane A\Documents\PTN\Semester 5\IoT\UTS"
python python_backend/labeling_tool.py
```

Jendela OpenCV akan terbuka menampilkan gambar pertama dari `dataset/images/`.

### Kontrol Keyboard

| Tombol | Fungsi |
|:---:|---|
| `1` | Pilih kelas: **Pohon yang ditebang** (Orange) |
| `2` | Pilih kelas: **Pohon jatuh alami** (Kuning) |
| `3` | Pilih kelas: **Api** (Merah) |
| `S` | Simpan label gambar saat ini |
| `N` | Simpan & pindah ke gambar **berikutnya** |
| `P` | Simpan & kembali ke gambar **sebelumnya** |
| `U` atau `Z` | Undo / hapus kotak terakhir |
| `C` | Hapus semua kotak di gambar ini |
| `Q` atau `ESC` | Keluar dari tool |

### Cara Menggambar Bounding Box

```
1. Tekan angka kelas (1 / 2 / 3) sesuai objek
2. Klik kiri tahan di pojok kiri-atas objek
3. Seret ke pojok kanan-bawah objek
4. Lepas mouse → kotak otomatis tersimpan di layar
5. Ulangi untuk objek lain di gambar yang sama
6. Tekan [S] untuk simpan, lalu [N] untuk lanjut ke gambar berikutnya
```

### Tips Bounding Box yang Benar

- Kotak harus **membungkus objek dengan rapat** — jangan terlalu longgar
- Jangan sampai ada bagian objek yang terpotong di luar kotak
- Jika ada 2 objek berbeda kelas dalam 1 gambar, gambar 2 kotak terpisah

> [!WARNING]
> Jika objek sangat kecil (< 20x20 px), lebih baik skip gambar itu atau ambil foto lebih dekat. YOLOv8 kesulitan mendeteksi objek sangat kecil.

### Output Label

Setiap gambar menghasilkan file `.txt` di `dataset/labels/` dengan format YOLO:
```
# Format: <class_id> <cx> <cy> <width> <height>
# Semua nilai 0.0–1.0, relatif terhadap ukuran gambar
0 0.512500 0.437500 0.250000 0.312500
2 0.812500 0.687500 0.125000 0.187500
```

---

## 7. Struktur Folder Dataset

Setelah pengambilan & labeling selesai, struktur folder harus seperti ini:

```
dataset/
├── images/
│   ├── forest_0001.jpg
│   ├── forest_0002.jpg
│   └── ...
└── labels/
    ├── forest_0001.txt   ← nama harus sama dengan gambarnya
    ├── forest_0002.txt
    └── ...
```

> [!IMPORTANT]
> Nama file gambar dan label **harus sama persis** (beda hanya ekstensinya):
> `forest_0001.jpg` pasangannya `forest_0001.txt`

---

## 8. Training YOLOv8

Setelah dataset siap (minimal 50 gambar per kelas yang sudah dilabeli):

```powershell
cd "C:\Users\Muhammad Zidane A\Documents\PTN\Semester 5\IoT\UTS"
python python_backend/train_yolo.py
```

Script otomatis akan:
1. Split dataset: 80% train / 20% validasi
2. Buat `dataset.yaml` konfigurasi YOLOv8
3. Mulai training dengan model `yolov8n.pt` (nano, ringan untuk ESP32)
4. Simpan model hasil di `runs/detect/forest_protection/weights/best.pt`

### Indikator Keberhasilan Training

| Nilai mAP50 | Keterangan |
|:---:|---|
| < 0.50 | Kurang — tambah data atau perbaiki labeling |
| 0.50 – 0.70 | Cukup — bisa dipakai untuk testing awal |
| 0.70 – 0.85 | Baik — siap untuk pengujian lapangan |
| > 0.85 | Sangat baik — siap deploy |

---

## 9. Testing Model Realtime Menggunakan Kamera (`test_model.py`)

Setelah training selesai dan menghasilkan model `best.pt`, arahkan kamera ke objek (atau letakkan datasheet/foto di depan kamera) untuk menguji deteksi secara realtime:

```powershell
cd "C:\Users\Muhammad Zidane A\Documents\PTN\Semester 5\IoT\UTS"

# Cara 1: Menu Interaktif (Pilih 1 untuk Webcam, 2 untuk Serial COM, 3 untuk ESP32-CAM)
python python_backend/test_model.py

# Cara 2: Langsung Pakai Webcam Laptop (Index 0)
python python_backend/test_model.py 0

# Cara 3: Langsung Pakai ESP32-CAM WiFi
python python_backend/test_model.py 192.168.4.2
```

### Yang Ditampilkan Saat Kamera Mendeteksi Objek:
1. **Kotak Bounding Box Berwarna**:
   - 🟠 **Orange** : `[1] Pohon yang ditebang`
   - 🟡 **Kuning** : `[2] Pohon jatuh alami`
   - 🔴 **Merah**  : `[3] Api`
2. **Badge Label & Persentase Tingkat Keberhasilan**:
   - Di atas kotak langsung muncul keterangan kelas & skor keyakinannya (contoh: `[1] Pohon yang ditebang : 96.4%` atau `[3] Api : 98.7%`).
3. **Statistik Live di Header**: Menampilkan status jumlah objek terdeteksi, FPS realtime, waktu inferensi (ms), dan ambang batas confidence.

### Kontrol Keyboard Saat Menguji:
- **`+` / `-`** : Naikkan / turunkan ambang batas (*Confidence Threshold*)
- **`S`** : Simpan screenshot foto hasil deteksi ke folder `dataset/test_results/`
- **`F`** : Toggle Senter / Flash ESP32-CAM
- **`Q` / `ESC`** : Selesai dan keluar

---

## 10. Tips Kualitas Dataset

### Distribusi Kelas yang Seimbang

```
IDEAL:
  Pohon ditebang  : 120 gambar
  Pohon jatuh     : 110 gambar
  Api             : 100 gambar

HINDARI (terlalu timpang):
  Pohon ditebang  : 200 gambar
  Pohon jatuh     :  30 gambar
  Api             :  10 gambar
```

Model akan "malas" mendeteksi kelas yang sedikit. Usahakan rasio maks **3:1**.

### Sumber Gambar Tambahan (jika kurang)

Jika sulit mendapat gambar lapangan yang cukup, tambahkan dari:
- Google Images (cari: "illegal logging", "forest fire indonesia", "pohon tumbang")
- Dataset publik di [Roboflow Universe](https://universe.roboflow.com/) — cari "forest fire" atau "deforestation"
- Screenshot dari video drone hutan di YouTube

> [!NOTE]
> Gambar dari internet tetap harus dilabeli ulang dengan `labeling_tool.py`.

---

## 11. Checklist Sebelum Training

Centang semua poin ini sebelum menjalankan `train_yolo.py`:

- [ ] Minimal **50 foto per kelas** tersimpan di `dataset/images/`
- [ ] Setiap foto memiliki file label `.txt` pasangan di `dataset/labels/`
- [ ] Tidak ada foto yang tidak punya label sama sekali
- [ ] Nama file gambar dan label sudah **matching** (cek beberapa sample)
- [ ] Semua foto minimal resolusi **640x480**
- [ ] Distribusi kelas tidak terlalu timpang (rasio maks 3:1)

```powershell
# Cek jumlah gambar dan label — harus sama:
(Get-ChildItem "dataset\images" -File).Count
(Get-ChildItem "dataset\labels" -File).Count
```

---

*Tutorial ini bagian dari proyek AIoT Intelligence Forest Protection — Semester 5 IoT*
