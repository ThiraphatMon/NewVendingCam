import math
import time
from config import (
    FRAME_W,
    FRAME_H,
    TRACK_MATCH_DIST,
    LANDING_STABLE_FRAMES,
    CENTROID_STABLE_DIST as CFG_CENTROID_STABLE_DIST,
)

# จำนวน frame ติดต่อกันที่ centroid ต้องนิ่งพอ จึงถือว่า "ยืนยันรูปร่าง = ลงจอด" ได้
# ปรับผ่าน config.LANDING_STABLE_FRAMES (ยิ่งน้อยยิ่งจับของไว)
SHAPE_STABLE_FRAMES = LANDING_STABLE_FRAMES

# ระยะ pixel ที่ centroid เคลื่อนที่ได้ต่อเฟรมแล้วยังถือว่า "นิ่ง"
# ใช้ centroid แทน area เพราะ noise ข้างใน object ทำให้ box size ขยับ
# แต่ centroid ยังนิ่งอยู่กับที่ → stable ได้แม้ box กระพริบเล็กน้อย
CENTROID_STABLE_DIST = CFG_CENTROID_STABLE_DIST

# จำนวน frame ที่วัตถุหายไปแล้วยังคงรอก่อนลบ (tolerance เผื่อ noise กระพริบ 1-2 frame)
GHOST_FRAME_TOLERANCE = 2


def group_close_boxes(boxes, max_dist=50, overlap_pad=4, mode="distance"):
    """
    รวม bounding boxes ที่เป็นชิ้นส่วนของวัตถุเดียวกันกลับเป็นกล่องเดียว

    mode="distance" (default): รวมกล่องที่ขอบห่างกัน < max_dist
        → ชิ้นส่วนของวัตถุเดียวที่ mask ขาดถูกเชื่อมกลับเป็นก้อน
        → ของ 2 ชิ้นที่ตกห่างกันเกิน max_dist ยังแยกกัน (นับได้หลายชิ้น)

    mode="overlap": รวมเฉพาะกล่องที่ซ้อนทับกันจริง (±overlap_pad px)
        → แยกของที่บินใกล้กันได้ดี แต่วัตถุเดียวที่ mask ขาดจะไม่ถูกเชื่อม

    เลือก mode ผ่าน config.GROUP_MODE
    """
    if not boxes:
        return []

    rects = [[b[0], b[1], b[0] + b[2], b[1] + b[3]] for b in boxes]

    if mode == "overlap":
        def connected(r1, r2):
            return (
                r1[0] - overlap_pad < r2[2]
                and r1[2] + overlap_pad > r2[0]
                and r1[1] - overlap_pad < r2[3]
                and r1[3] + overlap_pad > r2[1]
            )
    else:
        # distance mode (default): ระยะห่างระหว่างขอบกล่อง < max_dist
        def connected(r1, r2):
            dx = max(0, max(r1[0], r2[0]) - min(r1[2], r2[2]))
            dy = max(0, max(r1[1], r2[1]) - min(r1[3], r2[3]))
            return math.hypot(dx, dy) < max_dist

    groups = []
    for r in rects:
        matched = [i for i, g in enumerate(groups) if any(connected(r, gr) for gr in g)]
        if not matched:
            groups.append([r])
        else:
            new_g = [r]
            for i in reversed(matched):
                new_g.extend(groups.pop(i))
            groups.append(new_g)

    return [
        (
            min(r[0] for r in g),
            min(r[1] for r in g),
            max(r[2] for r in g) - min(r[0] for r in g),
            max(r[3] for r in g) - min(r[1] for r in g),
        )
        for g in groups
    ]


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
        # เพราะถ้า reset แล้ว object ใหม่จะได้ id ซ้ำกับที่ sm.land_obj_id จำอยู่
        # ทำให้ของชิ้นใหม่ถูก skip โดยไม่ตั้งใจ
