"""
=======================================================================
 AIoT Intelligence Forest Protection - AI Vision & Detection Engine
=======================================================================
Fitur:
  1. Deteksi Pohon Ditebang, Pohon Jatuh Alami, dan Api (YOLOv8 + Fallback)
  2. Titik-Titik Penentu Khusus Area 1 & Area 2 (4 titik poligon per area)
  3. Klasifikasi Zona menggunakan Point-In-Polygon (cv2.pointPolygonTest)
  4. Perhitungan sudut servo penargetan berdasarkan posisi objek di area
  5. Visualisasi titik penentu (P1, P2, P3, P4), garis area, dan highlight api
=======================================================================
"""

import os
import json
import time
import cv2
import numpy as np

CLASSES = [
    "Pohon yang ditebang",
    "Pohon jatuh alami",
    "Api"
]

CLASS_COLORS = {
    0: (0, 165, 255),  # Kuning-Oranye untuk Pohon Ditebang
    1: (0, 255, 120),  # Hijau untuk Pohon Jatuh Alami
    2: (0, 0, 255)     # Merah Cerah untuk Api
}

DEFAULT_SERVO_POINTS = {
    "area1": {
        "p0":  {"name": "S1: 0°",  "x": 0.184, "y": 0.662, "angle": 0},
        "p90": {"name": "S1: 90°", "x": 0.297, "y": 0.383, "angle": 90}
    },
    "area2": {
        "p0":  {"name": "S2: 0°",  "x": 0.562, "y": 0.588, "angle": 0},
        "p90": {"name": "S2: 90°", "x": 0.506, "y": 0.879, "angle": 90}
    }
}

DEFAULT_ZONES_CONFIG = {
    "version": "1.0",
    "description": "Konfigurasi 4 Titik Poligon & Kalibrasi Sudut Servo (0° - 90°)",
    "area1": {
        "name": "Area 1",
        "servo": 1,
        "servo_gpio": 16,
        "relay": 1,
        "relay_gpio": 25,
        "servo_points": DEFAULT_SERVO_POINTS["area1"],
        "points": [
            {"name": "P1 (Kiri Atas)",   "x": 0.05, "y": 0.15},
            {"name": "P2 (Kanan Atas)",  "x": 0.45, "y": 0.15},
            {"name": "P3 (Kanan Bawah)", "x": 0.45, "y": 0.85},
            {"name": "P4 (Kiri Bawah)",  "x": 0.05, "y": 0.85}
        ]
    },
    "area2": {
        "name": "Area 2",
        "servo": 2,
        "servo_gpio": 17,
        "relay": 2,
        "relay_gpio": 26,
        "servo_points": DEFAULT_SERVO_POINTS["area2"],
        "points": [
            {"name": "P1 (Kiri Atas)",   "x": 0.55, "y": 0.15},
            {"name": "P2 (Kanan Atas)",  "x": 0.95, "y": 0.15},
            {"name": "P3 (Kanan Bawah)", "x": 0.95, "y": 0.85},
            {"name": "P4 (Kiri Bawah)",  "x": 0.55, "y": 0.85}
        ]
    }
}


class ForestAIDetector:
    def __init__(self, model_path=None, conf_thresh=0.45, config_path="data/zones_config.json"):
        self.conf_thresh = conf_thresh
        self.config_path = config_path
        self.model = None
        self.use_yolo = False
        self._last_config_mtime = 0.0
        self._last_mtime_check = 0.0
        
        # Cari file weights model YOLO hasil training
        candidate_paths = [
            model_path,
            "runs/detect/runs/forest_ai/forest_protection_model/weights/best.pt",
            "runs/forest_ai/forest_protection_model/weights/best.pt",
            "runs/detect/runs/forest_ai/forest_protection_model/weights/last.pt",
            "best.pt"
        ]
        
        active_model_path = None
        for p in candidate_paths:
            if p and os.path.exists(p):
                active_model_path = p
                break
                
        if active_model_path:
            try:
                from ultralytics import YOLO
                self.model = YOLO(active_model_path)
                self.use_yolo = True
                print(f"[AI ENGINE] Loaded custom YOLOv8 model from: {active_model_path}")
            except Exception as e:
                print(f"[AI ENGINE] Could not load YOLO model ({e}). Using Vision Fallback engine.")
        else:
            print("[AI ENGINE] Model YOLO tidak ditemukan di path utama, menggunakan Computer Vision Fallback Engine.")

        # Muat konfigurasi titik-titik area 1 dan area 2 serta sudut servo 0°-90°
        self.zones = self._load_zones_config()

    def _get_candidate_config_paths(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(script_dir) if os.path.basename(script_dir) == "python_backend" else script_dir
        paths = []
        if self.config_path:
            paths.append(self.config_path)
            if not os.path.isabs(self.config_path):
                paths.append(os.path.join(root_dir, self.config_path))
                paths.append(os.path.join(script_dir, self.config_path))
        paths.append(os.path.join(root_dir, "data", "zones_config.json"))
        paths.append(os.path.join(root_dir, "python_backend", "data", "zones_config.json"))
        # Remove duplicates while preserving order
        seen = set()
        deduped = []
        for p in paths:
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                deduped.append(ap)
        return deduped

    def _load_zones_config(self):
        """Memuat 4 titik penentu untuk Area 1 dan Area 2 serta titik servo 0°-90° dari JSON."""
        candidate_paths = self._get_candidate_config_paths()
        for cp in candidate_paths:
            if os.path.exists(cp):
                try:
                    with open(cp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        # Pastikan servo_points terisi jika belum ada
                        for ak in ["area1", "area2"]:
                            if ak in data and "servo_points" not in data[ak]:
                                data[ak]["servo_points"] = DEFAULT_SERVO_POINTS[ak]
                        try:
                            self._last_config_mtime = os.path.getmtime(cp)
                        except Exception:
                            pass
                        print(f"[AI ENGINE] Berhasil memuat titik area & servo dari {cp}")
                        return data
                except Exception as e:
                    print(f"[AI ENGINE ERROR] Gagal membaca {cp}: {e}")
        
        # Fallback dan simpan konfigurasi default
        target = candidate_paths[0] if candidate_paths else "data/zones_config.json"
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_ZONES_CONFIG, f, indent=2)
        except Exception:
            pass
        return DEFAULT_ZONES_CONFIG

    def check_and_reload_zones_if_modified(self):
        """Mengecek apakah file konfigurasi diubah (misal oleh calibrate_zones.py) dan memuat ulang otomatis."""
        now = time.time()
        if now - self._last_mtime_check < 1.0:
            return
        self._last_mtime_check = now

        candidate_paths = self._get_candidate_config_paths()
        for cp in candidate_paths:
            if os.path.exists(cp):
                try:
                    mtime = os.path.getmtime(cp)
                    if self._last_config_mtime > 0 and mtime > self._last_config_mtime:
                        with open(cp, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            for ak in ["area1", "area2"]:
                                if ak in data and "servo_points" not in data[ak]:
                                    data[ak]["servo_points"] = DEFAULT_SERVO_POINTS[ak]
                            self.zones = data
                            self._last_config_mtime = mtime
                            print(f"[AI ENGINE] 🔄 Memuat ulang konfigurasi zona & servo dari {cp} (diperbarui oleh kalibrasi)")
                        break
                except Exception:
                    pass

    def save_zones_config(self, new_zones_dict):
        """Menyimpan pembaruan titik area dan sudut servo ke semua file konfigurasi zona."""
        self.zones = new_zones_dict
        candidate_paths = self._get_candidate_config_paths()
        for cp in candidate_paths:
            try:
                os.makedirs(os.path.dirname(cp), exist_ok=True)
                with open(cp, "w", encoding="utf-8") as f:
                    json.dump(new_zones_dict, f, indent=2)
                try:
                    self._last_config_mtime = os.path.getmtime(cp)
                except Exception:
                    pass
                print(f"[AI ENGINE] Titik area & sudut berhasil disimpan ke {cp}")
            except Exception as e:
                print(f"[AI ENGINE ERROR] Gagal menyimpan ke {cp}: {e}")

    def get_zone_polygons_pixels(self, frame_w, frame_h):
        """Mengubah koordinat ternormalisasi (0.0-1.0) menjadi koordinat piksel."""
        def extract_pts(area_key):
            pts = []
            pts_data = self.zones.get(area_key, {}).get("points", [])
            for p in pts_data:
                px = int(np.clip(p.get("x", 0.0) * frame_w, 0, frame_w - 1))
                py = int(np.clip(p.get("y", 0.0) * frame_h, 0, frame_h - 1))
                pts.append([px, py])
            return np.array(pts, dtype=np.int32)

        poly1 = extract_pts("area1")
        poly2 = extract_pts("area2")
        return poly1, poly2

    def compute_calibrated_angle(self, cx, cy, area_key, frame_w, frame_h):
        """
        Menghitung sudut servo (0° - 90°) berdasarkan proyeksi vektor api (cx, cy)
        terhadap garis kalibrasi p0 (0°) dan p90 (90°) yang ditentukan di calibrate_zones.py.
        """
        s_pts = self.zones.get(area_key, {}).get("servo_points", {})
        p0 = s_pts.get("p0")
        p90 = s_pts.get("p90")

        if not p0 or not p90:
            return 90, (int(cx), int(cy))

        x0 = float(p0.get("x", 0.0)) * frame_w
        y0 = float(p0.get("y", 0.0)) * frame_h
        x1 = float(p90.get("x", 1.0)) * frame_w
        y1 = float(p90.get("y", 1.0)) * frame_h

        dx = x1 - x0
        dy = y1 - y0
        seg_sq = dx * dx + dy * dy

        if seg_sq < 1.0:
            return 45, (int(x0), int(y0))

        # Proyeksi vektor titik api (cx, cy) ke ruas garis (x0, y0) -> (x1, y1)
        u_x = cx - x0
        u_y = cy - y0
        t = (u_x * dx + u_y * dy) / seg_sq
        t_clamped = float(np.clip(t, 0.0, 1.0))

        angle_min = float(p0.get("angle", 0))
        angle_max = float(p90.get("angle", 90))
        calc_angle = int(round(angle_min + t_clamped * (angle_max - angle_min)))

        proj_x = int(round(x0 + t_clamped * dx))
        proj_y = int(round(y0 + t_clamped * dy))

        return int(np.clip(calc_angle, 0, 180)), (proj_x, proj_y)

    def determine_zone_and_angle(self, cx, cy, poly1, poly2, frame_w, frame_h=480):
        """
        Menentukan apakah titik (cx, cy) berada di Area 1 atau Area 2 
        menggunakan cv2.pointPolygonTest, lalu menghitung sudut servo presisi (0°-90°).
        """
        in_area1 = False
        in_area2 = False

        if len(poly1) >= 3:
            in_area1 = (cv2.pointPolygonTest(poly1, (float(cx), float(cy)), False) >= 0)
        if len(poly2) >= 3:
            in_area2 = (cv2.pointPolygonTest(poly2, (float(cx), float(cy)), False) >= 0)

        zone = 0
        angle = 90
        proj_pt = (int(cx), int(cy))

        if in_area1:
            zone = 1
            angle, proj_pt = self.compute_calibrated_angle(cx, cy, "area1", frame_w, frame_h)
        elif in_area2:
            zone = 2
            angle, proj_pt = self.compute_calibrated_angle(cx, cy, "area2", frame_w, frame_h)
        else:
            # Di luar kedua titik area yang ditentukan
            zone = 0
            angle = int(np.clip((cx / max(1, frame_w)) * 180, 0, 180))
            proj_pt = (int(cx), int(cy))

        return zone, angle, proj_pt

    def detect(self, frame):
        """
        Memproses frame gambar dan mengembalikan deteksi serta frame beranotasi.
        """
        if frame is None or frame.size == 0:
            return frame, []

        # Otomatis reload jika zones_config.json diubah (misal dari calibrate_zones.py)
        self.check_and_reload_zones_if_modified()

        h, w, _ = frame.shape
        poly1, poly2 = self.get_zone_polygons_pixels(w, h)
        detections = []

        # 1. Jalankan inferensi YOLO
        yolo_has_fire = False
        if self.use_yolo and self.model is not None:
            results = self.model(frame, conf=self.conf_thresh, verbose=False)
            for r in results:
                boxes = r.boxes
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())
                    xyxy = box.xyxy[0].cpu().numpy().astype(int)
                    x1, y1, x2, y2 = xyxy

                    # Ambil titik tengah objek
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2

                    zone, angle, proj_pt = self.determine_zone_and_angle(cx, cy, poly1, poly2, w, h)
                    # Jika titik tengah belum masuk area, cek titik dasar objek (y2)
                    if zone == 0:
                        zone, angle, proj_pt = self.determine_zone_and_angle(cx, y2, poly1, poly2, w, h)

                    label = self.model.names.get(cls_id, CLASSES[cls_id % len(CLASSES)])
                    detections.append({
                        "class_id": cls_id,
                        "label": label,
                        "confidence": round(conf, 2),
                        "bbox": [int(x1), int(y1), int(x2), int(y2)],
                        "center": [int(cx), int(cy)],
                        "zone": zone,
                        "angle": angle,
                        "proj_pt": proj_pt
                    })
                    if label.lower() == "api" or cls_id == 2:
                        yolo_has_fire = True

        # 2. HSV Fire Detection Fallback (Paralel / Cadangan)
        if not yolo_has_fire:
            hsv_fire = self._fallback_vision_detection(frame, poly1, poly2)
            if hsv_fire:
                detections.extend(hsv_fire)

        # 3. Fallback umum jika YOLO belum aktif
        if not self.use_yolo and len(detections) == 0:
            fallback = self._fallback_vision_detection(frame, poly1, poly2)
            if fallback:
                detections.extend(fallback)

        # Gambar anotasi area (titik-titik, garis, poligon, garis sudut 0°-90°) dan objek
        annotated_frame = self._draw_annotations(frame.copy(), detections, poly1, poly2)
        return annotated_frame, detections

    def _fallback_vision_detection(self, frame, poly1, poly2):
        """Deteksi warna api dengan HSV sebagai pengaman tambahan."""
        h, w, _ = frame.shape
        detections = []

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower_fire1 = np.array([0, 100, 200], dtype=np.uint8)
        upper_fire1 = np.array([25, 255, 255], dtype=np.uint8)
        lower_fire2 = np.array([170, 100, 200], dtype=np.uint8)
        upper_fire2 = np.array([180, 255, 255], dtype=np.uint8)

        mask1 = cv2.inRange(hsv, lower_fire1, upper_fire1)
        mask2 = cv2.inRange(hsv, lower_fire2, upper_fire2)
        fire_mask = cv2.bitwise_or(mask1, mask2)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        fire_mask = cv2.morphologyEx(fire_mask, cv2.MORPH_OPEN, kernel)
        fire_mask = cv2.morphologyEx(fire_mask, cv2.MORPH_DILATE, kernel)

        contours, _ = cv2.findContours(fire_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > 400:
                x, y, bw, bh = cv2.boundingRect(cnt)
                x1, y1, x2, y2 = x, y, x + bw, y + bh
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                zone, angle, proj_pt = self.determine_zone_and_angle(cx, cy, poly1, poly2, w, h)
                if zone == 0:
                    zone, angle, proj_pt = self.determine_zone_and_angle(cx, y2, poly1, poly2, w, h)

                conf = min(0.98, 0.65 + (area / 10000.0))
                detections.append({
                    "class_id": 2,
                    "label": "Api",
                    "confidence": round(conf, 2),
                    "bbox": [x1, y1, x2, y2],
                    "center": [cx, cy],
                    "zone": zone,
                    "angle": angle,
                    "proj_pt": proj_pt
                })

        return detections

    def _draw_annotations(self, frame, detections, poly1, poly2):
        """
        Menggambar titik-titik penentu khusus, garis poligon area, 
        garis referensi sudut servo 0°-90°, label panduan, dan target sudut api.
        """
        h, w, _ = frame.shape
        overlay = frame.copy()

        # Cek apakah ada api di area 1 atau area 2
        fire_in_area1 = any(d.get("label") == "Api" and d.get("zone") == 1 for d in detections)
        fire_in_area2 = any(d.get("label") == "Api" and d.get("zone") == 2 for d in detections)

        # ── 1. GAMBAR POLIGON & TITIK PENENTU AREA 1 ──
        color_area1 = (0, 0, 255) if fire_in_area1 else (255, 200, 0) # Cyan atau Merah jika api
        if len(poly1) >= 4:
            # Shading transparan
            cv2.fillPoly(overlay, [poly1], (0, 60, 200) if fire_in_area1 else (100, 80, 20))
            # Garis tepi poligon
            thick1 = 3 if fire_in_area1 else 2
            cv2.polylines(frame, [poly1], True, color_area1, thick1, cv2.LINE_AA)

            # Gambar 4 Titik Khusus Penentu Area 1
            labels1 = ["1:TL", "1:TR", "1:BR", "1:BL"]
            for i, pt in enumerate(poly1):
                pt_x, pt_y = int(pt[0]), int(pt[1])
                cv2.circle(frame, (pt_x, pt_y), 7, color_area1, -1)
                cv2.circle(frame, (pt_x, pt_y), 9, (255, 255, 255), 2)
                lbl_name = labels1[i] if i < len(labels1) else f"1:P{i+1}"
                cv2.putText(frame, lbl_name, (pt_x + 8, pt_y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(frame, lbl_name, (pt_x + 8, pt_y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color_area1, 1, cv2.LINE_AA)

            # Label Header Area 1
            top_pt1 = poly1[np.argmin(poly1[:, 1])]
            header_text1 = "🔥 AREA 1 [SERVO 1 - GPIO 16 | RELAY 1]" if fire_in_area1 else "AREA 1 (Servo 1: GPIO 16)"
            cv2.putText(frame, header_text1, (max(10, top_pt1[0] - 20), max(25, top_pt1[1] - 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(frame, header_text1, (max(10, top_pt1[0] - 20), max(25, top_pt1[1] - 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 255) if fire_in_area1 else (255, 220, 0), 1, cv2.LINE_AA)

        # ── 2. GAMBAR POLIGON & TITIK PENENTU AREA 2 ──
        color_area2 = (0, 0, 255) if fire_in_area2 else (0, 165, 255) # Oranye/Kuning atau Merah jika api
        if len(poly2) >= 4:
            # Shading transparan
            cv2.fillPoly(overlay, [poly2], (0, 60, 200) if fire_in_area2 else (20, 60, 100))
            # Garis tepi poligon
            thick2 = 3 if fire_in_area2 else 2
            cv2.polylines(frame, [poly2], True, color_area2, thick2, cv2.LINE_AA)

            # Gambar 4 Titik Khusus Penentu Area 2
            labels2 = ["2:TL", "2:TR", "2:BR", "2:BL"]
            for i, pt in enumerate(poly2):
                pt_x, pt_y = int(pt[0]), int(pt[1])
                cv2.circle(frame, (pt_x, pt_y), 7, color_area2, -1)
                cv2.circle(frame, (pt_x, pt_y), 9, (255, 255, 255), 2)
                lbl_name = labels2[i] if i < len(labels2) else f"2:P{i+1}"
                cv2.putText(frame, lbl_name, (pt_x + 8, pt_y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(frame, lbl_name, (pt_x + 8, pt_y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color_area2, 1, cv2.LINE_AA)

            # Label Header Area 2
            top_pt2 = poly2[np.argmin(poly2[:, 1])]
            header_text2 = "🔥 AREA 2 [SERVO 2 - GPIO 17 | RELAY 2]" if fire_in_area2 else "AREA 2 (Servo 2: GPIO 17)"
            cv2.putText(frame, header_text2, (max(10, top_pt2[0] - 20), max(25, top_pt2[1] - 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(frame, header_text2, (max(10, top_pt2[0] - 20), max(25, top_pt2[1] - 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 255) if fire_in_area2 else (0, 165, 255), 1, cv2.LINE_AA)

        # Gabungkan shading transparansi
        cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)

        # ── 3. GAMBAR GARIS & TITIK KALIBRASI SUDUT SERVO (0° - 90°) ──
        cfg_angles = [
            ("area1", (255, 230, 0), "S1"),    # Kuning/Cyan S1
            ("area2", (255, 100, 255), "S2")   # Magenta S2
        ]
        for ak, col, pfx in cfg_angles:
            s_pts = self.zones.get(ak, {}).get("servo_points", {})
            if "p0" in s_pts and "p90" in s_pts:
                p0 = s_pts["p0"]
                p90 = s_pts["p90"]
                x0, y0 = int(float(p0.get("x", 0.0)) * w), int(float(p0.get("y", 0.0)) * h)
                x1, y1 = int(float(p90.get("x", 1.0)) * w), int(float(p90.get("y", 1.0)) * h)

                # Garis penghubung 0° ke 90°
                cv2.line(frame, (x0, y0), (x1, y1), col, 2, cv2.LINE_AA)

                # Titik tengah (45°)
                mid_x, mid_y = (x0 + x1) // 2, (y0 + y1) // 2
                cv2.circle(frame, (mid_x, mid_y), 3, (255, 255, 255), -1)
                cv2.putText(frame, "45°", (mid_x + 5, mid_y - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (220, 220, 220), 1, cv2.LINE_AA)

                # Titik P0 (0°)
                cv2.circle(frame, (x0, y0), 7, col, -1)
                cv2.circle(frame, (x0, y0), 9, (255, 255, 255), 1)
                cv2.putText(frame, f"{pfx}: 0°", (x0 - 15, y0 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 2, cv2.LINE_AA)

                # Titik P90 (90°)
                cv2.circle(frame, (x1, y1), 7, col, -1)
                cv2.circle(frame, (x1, y1), 9, (255, 255, 255), 1)
                cv2.putText(frame, f"{pfx}: 90°", (x1 + 8, y1 + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 2, cv2.LINE_AA)

        # ── 4. GAMBAR BOUNDING BOX OBJEK & PROYEKSI TARGET SUDUT API ──
        for det in detections:
            cls_id = det["class_id"]
            label = det["label"]
            conf = det["confidence"]
            x1, y1, x2, y2 = det["bbox"]
            zone = det["zone"]
            angle = det["angle"]
            proj_pt = det.get("proj_pt")
            color = CLASS_COLORS.get(cls_id, (0, 255, 0))

            zone_str = f"Area {zone}" if zone in (1, 2) else "Luar Area"

            # Kotak bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # Tag teks
            tag = f"{label} {int(conf * 100)}% | {zone_str} ({angle}°)"
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(frame, (x1, max(0, y1 - 22)), (x1 + tw + 6, max(22, y1)), color, -1)
            cv2.putText(frame, tag, (x1 + 3, max(16, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255) if cls_id == 2 else (0, 0, 0), 1, cv2.LINE_AA)

            # Bidik silang (reticle) dan proyeksi ke sumbu sudut 0°-90° jika objek adalah Api
            if label.lower() == "api" or cls_id == 2:
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                cv2.drawMarker(frame, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
                cv2.circle(frame, (cx, cy), 12, (0, 255, 255), 1)

                if zone in (1, 2) and proj_pt:
                    target_col = (0, 255, 255) if zone == 1 else (255, 120, 255)
                    cv2.circle(frame, proj_pt, 6, target_col, -1)
                    cv2.circle(frame, proj_pt, 8, (255, 255, 255), 1)
                    cv2.line(frame, (cx, cy), proj_pt, target_col, 1, cv2.LINE_AA)
                    cv2.putText(frame, f"S{zone} Target: {angle}°", (x1, y2 + 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.50, target_col, 2, cv2.LINE_AA)

        # Header peringatan bila ada kebakaran
        if fire_in_area1 or fire_in_area2:
            alert_bar = np.zeros((40, w, 3), dtype=np.uint8)
            alert_bar[:] = (0, 0, 200) # Merah mencolok
            msg = "🚨 PERINGATAN API TERDETEKSI: SISTEM PEMADAM OTOMATIS AKTIF!"
            cv2.putText(alert_bar, msg, (20, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (255, 255, 255), 2, cv2.LINE_AA)
            frame[0:40, 0:w] = cv2.addWeighted(alert_bar, 0.85, frame[0:40, 0:w], 0.15, 0)

        return frame
