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
# เพิ่มเป็น 60 frames (~2.4 วินาที ที่ 25fps)
# ให้ object CONFIRMED_STOP ทน ghost ได้นานพอที่มือปัดผ่านจะไม่ทำให้ถูกลบ
CONFIRMED_GHOST_FRAME_TOLERANCE = 60

# ── [BUG FIX 2] Confirmed item ครองพื้นที่ของตัวเอง (anchored region) ──────────
# detection ใดที่ overlap กับ "กรอบ confirmed เดิม" ถือว่าเป็น "ของชิ้นเดิมที่ถูกบัง"
# (มือปัดผ่าน / มือเข้ามาบังชั่วคราว) → ไม่สร้าง object id ใหม่ และ confirmed item
# ถูกตรึงไว้ที่ตำแหน่ง + ขนาดเดิม (ไม่ดริฟต์ตามมือ ไม่บวมขึ้น ไม่ถูก handoff ไป id ใหม่)
# pad เผื่อขอบรอบกรอบ confirmed ให้ครอบ blob ที่คาบเกี่ยวเล็กน้อยได้
CONFIRMED_CLAIM_PAD = 10  # pixel

# exception (ของตกทับ): ถ้ามี "มวลส่วนเกิน" ทับกรอบ confirmed โดยมีพื้นที่ใหญ่กว่า
# กรอบ confirmed เกิน OCC_EXCESS_RATIO เท่า และ "นิ่งอยู่บริเวณนั้น" ครบ CONFIRM_TIME
# → ถือว่าเป็นของชิ้นใหม่ที่ตกมาทับ (ไม่ใช่แค่มือปัดผ่าน) → spawn object ใหม่ให้ capture ได้
# ต้องให้บริเวณนั้น "ว่างจากมวลส่วนเกิน" สักเฟรมก่อน จึงจะ arm ให้ spawn รอบใหม่ได้
# (กัน spawn ซ้ำรัว ๆ ระหว่างที่มือ/ของชิ้นใหม่ยังค้างอยู่)
OCC_EXCESS_RATIO = 1.5


def _box_rect(box):
    """box = (cx, cy, w, h) → (x1, y1, x2, y2)"""
    cx, cy, w, h = box
    return (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)


def _centroid_rect(centroid, shape, pad=0.0):
    """centroid=(cx,cy), shape=(w,h) → (x1,y1,x2,y2) เผื่อ pad รอบด้าน"""
    cx, cy = centroid
    w, h = shape
    return (
        cx - w / 2.0 - pad,
        cy - h / 2.0 - pad,
        cx + w / 2.0 + pad,
        cy + h / 2.0 + pad,
    )


def _rects_overlap(a, b):
    """rect = (x1,y1,x2,y2)"""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _union_box(boxes, idxs):
    """รวม bounding box ของ detected boxes (centroid form) ตาม index ที่ระบุ → (cx,cy,w,h)"""
    x1 = min(boxes[i][0] - boxes[i][2] / 2.0 for i in idxs)
    y1 = min(boxes[i][1] - boxes[i][3] / 2.0 for i in idxs)
    x2 = max(boxes[i][0] + boxes[i][2] / 2.0 for i in idxs)
    y2 = max(boxes[i][1] + boxes[i][3] / 2.0 for i in idxs)
    w = x2 - x1
    h = y2 - y1
    return (int(x1 + w / 2.0), int(y1 + h / 2.0), int(w), int(h))


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
        snapshot centroid + shape เป็น baseline สำหรับตรึงกรอบ (anchor)
        และตั้ง state เป็น CONFIRMED_STOP
        """
        if obj_id in self.objects:
            obj = self.objects[obj_id]
            # snapshot shape และ centroid ณ ตอน confirm เป็น baseline
            # ใช้ตรึงกรอบไม่ให้ขยับ/ขยายเกินขนาดของจริง
            obj["confirmed_shape"] = obj["shape"]
            obj["confirmed_centroid"] = obj["centroid"]
            obj["state"] = "CONFIRMED_STOP"
            # occlusion-spawn arming (สำหรับ exception ของตกทับ)
            obj["occ_since"] = None
            obj["occ_centroid"] = None
            obj["occ_armed"] = True
            self._confirmed_ids.add(obj_id)

    def update(self, detected_boxes):
        new_objects = {}
        current_time = time.time()
        matched_ids = set()
        consumed = set()  # index ของ detected box ที่ถูก confirmed region เคลม

        # ── Phase 0 [BUG FIX 2]: confirmed item ครองพื้นที่ของตัวเอง ──────────
        # detection ที่ overlap กรอบ confirmed เดิม = "ของเดิมที่ถูกบัง/ปัดผ่าน"
        #   → confirmed item ถูกตรึงไว้ที่ตำแหน่ง/ขนาดเดิม (ไม่ดริฟต์ ไม่บวม ไม่ถูกลืม)
        #   → box เหล่านั้นถูก consume ไม่ให้ไปสร้าง id ใหม่ใน Phase 1
        # exception: ถ้ามวลส่วนเกินทับอยู่ "นิ่ง" ครบ CONFIRM_TIME → spawn ของชิ้นใหม่
        for obj_id, obj in self.objects.items():
            if obj.get("state") != "CONFIRMED_STOP":
                continue
            if "confirmed_centroid" not in obj or "confirmed_shape" not in obj:
                continue

            crect = _centroid_rect(
                obj["confirmed_centroid"], obj["confirmed_shape"], CONFIRMED_CLAIM_PAD
            )
            overlapping = [
                i
                for i, b in enumerate(detected_boxes)
                if _rects_overlap(_box_rect(b), crect)
            ]

            if not overlapping:
                # ไม่มี detection ทับ region เลย → ของอาจถูกหยิบออก/ถูกบังหมด
                # ไม่ mark seen ที่นี่ → ปล่อยให้ disappearance loop ด้านล่างนับ ghost
                continue

            # ── ของเดิมยังอยู่ (มี blob ทับ region) → ตรึงไว้ที่ค่าที่ confirm ไว้ ──
            obj["centroid"] = obj["confirmed_centroid"]
            obj["shape"] = obj["confirmed_shape"]
            obj["ghost_frames"] = 0
            matched_ids.add(obj_id)
            consumed.update(overlapping)

            # ── exception: ตรวจ "มวลส่วนเกิน" ที่ทับ confirmed item ───────────
            union = _union_box(detected_boxes, overlapping)
            ucx, ucy, uw, uh = union
            confirmed_area = max(
                1, obj["confirmed_shape"][0] * obj["confirmed_shape"][1]
            )
            excess_present = (uw * uh) > confirmed_area * OCC_EXCESS_RATIO

            if not excess_present:
                # ไม่มีมวลส่วนเกินมีนัยสำคัญ (แค่ noise บนของเดิม) → เคลียร์ + arm ใหม่
                obj["occ_since"] = None
                obj["occ_centroid"] = None
                obj["occ_armed"] = True
            else:
                # มีมวลใหญ่กว่ากรอบ confirmed มากพอ (มือ/ของใหม่มาทับ)
                prev = obj.get("occ_centroid")
                stable = (
                    prev is not None
                    and math.hypot(ucx - prev[0], ucy - prev[1])
                    <= CENTROID_STABLE_DIST
                )
                if stable:
                    obj["occ_centroid"] = (ucx, ucy)
                    if (
                        obj.get("occ_armed", True)
                        and obj.get("occ_since") is not None
                        and (current_time - obj["occ_since"]) >= CONFIRM_TIME
                    ):
                        # มวลส่วนเกินนิ่งครบ CONFIRM_TIME → ของชิ้นใหม่ตกทับ (ไม่ใช่ปัดผ่าน)
                        # spawn object ใหม่ + back-date เวลาให้ main capture ได้ทันทีเฟรมนี้
                        # (เงื่อนไข persistence ถูกการันตีด้วย occ timer ไปแล้ว)
                        new_objects[self.next_id] = {
                            "centroid": (ucx, ucy),
                            "shape": (uw, uh),
                            "state": "SHAPE_CONFIRMED",
                            "still_start": None,
                            "first_seen": current_time - (CONFIRM_TIME + 2.0),
                            "shape_stable_count": SHAPE_STABLE_FRAMES,
                            "shape_confirmed_time": current_time - (CONFIRM_TIME + 1.0),
                            "ghost_frames": 0,
                        }
                        print(
                            f"[Tracker] ➕ มวลส่วนเกินทับ obj#{obj_id} นิ่งครบ "
                            f"{CONFIRM_TIME}s → spawn ของชิ้นใหม่ id={self.next_id} "
                            f"(ของตกทับ)"
                        )
                        self.next_id += 1
                        # disarm จนกว่าบริเวณนั้นจะว่างจากมวลส่วนเกินสักเฟรม
                        obj["occ_armed"] = False
                        obj["occ_since"] = None
                else:
                    # เพิ่งโผล่ / ยังขยับอยู่ (ลักษณะมือปัดผ่าน) → (re)start ตัวจับเวลา
                    obj["occ_since"] = current_time
                    obj["occ_centroid"] = (ucx, ucy)

            new_objects[obj_id] = obj

        # ── Phase 1: matching ปกติ เฉพาะ object ที่ "ไม่ใช่ confirmed" ─────────
        available = [
            oid
            for oid in self.objects.keys()
            if oid not in matched_ids
            and self.objects[oid].get("state") != "CONFIRMED_STOP"
        ]

        for idx, box in enumerate(detected_boxes):
            if idx in consumed:
                continue  # ถูก confirmed region เคลมไปแล้ว
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
                    # motion หดแปบเดียว → คืน shape เดิม ป้องกัน noise กระพริบ
                    cx, cy, w, h, dist = px, py, old_w, old_h, 0
                else:
                    # ไม่ให้หดเร็วเกิน (smoothing ปกติ)
                    w = max(w, int(old_w * 0.95))
                    h = max(h, int(old_h * 0.95))

                obj["centroid"] = (cx, cy)
                obj["shape"] = (w, h)
                obj["ghost_frames"] = 0

                # Shape stability check
                if obj["state"] == "SHAPE_CONFIRMED":
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

        # ── disappearance: object เดิมที่ไม่ถูก match ในเฟรมนี้ ───────────────
        for obj_id in self.objects.keys():
            if obj_id in matched_ids or obj_id in new_objects:
                continue

            obj = self.objects[obj_id]

            # วัตถุที่เพิ่งเกิดใหม่ไม่กี่ frame → ลบทิ้งทันที ไม่ต้องรอ
            if obj["state"] == "MOVING" and (current_time - obj["first_seen"]) < 0.5:
                continue  # ลบออก (ไม่ใส่ใน new_objects)

            # [BUG FIX: กรอบ CONFIRMED ค้าง]
            # CONFIRMED_STOP ที่ไม่มี blob ทับ region เลยเฟรมนี้ → นับ ghost frame
            #   - ยังไม่เกิน tolerance → เก็บไว้ + ghost_frames > 0 (กรอบหยุดวาด/นับ gone)
            #   - เกิน tolerance → ลบทิ้ง (ของออกจาก ROI จริง)
            if obj["state"] == "CONFIRMED_STOP":
                ghost_count = obj.get("ghost_frames", 0) + 1
                if ghost_count > CONFIRMED_GHOST_FRAME_TOLERANCE:
                    print(
                        f"[Tracker] 👋 obj#{obj_id} (CONFIRMED) "
                        f"หายจาก ROI ครบ {ghost_count} frame → ลบทิ้ง"
                    )
                    continue
                obj["ghost_frames"] = ghost_count
                new_objects[obj_id] = obj
                continue

            # วัตถุทั่วไปที่หายออกจาก ROI: นับ ghost frame
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
        self._confirmed_ids.clear()
        # ✅ ไม่ reset next_id กลับเป็น 1
        # เพราะถ้า reset แล้ว object ใหม่จะได้ id ซ้ำกับที่ sm.land_obj_id จำอยู่
        # ทำให้ของชิ้นใหม่ถูก skip โดยไม่ตั้งใจ