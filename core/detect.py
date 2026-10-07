"""
core/detect.py — foreground-mask building + blob detection

สร้าง binary motion mask จากภาพ diff แล้วหา bounding boxes ของ blob

Pipeline: threshold → [S22] ตัดจุดที่เป็นแค่แสง/เงา (texture) → OPEN (ลบ noise จุดเล็ก) → DILATE (เชื่อม mask ชิ้นเดียวที่ขาด)
          → contour_boxes (หา bounding box) → group_close_boxes (รวมก้อนที่แตกของชิ้นเดียว)
  - OPEN ลบ noise จุดเดียวออกก่อน
  - DILATE อยู่ท้ายสุด: ขยายเฉพาะมวลของจริงที่เหลือ (ถ้า dilate ก่อน noise จะโดนขยายตาม)
    ทำให้ mask ของวัตถุชิ้นเดียวที่ขาดเป็นหย่อม ๆ เชื่อมเป็นก้อนตัน → contour เดียว
"""

import math
import cv2
import numpy as np


def light_only_mask(bg, cur, win=7, ncc_thr=0.6, flat_var=4.0):
    """[S22 SHADOW] จุดที่การเปลี่ยนเป็นแค่แสง/เงา (bool array ขนาดเท่า bg)

    แสง/เงา/การปรับแสงของกล้อง เปลี่ยนแค่ความสว่าง ลวดลายพื้นผิวยังเหมือนเดิม — ของที่ตกลงมาทับลวดลาย
    → local NCC (box filter ขนาด win) ระหว่างพื้นหลังกับเฟรมปัจจุบันสูง = ลายเดิม = แค่แสง
    → ไม่มีลายทั้งคู่ (variance < flat_var) ก็ถือเป็นแค่แสง (พื้นเรียบสว่าง/มืดลง)
    bg, cur : grayscale float32 (ส่วนเดียวกันของภาพ เช่น bounding box ของ ROI)"""
    a = bg.astype(np.float32, copy=False)
    b = cur.astype(np.float32, copy=False)
    k = (win, win)
    ma, mb = cv2.blur(a, k), cv2.blur(b, k)
    va = cv2.blur(a * a, k) - ma * ma
    vb = cv2.blur(b * b, k) - mb * mb
    cab = cv2.blur(a * b, k) - ma * mb
    ncc = cab / np.sqrt(np.maximum(va * vb, 1e-3))
    return (ncc > ncc_thr) | ((va < flat_var) & (vb < flat_var))


def build_fgmask(diff, mot_thresh, open_ksize=5, dilate_ksize=5, dilate_iter=2, shadow=None):
    """
    สร้าง binary motion mask จากภาพ diff (absdiff ระหว่างเฟรมกับ background)

    open_ksize   : ขนาด kernel ของ MORPH_OPEN — ลบ noise จุดเล็ก ๆ (0=ปิด)
    dilate_ksize : ขนาด kernel ของ MORPH_DILATE — เชื่อม mask ชิ้นเดียวที่ขาด (0=ปิด)
    dilate_iter  : จำนวนรอบที่ทำ DILATE (0=ปิด)
    shadow       : None = ไม่กรองแสง/เงา (SHADOW_FILTER=off)
                   หรือ (bg_crop, cur_crop, (x, y, w, h), win, ncc_thr, flat_var)
                   → จุดในกล่อง (x, y, w, h) ที่เป็นแค่แสง/เงา ถูกตัดออกก่อน morphology
                   (bg_crop = พื้นหลังเดียวกับที่ใช้คำนวณ diff, ตัดเฉพาะกล่องนั้น)
    """
    fgmask = np.where(diff > mot_thresh, np.uint8(255), np.uint8(0))

    if shadow is not None:
        bg_crop, cur_crop, (x, y, w, h), win, ncc_thr, flat_var = shadow
        sub = fgmask[y:y + h, x:x + w].copy()
        if w > 0 and h > 0:
            sub[light_only_mask(bg_crop, cur_crop, win, ncc_thr, flat_var)] = 0
        # นอกกล่อง ROI ไม่ได้กรอง (และผู้เรียกตัดทิ้งด้วย roi_mask อยู่แล้ว) → ล้างเป็น 0
        # ไม่งั้นเงานอกกรอบถูก DILATE ล้นเข้าขอบ ROI เป็นแนวยาว (~4 px รอบกรอบ)
        fgmask[:] = 0
        fgmask[y:y + h, x:x + w] = sub

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


def drop_large_boxes(boxes, roi_areas, max_ratio):
    """ตัดกล่องที่ใหญ่เกิน max_ratio ของพื้นที่ ROI area ใดก็ได้ (ใช้ตอนเจอ env change)
    ก้อนใหญ่ = แสง/bg เปลี่ยน ไม่ส่งเข้า tracker แต่ก้อนเล็กที่เหลือยังส่งต่อตามปกติ"""
    return [
        (bx, by, bw, bh)
        for bx, by, bw, bh in boxes
        if not any(bw * bh > a["area_px"] * max_ratio for a in roi_areas)
    ]
