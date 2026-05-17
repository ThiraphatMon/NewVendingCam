import math
import time
from config import CONFIRM_TIME, STILL_DIST, FRAME_W, FRAME_H

EDGE_MARGIN = 5  # pixel margin สำหรับตัดสิน edge kill

# จำนวน frame ติดต่อกันที่ shape ต้องนิ่งพอ จึงถือว่า "ยืนยันรูปร่าง" ได้
SHAPE_STABLE_FRAMES = 5
SHAPE_SIZE_TOLERANCE = 0.20  # ขนาด w*h เปลี่ยนได้ไม่เกิน 20% จึงถือว่า stable


def group_close_boxes(boxes, max_dist=50):
    if not boxes:
        return []
    rects = [[b[0], b[1], b[0] + b[2], b[1] + b[3]] for b in boxes]

    def box_dist(r1, r2):
        dx = max(0, max(r1[0], r2[0]) - min(r1[2], r2[2]))
        dy = max(0, max(r1[1], r2[1]) - min(r1[3], r2[3]))
        return math.hypot(dx, dy)

    groups = []
    for r in rects:
        matched = [
            i
            for i, g in enumerate(groups)
            if any(box_dist(r, gr) < max_dist for gr in g)
        ]
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

                # ── [CHANGE 1] Shape stability check ────────────────────────────
                # ไม่ใช้ STILL_DIST อีกต่อไปในการตัดสิน CONFIRMED_STOP
                # ใช้การนับ frame ที่ขนาด bounding box เสถียรแทน
                if obj["state"] != "CONFIRMED_STOP":
                    prev_area = old_w * old_h
                    curr_area = w * h
                    area_ratio = abs(curr_area - prev_area) / max(1, prev_area)
                    if area_ratio <= SHAPE_SIZE_TOLERANCE:
                        obj["shape_stable_count"] = obj.get("shape_stable_count", 0) + 1
                    else:
                        obj["shape_stable_count"] = 0
                        if (
                            obj.get("shape_confirmed_time") is None
                        ):  # ยังไม่เคย confirm → reset ได้
                            obj["state"] = "DETECTING"
                        # ถ้า confirm แล้ว ไม่ถอยกลับเป็น DETECTING แม้ noise จะทำให้ shape เปลี่ยนชั่วคราว

                    if obj["shape_stable_count"] >= SHAPE_STABLE_FRAMES:
                        if obj.get("shape_confirmed_time") is None:
                            obj["shape_confirmed_time"] = current_time
                        # ไม่ reset shape_confirmed_time ถ้า confirm แล้ว
                        obj["state"] = "SHAPE_CONFIRMED"
                    else:
                        obj["state"] = "DETECTING"
                # ────────────────────────────────────────────────────────────────

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
                }
                self.next_id += 1

        for obj_id in available:
            if obj_id in matched_ids:
                continue
            obj = self.objects[obj_id]
            if obj["state"] == "MOVING" and (current_time - obj["first_seen"]) < 0.5:
                continue

            # Edge kill
            cx, cy = obj["centroid"]
            w, h = obj["shape"]
            at_edge = (
                cx - w // 2 <= EDGE_MARGIN
                or cx + w // 2 >= FRAME_W - EDGE_MARGIN
                or cy - h // 2 <= EDGE_MARGIN
                or cy + h // 2 >= FRAME_H - EDGE_MARGIN
            )
            if at_edge and obj["state"] != "CONFIRMED_STOP":
                continue

            # วัตถุหายออกจาก frame ชั่วคราว (noise) → เข้า WAITING countdown
            if obj["state"] != "CONFIRMED_STOP":
                if obj["still_start"] is None:
                    obj["still_start"] = current_time
                elapsed = current_time - obj["still_start"]
                if elapsed >= CONFIRM_TIME:
                    obj["state"] = "CONFIRMED_STOP"
                else:
                    obj["state"] = f"WAITING ({int(CONFIRM_TIME-elapsed)}s)"
            new_objects[obj_id] = obj

        self.objects = new_objects
        return self.objects

    def clear_all(self):
        self.objects.clear()
        self.next_id = 1
