import math
import time
from config import (
    FRAME_W,
    FRAME_H,
    TRACK_MATCH_DIST,
    LANDING_STABLE_FRAMES,
    CENTROID_STABLE_DIST as CFG_CENTROID_STABLE_DIST,
    GHOST_FRAME_TOLERANCE,
)

# จำนวน frame ติดต่อกันที่ centroid ต้องนิ่งพอ จึงถือว่า "ยืนยันรูปร่าง = ลงจอด" ได้
# ปรับผ่าน config.LANDING_STABLE_FRAMES (ยิ่งน้อยยิ่งจับของไว)
SHAPE_STABLE_FRAMES = LANDING_STABLE_FRAMES

# ระยะ pixel ที่ centroid เคลื่อนที่ได้ต่อเฟรมแล้วยังถือว่า "นิ่ง"
# ใช้ centroid แทน area เพราะ noise ข้างใน object ทำให้ box size ขยับ
# แต่ centroid ยังนิ่งอยู่กับที่ → stable ได้แม้ box กระพริบเล็กน้อย
CENTROID_STABLE_DIST = CFG_CENTROID_STABLE_DIST


class MemoryTracker:
    def __init__(self):
        self.next_id = 1
        self.objects = {}

    def update(self, detected_boxes):
        new_objects = {}
        current_time = time.time()
        matched_ids = set()

        # ── matching: จับ detection เข้ากับ object เดิมที่ใกล้ที่สุด ──────────
        for cx, cy, w, h in detected_boxes:
            best_id, min_dist = None, float("inf")
            for obj_id, obj in self.objects.items():
                if obj_id in matched_ids:
                    continue
                px, py = obj["centroid"]
                d = math.hypot(cx - px, cy - py)
                if d < TRACK_MATCH_DIST and d < min_dist:
                    min_dist, best_id = d, obj_id

            if best_id is not None:
                matched_ids.add(best_id)
                obj = self.objects[best_id]
                px, py = obj["centroid"]
                old_w, old_h = obj["shape"]
                dist = math.hypot(cx - px, cy - py)

                if (w * h) / max(1, old_w * old_h) < 0.75 and dist < 30:
                    # motion หดแปบเดียว → คืน shape เดิม ป้องกัน noise กระพริบ
                    cx, cy, w, h = px, py, old_w, old_h
                else:
                    # ไม่ให้หดเร็วเกิน (smoothing ปกติ)
                    w = max(w, int(old_w * 0.95))
                    h = max(h, int(old_h * 0.95))

                obj["centroid"] = (cx, cy)
                obj["shape"] = (w, h)
                obj["ghost_frames"] = 0

                # Shape stability check
                if obj["state"] != "SHAPE_CONFIRMED":
                    centroid_dist = math.hypot(cx - px, cy - py)
                    if centroid_dist <= CENTROID_STABLE_DIST:
                        obj["shape_stable_count"] = obj.get("shape_stable_count", 0) + 1
                    else:
                        obj["shape_stable_count"] = 0

                    if obj["shape_stable_count"] >= SHAPE_STABLE_FRAMES:
                        obj["shape_confirmed_time"] = current_time
                        obj["state"] = "SHAPE_CONFIRMED"
                    else:
                        obj["state"] = "DETECTING"

                new_objects[best_id] = obj
            else:
                new_objects[self.next_id] = {
                    "centroid": (cx, cy),
                    "shape": (w, h),
                    "state": "MOVING",
                    "first_seen": current_time,
                    "shape_stable_count": 0,
                    "shape_confirmed_time": None,
                    "ghost_frames": 0,
                }
                self.next_id += 1

        # ── disappearance: object เดิมที่ไม่ถูก match ในเฟรมนี้ ───────────────
        for obj_id, obj in self.objects.items():
            if obj_id in matched_ids or obj_id in new_objects:
                continue

            # วัตถุที่เพิ่งเกิดใหม่ไม่กี่ frame → ลบทิ้งทันที ไม่ต้องรอ
            if obj["state"] == "MOVING" and (current_time - obj["first_seen"]) < 0.5:
                continue

            # หายออกจาก ROI: นับ ghost frame จนเกิน tolerance แล้วลบ
            ghost_count = obj.get("ghost_frames", 0) + 1
            if ghost_count > GHOST_FRAME_TOLERANCE:
                continue  # ลบออก — กรอบจะหายไปพร้อมของ

            obj["ghost_frames"] = ghost_count
            obj["state"] = "DETECTING"
            new_objects[obj_id] = obj

        self.objects = new_objects
        return self.objects

    def clear_all(self):
        self.objects.clear()
        # ✅ ไม่ reset next_id กลับเป็น 1
        # เพราะถ้า reset แล้ว object ใหม่จะได้ id ซ้ำกับที่ sm.captured_items จำอยู่
        # ทำให้ของชิ้นใหม่ถูก skip โดยไม่ตั้งใจ
