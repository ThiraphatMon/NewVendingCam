import math
import time
from config import (
    FRAME_W,
    FRAME_H,
    TRACK_MATCH_DIST,
    LANDING_STABLE_FRAMES,
    CENTROID_STABLE_DIST,
    GHOST_FRAME_TOLERANCE,
    STRICT_STABILITY,
)

# การนิ่ง ("ลงจอด") ใช้ config:
#   LANDING_STABLE_FRAMES : จำนวนเฟรมติดกันที่ centroid ต้องนิ่ง
#   CENTROID_STABLE_DIST  : ระยะ px ที่ centroid ขยับได้ต่อเฟรมแล้วยังถือว่านิ่ง
#   ใช้ centroid แทน area เพราะ noise ข้างใน object ทำให้ box size ขยับ
#   แต่ centroid ยังนิ่งอยู่กับที่ → stable ได้แม้ box กระพริบเล็กน้อย
#   STRICT_STABILITY=1 (เข้มขึ้น):
#     F03 ขยับเกิน CENTROID_STABLE_DIST ระหว่าง hold (SHAPE_CONFIRMED) → ถอนสถานะ เริ่มนับนิ่งใหม่
#     F04 หายไป (ghost) แล้วกลับมา → เริ่มนับความนิ่งใหม่ ไม่สะสมข้ามช่วงที่หาย

# ── ค่าคงที่ภายใน tracker (ไม่ได้เปิดให้ตั้งใน .env) ──────────────────────────────
# กล่องหดเหลือน้อยกว่า SHRINK_RATIO ของเดิม และ centroid ขยับไม่เกิน SHRINK_MAX_MOVE px
# → ถือว่า mask หดแปบเดียว (noise กระพริบ) คืนกล่องเดิมทั้งหมด
SHRINK_RATIO = 0.75
SHRINK_MAX_MOVE = 30
# กรณีปกติ: กล่องหดได้ไม่เกินเฟรมละ (1 - SHRINK_SMOOTH) = 5% (smoothing)
SHRINK_SMOOTH = 0.95
# object ใหม่ (MOVING) ที่หายไปภายในเวลานี้ → ลบทันที ไม่ต้องรอ ghost tolerance
NEW_OBJ_GRACE_SEC = 0.5

# state ของ object ที่ถือว่ายัง "ขยับ / ยังไม่ถูกนับ" อยู่ใน ROI
ACTIVE_STATES = ("MOVING", "DETECTING", "SHAPE_CONFIRMED")


def is_motion_in_roi(tracked):
    """มี object ใดใน ROI ที่ยังขยับอยู่ไหม (ใช้ตอน IDLE ตัดสินว่าเริ่มมีของตก)"""
    return any(
        obj["state"] in ACTIVE_STATES or "WAITING" in obj["state"]
        for obj in tracked.values()
    )


def has_active_motion(tracked, captured_ids):
    """มีมือ/ของใหม่ขยับใน ROI ไหม โดยไม่นับ object ที่ capture ไปแล้ว
    (ใช้หยุด hold timer หลังจับของได้ และแสดงผลบนจอ)"""
    return any(
        obj_id not in captured_ids and obj["state"] in ACTIVE_STATES
        for obj_id, obj in tracked.items()
    )


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

                if (w * h) / max(1, old_w * old_h) < SHRINK_RATIO and dist < SHRINK_MAX_MOVE:
                    # motion หดแปบเดียว → คืน shape เดิม ป้องกัน noise กระพริบ
                    cx, cy, w, h = px, py, old_w, old_h
                else:
                    # ไม่ให้หดเร็วเกิน (smoothing ปกติ)
                    w = max(w, int(old_w * SHRINK_SMOOTH))
                    h = max(h, int(old_h * SHRINK_SMOOTH))

                obj["centroid"] = (cx, cy)
                obj["shape"] = (w, h)
                obj["ghost_frames"] = 0
                obj["frames"] = obj.get("frames", 1) + 1  # [TIMING] จำนวนเฟรมที่เห็น (log เท่านั้น)

                # Shape stability check
                centroid_dist = math.hypot(cx - px, cy - py)
                if obj["state"] == "SHAPE_CONFIRMED":
                    if STRICT_STABILITY and centroid_dist > CENTROID_STABLE_DIST:
                        # [F03] ขยับระหว่าง hold → ยังไม่ลงจอดจริง ถอนสถานะ เริ่มนับนิ่งใหม่
                        obj["state"] = "DETECTING"
                        obj["shape_stable_count"] = 0
                        obj["shape_confirmed_time"] = None
                        obj["still_resets"] = obj.get("still_resets", 0) + 1
                else:
                    if centroid_dist <= CENTROID_STABLE_DIST:
                        obj["shape_stable_count"] = obj.get("shape_stable_count", 0) + 1
                    else:
                        if obj.get("shape_stable_count", 0):
                            obj["still_resets"] = obj.get("still_resets", 0) + 1
                        obj["shape_stable_count"] = 0

                    if obj["shape_stable_count"] >= LANDING_STABLE_FRAMES:
                        obj["shape_confirmed_time"] = current_time
                        obj["still_frame"] = obj["frames"]  # [TIMING] เฟรมที่เริ่มนับ hold
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
                    "frames": 1,
                    "still_resets": 0,
                }
                self.next_id += 1

        # ── disappearance: object เดิมที่ไม่ถูก match ในเฟรมนี้ ───────────────
        for obj_id, obj in self.objects.items():
            if obj_id in matched_ids or obj_id in new_objects:
                continue

            # วัตถุที่เพิ่งเกิดใหม่ไม่กี่ frame → ลบทิ้งทันที ไม่ต้องรอ
            if obj["state"] == "MOVING" and (current_time - obj["first_seen"]) < NEW_OBJ_GRACE_SEC:
                continue

            # หายออกจาก ROI: นับ ghost frame จนเกิน tolerance แล้วลบ
            ghost_count = obj.get("ghost_frames", 0) + 1
            if ghost_count > GHOST_FRAME_TOLERANCE:
                continue  # ลบออก — กรอบจะหายไปพร้อมของ

            obj["ghost_frames"] = ghost_count
            obj["state"] = "DETECTING"
            if STRICT_STABILITY:
                # [F04] หายไปแล้วกลับมา → ต้องนิ่งครบ LANDING_STABLE_FRAMES ใหม่ ไม่สะสมข้ามช่วงหาย
                if obj.get("shape_stable_count", 0) or obj.get("shape_confirmed_time"):
                    obj["still_resets"] = obj.get("still_resets", 0) + 1
                obj["shape_stable_count"] = 0
                obj["shape_confirmed_time"] = None
            new_objects[obj_id] = obj

        self.objects = new_objects
        return self.objects

    def clear_all(self):
        self.objects.clear()
        # ✅ ไม่ reset next_id กลับเป็น 1
        # เพราะถ้า reset แล้ว object ใหม่จะได้ id ซ้ำกับที่ sm.captured_items จำอยู่
        # ทำให้ของชิ้นใหม่ถูก skip โดยไม่ตั้งใจ
