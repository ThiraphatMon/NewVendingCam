import math
import time
from config import CONFIRM_TIME, FRAME_W, FRAME_H

EDGE_MARGIN = 5  # pixel margin สำหรับตัดสิน edge kill

# จำนวน frame ติดต่อกันที่ centroid ต้องนิ่งพอ จึงถือว่า "ยืนยันรูปร่าง" ได้
SHAPE_STABLE_FRAMES = 5
# ระยะ pixel ที่ centroid เคลื่อนที่ได้ต่อเฟรมแล้วยังถือว่า "นิ่ง"
# ใช้ centroid แทน area เพราะ noise ข้างใน object ทำให้ box size ขยับ
# แต่ centroid ยังนิ่งอยู่กับที่ → stable ได้แม้ box กระพริบเล็กน้อย
CENTROID_STABLE_DIST = 10  # pixel

# [BUG FIX 1] จำนวน frame ที่วัตถุหายไปแล้วยังคงรอก่อนลบ
# ตั้งเป็น 0 = ลบทันทีที่หายออกจาก ROI (ไม่มีกรอบค้าง)
# ตั้งเป็น 2-3 = tolerance เล็กน้อยเผื่อ noise กระพริบ 1-2 frame
GHOST_FRAME_TOLERANCE = 2

# [BUG FIX: กรอบ CONFIRMED ค้าง]
# จำนวน frame ที่ object ซึ่ง confirmed แล้ว (CONFIRMED_STOP) หายจาก ROI
# ก่อนจะถือว่า "ของออกไปจริง" และลบทิ้ง
# ของ confirmed มักนิ่งอยู่กับที่ → motion mask อาจกระพริบหายเป็นบางจังหวะ
# จึงให้ tolerance สูงกว่า object ทั่วไปเล็กน้อย แต่ต้องลบได้ในที่สุด
# (ห้ามตั้งสูงเกินไป ไม่งั้นกรอบเขียวจะค้างนานหลังของออกจาก ROI)
# เพิ่มเป็น 25 frames (~1 วินาที ที่ 25fps)
# ให้ object CONFIRMED_STOP ทน ghost ได้นานพอที่มือปัดผ่านจะไม่ทำให้ถูกลบ
CONFIRMED_GHOST_FRAME_TOLERANCE = 60




def group_close_boxes(boxes, max_dist=50):
    """
    Merge bounding boxes that actually OVERLAP each other (or touch within
    OVERLAP_PAD pixels).  Boxes that are merely *near* each other but do
    not intersect are kept separate — this prevents two distinct falling
    items from being merged into one giant box when they fly close together.

    max_dist parameter is kept for API compatibility but is no longer used
    as the merge criterion; use OVERLAP_PAD below to control the tolerance.
    """
    if not boxes:
        return []

    # How many pixels of gap are still treated as "touching / same object".
    # Set to 0 to merge only truly overlapping boxes.
    # Increase slightly (e.g. 4-8) to handle 1-pixel noise between contours
    # of the same physical item.
    OVERLAP_PAD = 4

    rects = [[b[0], b[1], b[0] + b[2], b[1] + b[3]] for b in boxes]

    def overlaps(r1, r2):
        """Return True if two rects overlap (or are within OVERLAP_PAD pixels)."""
        return (
            r1[0] - OVERLAP_PAD < r2[2]
            and r1[2] + OVERLAP_PAD > r2[0]
            and r1[1] - OVERLAP_PAD < r2[3]
            and r1[3] + OVERLAP_PAD > r2[1]
        )

    groups = []
    for r in rects:
        matched = [i for i, g in enumerate(groups) if any(overlaps(r, gr) for gr in g)]
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
        # set ของ obj_id ที่ confirmed แล้ว → ใช้ตรวจการขยายกรอบ
        self._confirmed_ids: set = set()

    def mark_confirmed(self, obj_id: int):
        """
        เรียกจาก main loop ทันทีหลัง state_machine capture ของชิ้นนั้น
        snapshot centroid เป็น baseline สำหรับตรวจ drift และตั้ง state เป็น CONFIRMED_STOP
        """
        if obj_id in self.objects:
            obj = self.objects[obj_id]
            # snapshot shape และ centroid ณ ตอน confirm เป็น baseline
            # ใช้ clamp ไม่ให้กรอบขยายเกินขนาดของจริง
            obj["confirmed_shape"] = obj["shape"]
            obj["confirmed_centroid"] = obj["centroid"]
            obj["state"] = "CONFIRMED_STOP"
            self._confirmed_ids.add(obj_id)

    def update(self, detected_boxes):
        new_objects = {}
        current_time = time.time()
        matched_ids = set()
        available = list(self.objects.keys())

        for box in detected_boxes:
            cx, cy, w, h = box
            best_id, min_dist = None, float("inf")
            for obj_id in available:
                if obj_id in matched_ids:
                    continue
                px, py = self.objects[obj_id]["centroid"]
                d = math.hypot(cx - px, cy - py)
                if d < 150 and d < min_dist:
                    min_dist, best_id = d, obj_id

            if best_id is not None:
                matched_ids.add(best_id)
                obj = self.objects[best_id]
                px, py = obj["centroid"]
                old_w, old_h = obj["shape"]
                dist = math.hypot(cx - px, cy - py)

                if obj["state"] == "CONFIRMED_STOP":
                    # CONFIRMED_STOP: ใช้ขนาดจาก motion mask จริงเลย
                    # ไม่ smoothing ทั้ง 2 ทิศทาง (ไม่บวม / ไม่ค้าง)
                    # กรอบสะท้อนขนาดวัตถุจริงที่เห็นใน motion mask เสมอ
                    pass
                elif (w * h) / max(1, old_w * old_h) < 0.75 and dist < 30:
                    # object ที่ยังไม่ confirmed: ถ้า motion หดแปบเดียว → คืน shape เดิม
                    # ป้องกัน noise ทำให้กรอบกระพริบ
                    cx, cy, w, h, dist = px, py, old_w, old_h, 0
                else:
                    # object ที่ยังไม่ confirmed: ไม่ให้หดเร็วเกิน (smoothing ปกติ)
                    w = max(w, int(old_w * 0.95))
                    h = max(h, int(old_h * 0.95))

                obj["centroid"] = (cx, cy)
                # CONFIRMED_STOP: ใช้ขนาด motion จริง แต่ไม่อนุญาตให้ใหญ่เกิน confirmed_shape
                # ป้องกันมือ/วัตถุอื่นมา merge แล้วทำให้กรอบขยาย
                if obj["state"] == "CONFIRMED_STOP" and "confirmed_shape" in obj:
                    ccw, cch = obj["confirmed_shape"]
                    obj["shape"] = (min(w, ccw), min(h, cch))
                else:
                    obj["shape"] = (w, h)
                # [BUG FIX 1] reset ghost counter เมื่อวัตถุกลับมาเจอแล้ว
                obj["ghost_frames"] = 0

                # Shape stability check
                # CONFIRMED_STOP: ไม่แตะ state เลย
                # SHAPE_CONFIRMED: lock state ไว้ แต่ shape ยัง track ตาม motion จริง
                #   (ไม่ lock shape เพื่อให้กรอบสะท้อนขนาดวัตถุจริงเสมอ)
                # MOVING/DETECTING: วัด centroid stability แทน area
                #   noise ข้างใน object ทำให้ box size ขยับแต่ centroid ยังนิ่ง
                if obj["state"] == "CONFIRMED_STOP":
                    pass
                elif obj["state"] == "SHAPE_CONFIRMED":
                    # lock state ไว้ — shape อัปเดตตาม motion จริงแล้วข้างบน
                    pass
                else:
                    centroid_dist = math.hypot(cx - px, cy - py)
                    if centroid_dist <= CENTROID_STABLE_DIST:
                        obj["shape_stable_count"] = obj.get("shape_stable_count", 0) + 1
                    else:
                        obj["shape_stable_count"] = 0
                        obj["state"] = "DETECTING"

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
                    "still_start": None,
                    "first_seen": current_time,
                    "shape_stable_count": 0,
                    "shape_confirmed_time": None,
                    "ghost_frames": 0,
                }
                self.next_id += 1

        # [BUG FIX 1] จัดการวัตถุที่หายไปจาก detection frame นี้
        for obj_id in available:
            if obj_id in matched_ids:
                continue  # วัตถุยังอยู่ใน frame → จัดการแล้วข้างบน

            obj = self.objects[obj_id]

            # วัตถุที่เพิ่งเกิดใหม่ไม่กี่ frame → ลบทิ้งทันที ไม่ต้องรอ
            if obj["state"] == "MOVING" and (current_time - obj["first_seen"]) < 0.5:
                continue  # ลบออก (ไม่ใส่ใน new_objects)

            # [BUG FIX: กรอบ CONFIRMED ค้าง]
            # CONFIRMED_STOP: ของที่ confirm แล้วก็ต้องนับ ghost frame ด้วย
            # เดิม: เก็บค้างไว้ตลอด → main.is_really_gone() เห็น ghost_frames=0
            #       เสมอ → กรอบเขียวค้างจนกว่าจะ force-reset โดย hold timeout
            # ใหม่: นับ ghost frame เหมือน object ทั่วไป (แต่ tolerance สูงกว่า)
            #       - ยังอยู่ใน tolerance → เก็บไว้ + ตั้ง ghost_frames > 0
            #         เพื่อให้ main.py รู้ว่า "ของกำลังหาย" (กรอบหยุดวาด/นับ gone)
            #       - เกิน tolerance → ลบทิ้ง ของออกจาก ROI จริง
            if obj["state"] == "CONFIRMED_STOP":
                ghost_count = obj.get("ghost_frames", 0) + 1
                if ghost_count > CONFIRMED_GHOST_FRAME_TOLERANCE:
                    # ของ confirmed หายจาก ROI นานพอ → ลบทิ้ง
                    # (ไม่ใส่ใน new_objects → main.py จะ reset กลับ IDLE)
                    print(
                        f"[Tracker] 👋 obj#{obj_id} (CONFIRMED) "
                        f"หายจาก ROI ครบ {ghost_count} frame → ลบทิ้ง"
                    )
                    continue
                obj["ghost_frames"] = ghost_count
                new_objects[obj_id] = obj
                continue

            # [BUG FIX 1 - หัวใจหลัก]
            # วัตถุทั่วไปที่หายออกจาก ROI: นับ ghost frame
            # ถ้าเกิน GHOST_FRAME_TOLERANCE → ลบทิ้งเลย ไม่มีกรอบค้าง
            ghost_count = obj.get("ghost_frames", 0) + 1
            if ghost_count > GHOST_FRAME_TOLERANCE:
                # ลบออก — กรอบจะหายไปพร้อมของ
                continue

            # ยังอยู่ในช่วง tolerance → เก็บไว้ชั่วคราวแต่ไม่สร้าง WAITING state
            obj["ghost_frames"] = ghost_count
            obj["state"] = "DETECTING"  # ลดความสำคัญลง ไม่ใช่ WAITING อีกต่อไป
            new_objects[obj_id] = obj

        self.objects = new_objects
        return self.objects

    def clear_all(self):
        self.objects.clear()
        self._confirmed_ids.clear()
        # ✅ ไม่ reset next_id กลับเป็น 1
        # เพราะถ้า reset แล้ว object ใหม่จะได้ id ซ้ำกับที่ sm.land_obj_id จำอยู่
        # ทำให้ของชิ้นใหม่ถูก skip โดยไม่ตั้งใจ