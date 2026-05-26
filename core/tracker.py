import math
import time
from config import CONFIRM_TIME, FRAME_W, FRAME_H

EDGE_MARGIN = 5  # pixel margin สำหรับตัดสิน edge kill

# จำนวน frame ติดต่อกันที่ shape ต้องนิ่งพอ จึงถือว่า "ยืนยันรูปร่าง" ได้
SHAPE_STABLE_FRAMES = 5
SHAPE_SIZE_TOLERANCE = 0.20  # ขนาด w*h เปลี่ยนได้ไม่เกิน 20% จึงถือว่า stable

# [BUG FIX 1] จำนวน frame ที่วัตถุหายไปแล้วยังคงรอก่อนลบ
# ตั้งเป็น 0 = ลบทันทีที่หายออกจาก ROI (ไม่มีกรอบค้าง)
# ตั้งเป็น 2-3 = tolerance เล็กน้อยเผื่อ noise กระพริบ 1-2 frame
GHOST_FRAME_TOLERANCE = 2

# [FIX: CONFIRMED BOX EXPANSION]
# threshold การขยายของกรอบ confirmed object (เทียบกับ confirmed_shape)
# ถ้ากรอบขยายเกินนี้ → สงสัยว่ามีของใหม่มาเกาะ
CONFIRMED_EXPAND_RATIO = 1.35  # กรอบขยายเกิน 35% → สงสัย
# ระยะเวลา (วินาที) ที่กรอบต้องขยายค้างอยู่ก่อนจะตัดสินว่าเป็นของใหม่
# ใช้ค่าเดียวกับ CONFIRM_TIME เพื่อให้ consistent กับ logic ปกติ
CONFIRMED_EXPAND_CONFIRM_TIME = CONFIRM_TIME


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
        บันทึก confirmed_shape ไว้เป็น baseline สำหรับตรวจการขยาย
        """
        if obj_id in self.objects:
            obj = self.objects[obj_id]
            obj["confirmed_shape"] = obj["shape"]  # snapshot ณ ตอน confirm
            obj["expand_since"] = None  # เริ่มต้นยังไม่ขยาย
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

                if (w * h) / max(1, old_w * old_h) < 0.75 and dist < 30:
                    cx, cy, w, h, dist = px, py, old_w, old_h, 0
                else:
                    w = max(w, int(old_w * 0.95))
                    h = max(h, int(old_h * 0.95))

                obj["centroid"] = (cx, cy)
                obj["shape"] = (w, h)
                # [BUG FIX 1] reset ghost counter เมื่อวัตถุกลับมาเจอแล้ว
                obj["ghost_frames"] = 0

                # [FIX: CONFIRMED BOX EXPANSION]
                # ถ้า object นี้ confirmed แล้ว → ตรวจดูว่ากรอบขยายผิดปกติหรือไม่
                if best_id in self._confirmed_ids and "confirmed_shape" in obj:
                    cw, ch = obj["confirmed_shape"]
                    confirmed_area = cw * ch
                    current_area = w * h
                    expand_ratio = current_area / max(1, confirmed_area)

                    if expand_ratio >= CONFIRMED_EXPAND_RATIO:
                        # กรอบขยายผิดปกติ — เริ่มจับเวลา
                        if obj["expand_since"] is None:
                            obj["expand_since"] = current_time
                            print(
                                f"[Tracker] ⚠️ obj#{best_id} กรอบขยาย "
                                f"{expand_ratio:.2f}x → เริ่มจับเวลา"
                            )
                        else:
                            expand_duration = current_time - obj["expand_since"]
                            if expand_duration >= CONFIRMED_EXPAND_CONFIRM_TIME:
                                # ขยายค้างนานพอ → ถือว่ามีของใหม่ฝังอยู่ในกรอบ
                                # สร้าง object ใหม่ตรงตำแหน่ง centroid ปัจจุบัน
                                new_id = self.next_id
                                self.next_id += 1
                                # ประมาณขนาดของใหม่ = ส่วนที่เกินจาก confirmed_shape
                                # ใช้ขนาด confirmed เดิมเป็น fallback
                                new_w = max(cw, w - cw)
                                new_h = max(ch, h - ch)
                                new_objects[new_id] = {
                                    "centroid": (cx, cy),
                                    "shape": (new_w, new_h),
                                    "state": "SHAPE_CONFIRMED",
                                    "still_start": None,
                                    "first_seen": current_time,
                                    "shape_stable_count": SHAPE_STABLE_FRAMES,
                                    "shape_confirmed_time": current_time
                                    - CONFIRMED_EXPAND_CONFIRM_TIME,
                                    "ghost_frames": 0,
                                }
                                print(
                                    f"[Tracker] 🆕 obj#{new_id} เกิดใหม่จากการขยายกรอบ "
                                    f"ของ obj#{best_id} (expand={expand_ratio:.2f}x "
                                    f"นาน {expand_duration:.1f}s)"
                                )
                                # reset expand timer ของชิ้นเดิมเพื่อไม่ trigger ซ้ำ
                                obj["expand_since"] = None
                                obj["confirmed_shape"] = obj["shape"]
                    else:
                        # กรอบหดกลับมาปกติแล้ว → reset timer
                        if obj["expand_since"] is not None:
                            obj["expand_since"] = None

                # Shape stability check
                if obj["state"] != "CONFIRMED_STOP":
                    prev_area = old_w * old_h
                    curr_area = w * h
                    area_ratio = abs(curr_area - prev_area) / max(1, prev_area)
                    if area_ratio <= SHAPE_SIZE_TOLERANCE:
                        obj["shape_stable_count"] = obj.get("shape_stable_count", 0) + 1
                    else:
                        obj["shape_stable_count"] = 0
                        if obj.get("shape_confirmed_time") is None:
                            obj["state"] = "DETECTING"

                    if obj["shape_stable_count"] >= SHAPE_STABLE_FRAMES:
                        if obj.get("shape_confirmed_time") is None:
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

            # CONFIRMED_STOP: วัตถุที่ confirm แล้ว → อนุญาตให้ค้างไว้
            # เพราะ state_machine กำลังจัดการอยู่ (จะถูกลบโดย do_reset())
            if obj["state"] == "CONFIRMED_STOP":
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
