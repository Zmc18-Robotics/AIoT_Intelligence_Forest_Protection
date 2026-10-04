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
=======================================================================
"""

import os
import sys
import glob
import shutil
import random
import argparse
from pathlib import Path


def sync_data_yaml():
    """
    Membuat / memperbarui data.yaml dengan path absolut workspace saat ini
    untuk mencegah error path salah dari cache Ultralytics settings.json.
    """
    dataset_dir = os.path.abspath("dataset").replace("\\", "/")
    yaml_path = os.path.abspath("dataset/data.yaml")

    yaml_content = f"""# Dataset configuration for YOLOv8 Forest Protection Model
path: {dataset_dir}
train: images/train
val: images/val

# Classes
names:
  0: Pohon yang ditebang
  1: Pohon jatuh alami
  2: Api
"""
    with open(yaml_path, "w") as f:
        f.write(yaml_content)

    print(f"[CONFIG] data.yaml disinkronkan ke path: {dataset_dir}")
    return yaml_path


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


def train(epochs=40, imgsz=640, batch=8, model_type="yolov8n.pt"):
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

    # 2. Sinkronkan data.yaml dengan path absolut saat ini
    yaml_path = sync_data_yaml()

    print("\n" + "=" * 62)
    print(" 🌲 AIoT Forest Protection — Training YOLOv8 Model")
    print("=" * 62)
    print(f"📁 Dataset Config : {yaml_path}")
    print(f"🔄 Epochs         : {epochs}")
    print(f"🖼️ Resolusi (img) : {imgsz}x{imgsz}")
    print(f"📦 Batch Size     : {batch}")
    print(f"🧠 Base Model     : {model_type}")
    print("=" * 62 + "\n")

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
        mosaic=1.0       # Kombinasi 4 gambar acak
    )

    out_weights = os.path.abspath("runs/forest_ai/forest_protection_model/weights/best.pt")
    print("\n" + "=" * 62)
    print(" 🎉 TRAINING SELESAI!")
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
    args = parser.parse_args()

    train(epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, model_type=args.model)
