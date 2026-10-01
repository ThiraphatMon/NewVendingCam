import json
import os
import time
import cv2
import numpy as np
from config import ROI_CHECK_INTERVAL, ROI_CONFIG_PATH
from utils.json_file import write_json_atomic
from utils.logger import get_logger

logger = get_logger("roi")

# ROI_CHECK_INTERVAL: เช็ค mtime ทุกกี่วินาที แทนที่จะเช็คทุก frame (ตั้งใน config)


class ROIManager:
    def __init__(self, frame_w, frame_h, config_path=ROI_CONFIG_PATH):
        self.frame_w = int(frame_w)
        self.frame_h = int(frame_h)
        self.config_path = config_path
        self.last_mtime = None
        self._last_check_time = 0.0  # timestamp ที่เช็ค mtime ล่าสุด
        self.roi_type = "rect"
        self.config_frame_w = self.frame_w
        self.config_frame_h = self.frame_h
        self.areas = []
        self.points = []
        self.rect = {
            "x": self.frame_w // 2,
            "y": 0,
            "w": self.frame_w // 2,
            "h": self.frame_h,
        }
        self.load()

    def _default_config(self):
        return {
            "frame": {"width": self.frame_w, "height": self.frame_h},
            "roi_type": "rect",
            "rect": {
                "x": self.frame_w // 2,
                "y": 0,
                "w": self.frame_w // 2,
                "h": self.frame_h,
            },
        }

    def load(self):
        """โหลด ROI จากไฟล์ (ไม่มีไฟล์ → สร้าง default)
        ไฟล์พัง / เขียนไม่เสร็จ / ค่าผิดรูปแบบ → log warning แล้วใช้ ROI เดิมต่อ (ไม่ทำให้โปรแกรมตาย)"""
        if not os.path.exists(self.config_path):
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            write_json_atomic(self.config_path, self._default_config())

        try:
            self.last_mtime = os.path.getmtime(self.config_path)
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # แปลงค่าทั้งหมดก่อน แล้วค่อยใช้จริง → พังกลางทางจะไม่เหลือ ROI ครึ่ง ๆ
            frame = config.get("frame", {})
            config_frame_w = int(frame.get("width", self.frame_w))
            config_frame_h = int(frame.get("height", self.frame_h))
            roi_type = config.get("roi_type", "rect")
            areas, points, rect = self.areas, self.points, self.rect
            if roi_type == "multi_polygon":
                areas = list(config.get("areas", []))
            elif roi_type in ("polygon", "quad"):
                points = list(config.get("points", []))
            elif roi_type == "rect":
                rect = dict(config.get("rect", self.rect))
        except (OSError, ValueError, TypeError, AttributeError) as e:
            logger.warning(
                f"⚠️ อ่าน ROI จาก {self.config_path} ไม่ได้ ({e}) → ใช้ ROI เดิมต่อ ({self.roi_type})"
            )
            return

        self.config_frame_w, self.config_frame_h = config_frame_w, config_frame_h
        self.roi_type = roi_type
        self.areas, self.points, self.rect = areas, points, rect

        if self.roi_type == "multi_polygon":
            logger.info(f"✅ Loaded multi_polygon ROI: {len(self.areas)} area(s)")
        elif self.roi_type in ("polygon", "quad"):
            logger.info(f"✅ Loaded {self.roi_type} ROI: {len(self.points)} point(s)")
        elif self.roi_type == "rect":
            logger.info("✅ Loaded rect ROI")
        else:
            logger.warning(f"⚠️ Unknown roi_type: {self.roi_type}. Fallback to default rect.")
            self.roi_type = "rect"
            self.rect = self._default_config()["rect"]

    def reload_if_changed(self):
        """เช็คและ reload config — แต่จะทำ syscall getmtime แค่ทุก ROI_CHECK_INTERVAL วินาที
        แทนที่จะเรียกทุก frame เพื่อลด I/O load บน eMMC ของ Pi"""
        now = time.time()
        if now - self._last_check_time < ROI_CHECK_INTERVAL:
            return  # ยังไม่ถึงเวลาเช็ค ข้ามไปก่อน
        self._last_check_time = now

        if not os.path.exists(self.config_path):
            return
        mtime = os.path.getmtime(self.config_path)
        if self.last_mtime is None or mtime != self.last_mtime:
            self.load()

    def _scale_point(self, point):
        scale_x = self.frame_w / max(1, self.config_frame_w)
        scale_y = self.frame_h / max(1, self.config_frame_h)
        x = int(round(float(point["x"]) * scale_x))
        y = int(round(float(point["y"]) * scale_y))
        x = max(0, min(self.frame_w - 1, x))
        y = max(0, min(self.frame_h - 1, y))
        return [x, y]

    def _valid_points(self, points):
        if not isinstance(points, list) or len(points) < 3:
            return None
        try:
            scaled = [self._scale_point(p) for p in points]
            return np.array(scaled, dtype=np.int32).reshape((-1, 1, 2))
        except Exception:
            return None

    def _scaled_rect(self):
        """คืน (x1, y1, x2, y2) ของ rect ROI หลัง scale ตามขนาดเฟรมจริง (clamp ในขอบเฟรม)"""
        scale_x = self.frame_w / max(1, self.config_frame_w)
        scale_y = self.frame_h / max(1, self.config_frame_h)
        x = int(round(float(self.rect.get("x", 0)) * scale_x))
        y = int(round(float(self.rect.get("y", 0)) * scale_y))
        rw = int(round(float(self.rect.get("w", self.frame_w)) * scale_x))
        rh = int(round(float(self.rect.get("h", self.frame_h)) * scale_y))
        x1 = max(0, min(self.frame_w, x))
        y1 = max(0, min(self.frame_h, y))
        x2 = max(0, min(self.frame_w, x + rw))
        y2 = max(0, min(self.frame_h, y + rh))
        return x1, y1, x2, y2

    def build_mask(self, mask_shape):
        h, w = mask_shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        if self.roi_type == "multi_polygon":
            for area in self.areas:
                pts = self._valid_points(area.get("points", []))
                if pts is not None:
                    cv2.fillPoly(mask, [pts], 255)
        elif self.roi_type in ("polygon", "quad"):
            pts = self._valid_points(self.points)
            if pts is not None:
                cv2.fillPoly(mask, [pts], 255)
        elif self.roi_type == "rect":
            x1, y1, x2, y2 = self._scaled_rect()
            mask[y1:y2, x1:x2] = 255

        if cv2.countNonZero(mask) == 0:
            mask[:, w // 2 : w] = 255
        return mask

    def get_roi_areas(self, mask_shape):
        """
        คืน list ของแต่ละ ROI area เป็น dict:
            {"mask": np.uint8 array (same shape as mask_shape), "area_px": int}

        ใช้สำหรับ large motion check per-area
        รองรับทุก roi_type: rect, polygon, quad, multi_polygon
        """
        h, w = mask_shape[:2]
        areas = []

        if self.roi_type == "multi_polygon":
            for area in self.areas:
                pts = self._valid_points(area.get("points", []))
                if pts is None:
                    continue
                m = np.zeros((h, w), dtype=np.uint8)
                cv2.fillPoly(m, [pts], 255)
                area_px = int(cv2.countNonZero(m))
                if area_px > 0:
                    areas.append({"mask": m, "area_px": area_px})

        elif self.roi_type in ("polygon", "quad"):
            pts = self._valid_points(self.points)
            if pts is not None:
                m = np.zeros((h, w), dtype=np.uint8)
                cv2.fillPoly(m, [pts], 255)
                area_px = int(cv2.countNonZero(m))
                if area_px > 0:
                    areas.append({"mask": m, "area_px": area_px})

        elif self.roi_type == "rect":
            x1, y1, x2, y2 = self._scaled_rect()
            m = np.zeros((h, w), dtype=np.uint8)
            m[y1:y2, x1:x2] = 255
            area_px = int(cv2.countNonZero(m))
            if area_px > 0:
                areas.append({"mask": m, "area_px": area_px})

        return areas

    def draw(self, frame):
        overlay = frame.copy()
        if self.roi_type == "multi_polygon":
            for i, area in enumerate(self.areas):
                pts = self._valid_points(area.get("points", []))
                if pts is not None:
                    cv2.fillPoly(overlay, [pts], (255, 200, 0))
                    cv2.polylines(frame, [pts], True, (255, 200, 0), 2)
                    first = pts.reshape(-1, 2)[0]
                    cv2.putText(
                        frame,
                        f"ROI A{i + 1}",
                        (int(first[0]) + 8, int(first[1]) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 200, 0),
                        2,
                    )
            cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, frame)
        elif self.roi_type in ("polygon", "quad"):
            pts = self._valid_points(self.points)
            if pts is not None:
                cv2.fillPoly(overlay, [pts], (255, 200, 0))
                cv2.polylines(frame, [pts], True, (255, 200, 0), 2)
                cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, frame)
        elif self.roi_type == "rect":
            x1, y1, x2, y2 = self._scaled_rect()
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 200, 0), 2)

        cv2.putText(
            frame,
            "DETECTION ROI",
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 200, 0),
            2,
        )
