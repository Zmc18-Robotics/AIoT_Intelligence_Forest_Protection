"""
=======================================================================
 AIoT Intelligence Forest Protection - Interactive Dataset Labeling Tool
=======================================================================
Tool untuk menggambar bounding box (anotasi YOLO) pada gambar dataset:
  [1] Pohon yang ditebang (Cut/Felled Tree - Illegal Logging)
  [2] Pohon jatuh alami (Naturally Fallen Tree)
  [3] Api (Fire Incident)

Fitur Baru:
  - Tampilan BESAR & Nyaman (1100x750 px, Resizable)
  - Dukungan Keyboard Lengkap (Bisa huruf kecil, huruf besar/Caps Lock, Space, Enter)
  - Tombol Navigasi & Kelas bisa DIKLIK MENGGUNAKAN MOUSE!
  - Notifikasi Toast visual langsung di layar saat simpan / undo / ganti foto
  - Format YOLO (.txt) otomatis disimpan di dataset/labels/

Kontrol Keyboard / Mouse:
  - [1] / [2] / [3]       : Pilih Kelas
  - [S] / [ENTER] / [SPACE]: Simpan Anotasi Foto Saat Ini
  - [N] / [D] / [Tombol >] : Simpan & Lanjut ke Foto BERIKUTNYA
  - [P] / [A] / [Tombol <] : Simpan & Kembali ke Foto SEBELUMNYA
  - [U] / [Z] / [BACKSPACE]: Undo (Hapus kotak terakhir)
  - [C] / [DELETE]        : Clear (Hapus semua kotak di foto ini)
  - [Q] / [ESC]           : Selesai & Keluar
=======================================================================
"""

import os
import glob
import time
import cv2
import numpy as np

CLASSES = [
    "Pohon yang ditebang",
    "Pohon jatuh alami",
    "Api"
]

CLASS_COLORS = [
    (0, 140, 255),  # Orange untuk Pohon Ditebang
    (0, 230, 255),  # Kuning untuk Pohon Jatuh Alami
    (30, 30, 255)   # Merah untuk Api
]

CANVAS_W = 1100
CANVAS_H = 750
TOP_BAR_H = 70
BOTTOM_BAR_H = 50


class ForestLabelingTool:
    def __init__(self, img_dir="dataset/images", label_dir="dataset/labels"):
        self.img_dir = img_dir
        self.label_dir = label_dir
        os.makedirs(self.img_dir, exist_ok=True)
        os.makedirs(self.label_dir, exist_ok=True)

        self.image_files = sorted(
            glob.glob(os.path.join(self.img_dir, "*.jpg")) +
            glob.glob(os.path.join(self.img_dir, "*.jpeg")) +
            glob.glob(os.path.join(self.img_dir, "*.png")) +
            glob.glob(os.path.join(self.img_dir, "*.bmp")) +
            glob.glob(os.path.join(self.img_dir, "*.webp"))
        )
        self.current_idx = 0
        self.current_class = 0

        # Koordinat gambar asli (original image pixels)
        self.drawing = False
        self.ix_orig, self.iy_orig = -1, -1
        self.current_rect_orig = None
        self.boxes = []  # list of dict: {"cls": int, "bbox": (x1, y1, x2, y2)}

        # Variabel scaling display
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = TOP_BAR_H
        self.cur_img_w = 640
        self.cur_img_h = 480

        # Toast notification system
        self.toast_msg = ""
        self.toast_color = (0, 255, 100)
        self.toast_time = 0

        # Clickable button bounding boxes (x1, y1, x2, y2, action_name, param)
        self.ui_buttons = []

        self.window_name = "AIoT Forest Protection — YOLO Labeling Tool"

    def show_toast(self, msg, color=(0, 255, 120)):
        self.toast_msg = msg
        self.toast_color = color
        self.toast_time = time.time()

    def screen_to_orig(self, sx, sy):
        """Konversi koordinat layar display ke koordinat gambar asli."""
        ox = int((sx - self.offset_x) / self.scale)
        oy = int((sy - self.offset_y) / self.scale)
        ox = max(0, min(self.cur_img_w, ox))
        oy = max(0, min(self.cur_img_h, oy))
        return ox, oy

    def orig_to_screen(self, ox, oy):
        """Konversi koordinat gambar asli ke koordinat layar display."""
        sx = int(ox * self.scale + self.offset_x)
        sy = int(oy * self.scale + self.offset_y)
        return sx, sy

    def is_inside_image(self, sx, sy):
        img_disp_w = int(self.cur_img_w * self.scale)
        img_disp_h = int(self.cur_img_h * self.scale)
        return (self.offset_x <= sx <= self.offset_x + img_disp_w and
                self.offset_y <= sy <= self.offset_y + img_disp_h)

    def mouse_callback(self, event, x, y, flags, param):
        # 1. Cek Klik Tombol UI
        if event == cv2.EVENT_LBUTTONDOWN:
            for bx1, by1, bx2, by2, action, val in self.ui_buttons:
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    self.handle_button_action(action, val)
                    return

        # 2. Gambar Bounding Box di Area Gambar
        ox, oy = self.screen_to_orig(x, y)

        if event == cv2.EVENT_LBUTTONDOWN:
            if self.is_inside_image(x, y):
                self.drawing = True
                self.ix_orig, self.iy_orig = ox, oy
                self.current_rect_orig = (ox, oy, ox, oy)

        elif event == cv2.EVENT_MOUSEMOVE:
            if self.drawing:
                self.current_rect_orig = (self.ix_orig, self.iy_orig, ox, oy)

        elif event == cv2.EVENT_LBUTTONUP:
            if self.drawing:
                self.drawing = False
                x1 = min(self.ix_orig, ox)
                y1 = min(self.iy_orig, oy)
                x2 = max(self.ix_orig, ox)
                y2 = max(self.iy_orig, oy)

                # Filter klik terlalu kecil (minimal 6x6 pixel pada gambar asli)
                if (x2 - x1) >= 6 and (y2 - y1) >= 6:
                    self.boxes.append({
                        "cls": self.current_class,
                        "bbox": (x1, y1, x2, y2)
                    })
                    cls_name = CLASSES[self.current_class]
                    self.show_toast(f"+ Kotak Ditambahkan: {cls_name} (Total: {len(self.boxes)})",
                                    CLASS_COLORS[self.current_class])
                self.current_rect_orig = None

    def handle_button_action(self, action, val):
        if action == "SET_CLASS":
            self.current_class = val
            self.show_toast(f"Kelas Aktif: [{val + 1}] {CLASSES[val]}", CLASS_COLORS[val])
        elif action == "SAVE":
            self.save_labels()
        elif action == "NEXT":
            self.save_labels()
            self.next_image()
        elif action == "PREV":
            self.save_labels()
            self.prev_image()
        elif action == "UNDO":
            self.undo_box()
        elif action == "CLEAR":
            self.clear_boxes()
        elif action == "QUIT":
            self.save_labels()
            cv2.destroyAllWindows()
            exit(0)

    def next_image(self):
        if self.image_files:
            self.current_idx = (self.current_idx + 1) % len(self.image_files)
            self.load_existing_labels()
            self.show_toast(f"Foto [{self.current_idx + 1}/{len(self.image_files)}]", (200, 220, 255))

    def prev_image(self):
        if self.image_files:
            self.current_idx = (self.current_idx - 1) % len(self.image_files)
            self.load_existing_labels()
            self.show_toast(f"Foto [{self.current_idx + 1}/{len(self.image_files)}]", (200, 220, 255))

    def undo_box(self):
        if self.boxes:
            removed = self.boxes.pop()
            cls_name = CLASSES[removed["cls"]]
            self.show_toast(f"Undo: Menghapus kotak {cls_name} (Sisa {len(self.boxes)})", (0, 200, 255))
        else:
            self.show_toast("Tidak ada kotak untuk di-undo", (150, 150, 150))

    def clear_boxes(self):
        if self.boxes:
            count = len(self.boxes)
            self.boxes = []
            self.show_toast(f"Semua {count} kotak dihapus!", (80, 80, 255))

    def load_existing_labels(self):
        self.boxes = []
        if not self.image_files:
            return
        img_path = self.image_files[self.current_idx]
        base_name = os.path.splitext(os.path.basename(img_path))[0]
        label_path = os.path.join(self.label_dir, base_name + ".txt")

        if os.path.exists(label_path):
            with open(label_path, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        cls_id = int(parts[0])
                        cx = float(parts[1]) * self.cur_img_w
                        cy = float(parts[2]) * self.cur_img_h
                        w = float(parts[3]) * self.cur_img_w
                        h = float(parts[4]) * self.cur_img_h
                        x1 = int(cx - w / 2)
                        y1 = int(cy - h / 2)
                        x2 = int(cx + w / 2)
                        y2 = int(cy + h / 2)
                        self.boxes.append({
                            "cls": cls_id,
                            "bbox": (x1, y1, x2, y2)
                        })

    def save_labels(self):
        if not self.image_files:
            return
        img_path = self.image_files[self.current_idx]
        base_name = os.path.splitext(os.path.basename(img_path))[0]
        label_path = os.path.join(self.label_dir, base_name + ".txt")

        # Jika tidak ada kotak, hapus file label lama (jika ada) atau buat file kosong
        if not self.boxes:
            if os.path.exists(label_path):
                os.remove(label_path)
            self.show_toast(f"File label dikosongkan: {base_name}.txt", (200, 200, 200))
            print(f"  [SAVED] Label dikosongkan: {label_path}")
            return

        with open(label_path, "w") as f:
            for item in self.boxes:
                cls_id = item["cls"]
                x1, y1, x2, y2 = item["bbox"]

                # Clip ke batas gambar
                x1 = max(0, min(x1, self.cur_img_w))
                x2 = max(0, min(x2, self.cur_img_w))
                y1 = max(0, min(y1, self.cur_img_h))
                y2 = max(0, min(y2, self.cur_img_h))

                w = (x2 - x1) / self.cur_img_w
                h = (y2 - y1) / self.cur_img_h
                cx = (x1 + (x2 - x1) / 2.0) / self.cur_img_w
                cy = (y1 + (y2 - y1) / 2.0) / self.cur_img_h

                if w > 0 and h > 0:
                    f.write(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")

        self.show_toast(f"BERHASIL DISIMPAN! ({len(self.boxes)} Kotak)", (0, 255, 100))
        print(f"  [SAVED] {len(self.boxes)} label disimpan ke: {label_path}")

    def run(self):
        if not self.image_files:
            print("=" * 60)
            print(f"[INFO] Folder '{self.img_dir}' masih kosong.")
            print("Silakan jalankan 'capture_dataset.py' terlebih dahulu untuk mengambil foto,")
            print(f"atau salin file foto ke folder '{self.img_dir}'.")
            print("=" * 60)
            return

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, CANVAS_W, CANVAS_H)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)

        first_load = True

        while True:
            img_path = self.image_files[self.current_idx]
            orig_img = cv2.imread(img_path)
            if orig_img is None:
                print(f"[ERROR] Gagal membaca gambar: {img_path}")
                break

            self.cur_img_h, self.cur_img_w = orig_img.shape[:2]

            if first_load:
                self.load_existing_labels()
                first_load = False

            # Reset daftar tombol klik per frame
            self.ui_buttons = []

            # ── Buat Canvas Display ──
            canvas = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
            canvas[:] = (24, 24, 24)

            # Hitung scaling gambar agar muat besar & proporsional
            avail_w = CANVAS_W - 30
            avail_h = CANVAS_H - TOP_BAR_H - BOTTOM_BAR_H - 20

            self.scale = min(avail_w / self.cur_img_w, avail_h / self.cur_img_h)
            disp_w = int(self.cur_img_w * self.scale)
            disp_h = int(self.cur_img_h * self.scale)

            self.offset_x = (CANVAS_W - disp_w) // 2
            self.offset_y = TOP_BAR_H + (avail_h - disp_h) // 2 + 5

            # Resize gambar asli ke ukuran display
            resized_img = cv2.resize(orig_img, (disp_w, disp_h), interpolation=cv2.INTER_LINEAR)
            canvas[self.offset_y : self.offset_y + disp_h, self.offset_x : self.offset_x + disp_w] = resized_img

            # Garis border halus di sekeliling gambar
            cv2.rectangle(canvas, (self.offset_x - 1, self.offset_y - 1),
                          (self.offset_x + disp_w, self.offset_y + disp_h), (60, 60, 60), 1)

            # ── Gambar Kotak Anotasi Tersimpan ──
            for item in self.boxes:
                cls_id = item["cls"]
                ox1, oy1, ox2, oy2 = item["bbox"]
                sx1, sy1 = self.orig_to_screen(ox1, oy1)
                sx2, sy2 = self.orig_to_screen(ox2, oy2)

                color = CLASS_COLORS[cls_id % len(CLASS_COLORS)]
                label = f"[{cls_id + 1}] {CLASSES[cls_id % len(CLASSES)]}"

                cv2.rectangle(canvas, (sx1, sy1), (sx2, sy2), color, 2)

                # Badge label
                text_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.44, 1)
                badge_w = text_size[0] + 10
                badge_h = 20
                badge_y = max(self.offset_y, sy1 - badge_h)

                cv2.rectangle(canvas, (sx1, badge_y), (sx1 + badge_w, badge_y + badge_h), color, -1)
                cv2.putText(canvas, label, (sx1 + 5, badge_y + 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.44, (15, 15, 15), 1, cv2.LINE_AA)

            # ── Gambar Kotak Drag yang Sedang Ditarik ──
            if self.current_rect_orig:
                ox1, oy1, ox2, oy2 = self.current_rect_orig
                sx1, sy1 = self.orig_to_screen(min(ox1, ox2), min(oy1, oy2))
                sx2, sy2 = self.orig_to_screen(max(ox1, ox2), max(oy1, oy2))
                active_col = CLASS_COLORS[self.current_class]
                cv2.rectangle(canvas, (sx1, sy1), (sx2, sy2), active_col, 2)

            # ══════════════════════════════════════════════════════════════
            # HEADER ATAS (HUD & TOMBOL KELAS KLIK)
            # ══════════════════════════════════════════════════════════════
            cv2.rectangle(canvas, (0, 0), (CANVAS_W, TOP_BAR_H), (15, 15, 15), -1)
            cv2.line(canvas, (0, TOP_BAR_H), (CANVAS_W, TOP_BAR_H), (45, 45, 45), 1)

            img_name = os.path.basename(img_path)
            cv2.putText(canvas, f"Foto: {img_name}", (15, 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(canvas, f"Index: [{self.current_idx + 1}/{len(self.image_files)}]  |  Resolusi: {self.cur_img_w}x{self.cur_img_h}  |  Kotak: {len(self.boxes)}",
                        (15, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180, 180, 180), 1, cv2.LINE_AA)

            # Tombol Kelas di kanan header (Bisa diklik mouse atau ditekan 1/2/3)
            cls_buttons = [
                ("[1] Ditebang", 0),
                ("[2] Jatuh Alami", 1),
                ("[3] Api", 2)
            ]
            bx = CANVAS_W - 510
            cv2.putText(canvas, "PILIH KELAS:", (bx - 90, 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (170, 170, 170), 1, cv2.LINE_AA)

            for title, cid in cls_buttons:
                is_selected = (self.current_class == cid)
                btn_color = CLASS_COLORS[cid] if is_selected else (35, 35, 35)
                text_col = (10, 10, 10) if is_selected else (200, 200, 200)
                thick = 2 if is_selected else 1

                t_size, _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, 0.46, 1)
                bw = t_size[0] + 16
                bh = 36

                # Gambar tombol
                if is_selected:
                    cv2.rectangle(canvas, (bx, 18), (bx + bw, 18 + bh), btn_color, -1)
                else:
                    cv2.rectangle(canvas, (bx, 18), (bx + bw, 18 + bh), (60, 60, 60), 1)

                cv2.putText(canvas, title, (bx + 8, 42),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.46, text_col, thick, cv2.LINE_AA)

                # Daftarkan area klik tombol
                self.ui_buttons.append((bx, 18, bx + bw, 18 + bh, "SET_CLASS", cid))
                bx += bw + 8

            # ══════════════════════════════════════════════════════════════
            # FOOTER BAWAH (TOMBOL AKSI KLIK & SHORTCUT)
            # ══════════════════════════════════════════════════════════════
            foot_y = CANVAS_H - BOTTOM_BAR_H
            cv2.rectangle(canvas, (0, foot_y), (CANVAS_W, CANVAS_H), (15, 15, 15), -1)
            cv2.line(canvas, (0, foot_y), (CANVAS_W, foot_y), (45, 45, 45), 1)

            # Tombol aksi klik di footer
            action_buttons = [
                ("< [P] Prev", "PREV", (45, 45, 45), (200, 200, 200)),
                ("[S/Space] SIMPAN", "SAVE", (0, 130, 60), (255, 255, 255)),
                ("[N] Next >", "NEXT", (45, 45, 45), (200, 200, 200)),
                ("[U] Undo", "UNDO", (40, 40, 40), (220, 220, 100)),
                ("[C] Clear", "CLEAR", (40, 40, 40), (100, 100, 240)),
                ("[Q] Keluar", "QUIT", (40, 40, 40), (180, 180, 180)),
            ]

            abx = 15
            for btn_text, act_name, bg_col, txt_col in action_buttons:
                t_size, _ = cv2.getTextSize(btn_text, cv2.FONT_HERSHEY_SIMPLEX, 0.44, 1)
                bw = t_size[0] + 16
                bh = 32
                by = foot_y + 9

                cv2.rectangle(canvas, (abx, by), (abx + bw, by + bh), bg_col, -1)
                cv2.rectangle(canvas, (abx, by), (abx + bw, by + bh), (70, 70, 70), 1)
                cv2.putText(canvas, btn_text, (abx + 8, by + 21),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.44, txt_col, 1, cv2.LINE_AA)

                self.ui_buttons.append((abx, by, abx + bw, by + bh, act_name, None))
                abx += bw + 10

            # ── NOTIFIKASI TOAST (POPUP) ──
            if self.toast_msg and (time.time() - self.toast_time) < 2.2:
                t_size, _ = cv2.getTextSize(self.toast_msg, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
                tw = t_size[0] + 28
                th = 32
                tx = (CANVAS_W - tw) // 2
                ty = TOP_BAR_H + 12

                cv2.rectangle(canvas, (tx, ty), (tx + tw, ty + th), (20, 20, 20), -1)
                cv2.rectangle(canvas, (tx, ty), (tx + tw, ty + th), self.toast_color, 2)
                cv2.putText(canvas, self.toast_msg, (tx + 14, ty + 21),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.52, self.toast_color, 1, cv2.LINE_AA)

            cv2.imshow(self.window_name, canvas)

            # ══════════════════════════════════════════════════════════════
            # KEYBOARD EVENT HANDLING (Mendukung Huruf Besar, Kecil, Enter, Space)
            # ══════════════════════════════════════════════════════════════
            raw_key = cv2.waitKey(20)
            if raw_key != -1:
                key = raw_key & 0xFF

                # Ganti Kelas: 1, 2, 3
                if key == ord('1'):
                    self.current_class = 0
                    self.show_toast("Kelas Aktif: [1] Pohon yang ditebang", CLASS_COLORS[0])
                elif key == ord('2'):
                    self.current_class = 1
                    self.show_toast("Kelas Aktif: [2] Pohon jatuh alami", CLASS_COLORS[1])
                elif key == ord('3'):
                    self.current_class = 2
                    self.show_toast("Kelas Aktif: [3] Api", CLASS_COLORS[2])

                # Simpan (Save): 's', 'S', Enter (13/10), Space (32)
                elif key in (ord('s'), ord('S'), 13, 32, 10):
                    self.save_labels()

                # Next: 'n', 'N', 'd', 'D'
                elif key in (ord('n'), ord('N'), ord('d'), ord('D')):
                    self.save_labels()
                    self.next_image()

                # Prev: 'p', 'P', 'a', 'A'
                elif key in (ord('p'), ord('P'), ord('a'), ord('A')):
                    self.save_labels()
                    self.prev_image()

                # Undo: 'u', 'U', 'z', 'Z', Backspace (8)
                elif key in (ord('u'), ord('U'), ord('z'), ord('Z'), 8):
                    self.undo_box()

                # Clear: 'c', 'C', Delete (127, 255)
                elif key in (ord('c'), ord('C'), 127, 255):
                    self.clear_boxes()

                # Keluar: 'q', 'Q', ESC (27)
                elif key in (ord('q'), ord('Q'), 27):
                    self.save_labels()
                    break

        cv2.destroyAllWindows()


if __name__ == "__main__":
    tool = ForestLabelingTool()
    tool.run()
