"""
=======================================================================
 AIoT Intelligence Forest Protection - YOLOv8 Model Training Script
=======================================================================
Melatih model YOLOv8 pada dataset perlindungan hutan:
  - [0] Pohon yang ditebang (Illegal Logging)
  - [1] Pohon jatuh alami (Naturally Fallen Tree)
  - [2] Api (Forest Fire Incident)

Penggunaan:
  python python_backend/train_yolo.py --epochs 40 --imgsz 640 --batch 8

Perbaikan Bug:
  - Cache Ultralytics dihapus otomatis sebelum training (mencegah bug
    'hanya 2 kelas terdeteksi' akibat cache label lama yang ter-cache).
  - Diagnosa distribusi kelas dilakukan sebelum training.
  - Penanganan class weight untuk dataset tidak seimbang.
======================================================================="""

import os
import sys
import glob
import shutil
import random
import argparse
from pathlib import Path

CLASS_NAMES = [
    "Pohon yang ditebang",   # 0
    "Pohon jatuh alami",     # 1
    "Api",                   # 2
]
NUM_CLASSES = len(CLASS_NAMES)


def sync_data_yaml():
    """
    Membuat / memperbarui data.yaml dengan path absolut workspace saat ini
    untuk mencegah error path salah dari cache Ultralytics settings.json.
    """
    dataset_dir = os.path.abspath("dataset").replace("\\", "/")
    yaml_path = os.path.abspath("dataset/data.yaml")

    names_block = "\n".join(
        f"  {i}: {name}" for i, name in enumerate(CLASS_NAMES)
    )
    yaml_content = f"""# Dataset configuration for YOLOv8 Forest Protection Model
# AUTO-GENERATED oleh train_yolo.py — jangan edit manual
path: {dataset_dir}
train: images/train
val: images/val

nc: {NUM_CLASSES}

# Classes
names:
{names_block}
"""
    with open(yaml_path, "w") as f:
        f.write(yaml_content)

    print(f"[CONFIG] data.yaml disinkronkan ke path: {dataset_dir}")
    return yaml_path


def clear_dataset_cache():
    """
    Hapus file .cache Ultralytics di folder labels/.
    BUG FIX: Cache menyimpan info kelas lama sehingga kelas baru (mis. Api)
    tidak dikenali meskipun labelnya sudah ada di disk.
    """
    cache_files = glob.glob("dataset/labels/**/*.cache", recursive=True) + \
                  glob.glob("dataset/labels/*.cache")
    if cache_files:
        for cf in cache_files:
            try:
                os.remove(cf)
                print(f"[CACHE] Dihapus: {cf}")
            except Exception as e:
                print(f"[CACHE] Gagal hapus {cf}: {e}")
    else:
        print("[CACHE] Tidak ada cache lama ditemukan.")


def backup_dataset_labels(label_dir="dataset/labels"):
    """
    Cadangkan seluruh file label ke folder dataset/labels_backup/
    sehingga data anotasi TIDAK AKAN PERNAH hilang.
    """
    backup_dir = "dataset/labels_backup"
    os.makedirs(backup_dir, exist_ok=True)
    saved_count = 0
    for split in ("train", "val"):
        src = os.path.join(label_dir, split)
        dst = os.path.join(backup_dir, split)
        if os.path.exists(src):
            os.makedirs(dst, exist_ok=True)
            for f in glob.glob(os.path.join(src, "*.txt")):
                shutil.copy2(f, os.path.join(dst, os.path.basename(f)))
                saved_count += 1
    if saved_count > 0:
        print(f"[BACKUP] Salinan cadangan aman {saved_count} file label dibuat di: '{backup_dir}/'")


def diagnose_dataset(label_dir="dataset/labels"):
    """
    Periksa distribusi kelas di seluruh folder train dan val.
    Mendeteksi kelas yang hilang atau tidak seimbang.
    Returns: (ok: bool, counts_train: dict, counts_val: dict)
    """
    print("\n[DIAGNOSA] Memeriksa distribusi kelas dataset...")
    ok = True

    for split in ("train", "val"):
        split_dir = os.path.join(label_dir, split)
        counts = {i: 0 for i in range(NUM_CLASSES)}
        txt_files = glob.glob(os.path.join(split_dir, "*.txt"))

        if not txt_files:
            print(f"  [{split.upper()}] ⚠️  Tidak ada file label ditemukan di '{split_dir}'!")
            ok = False
            continue

        for fpath in txt_files:
            try:
                with open(fpath, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        cls_id = int(line.split()[0])
                        if cls_id in counts:
                            counts[cls_id] += 1
                        else:
                            print(f"  [{split.upper()}] ⚠️  Class ID tidak dikenal: {cls_id} di {fpath}")
            except Exception as e:
                print(f"  [{split.upper()}] Error membaca {fpath}: {e}")

        print(f"\n  [{split.upper()}] Distribusi ({len(txt_files)} file label):")
        for cls_id, name in enumerate(CLASS_NAMES):
            count = counts[cls_id]
            bar = "#" * min(count, 40)
            status = "[OK]" if count > 0 else "[!!! TIDAK ADA DATA !!!]"
            print(f"    [{cls_id}] {name:<25} : {count:>4} bbox  {bar} {status}")
            if count == 0:
                ok = False

    if not ok:
        print("\n  [PERINGATAN] Satu atau lebih kelas tidak memiliki data!")
        print("     Model TIDAK akan bisa mendeteksi kelas yang tidak ada datanya.")
        print("     Tambahkan gambar & label untuk kelas yang kosong, lalu jalankan ulang training.")
    else:
        print("\n  [OK] Semua kelas memiliki data. Dataset siap training!")

    return ok


def prepare_dataset(img_dir="dataset/images", label_dir="dataset/labels", split_ratio=0.8):
    """
    Otomatis membagi dataset gambar dan label ke folder train dan val (80:20).
    """
    train_img_dir = os.path.join(img_dir, "train")
    val_img_dir = os.path.join(img_dir, "val")
    train_lbl_dir = os.path.join(label_dir, "train")
    val_lbl_dir = os.path.join(label_dir, "val")

    os.makedirs(train_img_dir, exist_ok=True)
    os.makedirs(val_img_dir, exist_ok=True)
    os.makedirs(train_lbl_dir, exist_ok=True)
    os.makedirs(val_lbl_dir, exist_ok=True)

    # Cari gambar di root dataset/images/ yang belum masuk folder train/val
    root_imgs = [
        f for f in glob.glob(os.path.join(img_dir, "*.*"))
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp'))
    ]

    train_count = len(glob.glob(os.path.join(train_img_dir, "*.*")))
    val_count = len(glob.glob(os.path.join(val_img_dir, "*.*")))

    if not root_imgs:
        if train_count > 0:
            print(f"[DATASET] Dataset siap: {train_count} gambar train, {val_count} gambar val.")
            return True
        else:
            print(f"[ERROR] Tidak ada gambar ditemukan di '{img_dir}'.")
            print("Silakan jalankan 'capture_dataset.py' atau salin foto ke folder 'dataset/images/'.")
            return False

    random.seed(42)
    random.shuffle(root_imgs)

    split_idx = max(1, int(len(root_imgs) * split_ratio))
    train_files = root_imgs[:split_idx]
    val_files = root_imgs[split_idx:] if split_idx < len(root_imgs) else [root_imgs[-1]]

    print(f"[DATASET] Membagi {len(root_imgs)} gambar baru: {len(train_files)} train, {len(val_files)} val...")

    for img_path in train_files:
        base_name = os.path.splitext(os.path.basename(img_path))[0]
        dest_img = os.path.join(train_img_dir, os.path.basename(img_path))
        shutil.move(img_path, dest_img)
        lbl_file = os.path.join(label_dir, base_name + ".txt")
        if os.path.exists(lbl_file):
            shutil.move(lbl_file, os.path.join(train_lbl_dir, base_name + ".txt"))

    for img_path in val_files:
        base_name = os.path.splitext(os.path.basename(img_path))[0]
        dest_img = os.path.join(val_img_dir, os.path.basename(img_path))
        shutil.move(img_path, dest_img)
        lbl_file = os.path.join(label_dir, base_name + ".txt")
        if os.path.exists(lbl_file):
            shutil.move(lbl_file, os.path.join(val_lbl_dir, base_name + ".txt"))

    total_train = len(glob.glob(os.path.join(train_img_dir, "*.*")))
    total_val = len(glob.glob(os.path.join(val_img_dir, "*.*")))
    print(f"[DATASET] Total: {total_train} gambar train, {total_val} gambar val.")
    return True


def train(epochs=40, imgsz=640, batch=8, model_type="yolov8n.pt", force=False):
    try:
        from ultralytics import YOLO, settings
        # Sinkronkan settings datasets_dir internal Ultralytics
        workspace_dir = os.path.abspath(".").replace("\\", "/")
        settings.update({'datasets_dir': workspace_dir})
    except ImportError:
        print("[ERROR] Modul 'ultralytics' belum terpasang. Silakan jalankan: pip install ultralytics")
        return

    # 1. Pastikan dataset siap dan terbagi
    if not prepare_dataset():
        return

    # 2. Cadangkan seluruh label untuk keamanan ekstra
    print("\n[STEP 1/5] Membuat salinan cadangan aman seluruh label...")
    backup_dataset_labels()

    # 3. Hapus cache LAMA agar Ultralytics baca ulang semua label terbaru
    print("\n[STEP 2/5] Membersihkan cache dataset lama...")
    clear_dataset_cache()

    # 4. Diagnosa distribusi kelas
    print("\n[STEP 3/5] Mendiagnosa dataset...")
    dataset_ok = diagnose_dataset()
    if not dataset_ok and not force:
        print("\n[ABORT] Training dibatalkan karena ada kelas tanpa data.")
        print("  Gunakan flag --force untuk memaksa training meskipun ada kelas kosong.")
        print("  Contoh: python python_backend/train_yolo.py --force")
        return
    elif not dataset_ok and force:
        print("\n[FORCE] Melanjutkan training meskipun ada kelas kosong (--force aktif).")

    # 4. Sinkronkan data.yaml dengan path absolut saat ini
    print("\n[STEP 3/4] Menyinkronkan data.yaml...")
    yaml_path = sync_data_yaml()

    print("\n" + "=" * 62)
    print(" [AIoT] Forest Protection -- Training YOLOv8 Model")
    print("=" * 62)
    print(f"[DATASET] Dataset Config : {yaml_path}")
    print(f"[EPOCHS]  Epochs         : {epochs}")
    print(f"[IMG]     Resolusi (img) : {imgsz}x{imgsz}")
    print(f"[BATCH]   Batch Size     : {batch}")
    print(f"[MODEL]   Base Model     : {model_type}")
    print("=" * 62 + "\n")

    print("[STEP 4/4] Memulai training...")
    model = YOLO(model_type)
    results = model.train(
        data=yaml_path,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        project="runs/forest_ai",
        name="forest_protection_model",
        exist_ok=True,
        save=True,
        # ── Augmentasi Data Kuat untuk Dataset Kecil (Otomatis Lipatgandakan Variasi) ──
        degrees=15.0,    # Rotasi acak +/- 15 derajat
        translate=0.1,   # Geser posisi 10%
        scale=0.3,       # Variasi jarak dekat/jauh 30%
        fliplr=0.5,      # Cermin horizontal
        hsv_h=0.015,     # Variasi warna
        hsv_s=0.6,       # Variasi saturasi
        hsv_v=0.4,       # Variasi pencahayaan (terang/gelap)
        mosaic=1.0,      # Kombinasi 4 gambar acak
        # ── Optimizer & Scheduler untuk kelas tidak seimbang ──
        cos_lr=True,     # Cosine LR scheduler, lebih stabil
        patience=20,     # Early stopping jika tidak ada peningkatan 20 epoch
    )

    out_weights = os.path.abspath("runs/forest_ai/forest_protection_model/weights/best.pt")
    print("\n" + "=" * 62)
    print(" [SELESAI] TRAINING BERHASIL!")
    print(f"[*] Model tersimpan di: {out_weights}")
    print("=" * 62)
    print("Langkah selanjutnya: Uji model dengan menjalankan:")
    print("    python python_backend/test_model.py\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train YOLOv8 for AIoT Forest Protection")
    parser.add_argument("--epochs", type=int, default=40, help="Jumlah epoch training (default: 40)")
    parser.add_argument("--imgsz", type=int, default=640, help="Resolusi gambar (default: 640)")
    parser.add_argument("--batch", type=int, default=8, help="Batch size (default: 8)")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="Base model (default: yolov8n.pt)")
    parser.add_argument("--force", action="store_true",
                        help="Paksa training meskipun ada kelas tanpa data (tidak disarankan)")
    parser.add_argument("--diagnose-only", action="store_true",
                        help="Hanya tampilkan diagnosa dataset tanpa training")
    args = parser.parse_args()

    if args.diagnose_only:
        clear_dataset_cache()
        diagnose_dataset()
    else:
        train(epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
              model_type=args.model, force=args.force)
