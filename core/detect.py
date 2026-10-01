"""
core/detect.py — foreground-mask building + blob detection

สร้าง binary motion mask จากภาพ diff แล้วหา bounding boxes ของ blob

Pipeline: threshold → OPEN (ลบ noise จุดเล็ก) → DILATE (เชื่อม mask ชิ้นเดียวที่ขาด)
          → contour_boxes (หา bounding box) → group_close_boxes (รวมก้อนที่แตกของชิ้นเดียว)
  - OPEN ลบ noise จุดเดียวออกก่อน
  - DILATE อยู่ท้ายสุด: ขยายเฉพาะมวลของจริงที่เหลือ (ถ้า dilate ก่อน noise จะโดนขยายตาม)
    ทำให้ mask ของวัตถุชิ้นเดียวที่ขาดเป็นหย่อม ๆ เชื่อมเป็นก้อนตัน → contour เดียว
"""

import math
import cv2
import numpy as np


def build_fgmask(diff, mot_thresh, open_ksize=5, dilate_ksize=5, dilate_iter=2):
    """
    สร้าง binary motion mask จากภาพ diff (absdiff ระหว่างเฟรมกับ background)

    open_ksize   : ขนาด kernel ของ MORPH_OPEN — ลบ noise จุดเล็ก ๆ (0=ปิด)
    dilate_ksize : ขนาด kernel ของ MORPH_DILATE — เชื่อม mask ชิ้นเดียวที่ขาด (0=ปิด)
    dilate_iter  : จำนวนรอบที่ทำ DILATE (0=ปิด)
    """
    fgmask = np.where(diff > mot_thresh, np.uint8(255), np.uint8(0))

    if open_ksize and open_ksize >= 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_ksize, open_ksize))
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, k)
    if dilate_ksize and dilate_ksize >= 1 and dilate_iter and dilate_iter >= 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_ksize, dilate_ksize))
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_DILATE, k, iterations=dilate_iter)
    return fgmask


def contour_boxes(fgmask, min_area):
    """
    หา bounding boxes จาก contours โดยกรอง contour ที่พื้นที่ <= min_area (noise เล็กเกิน)
    คืน list ของ (x, y, w, h)
    """
    contours, _ = cv2.findContours(
        fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    boxes = []
    for c in contours:
        if cv2.contourArea(c) <= min_area:
            continue
        boxes.append(cv2.boundingRect(c))
    return boxes


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
