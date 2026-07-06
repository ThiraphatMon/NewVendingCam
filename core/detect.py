"""
core/detect.py — foreground-mask building + blob separation

แยกตรรกะการสร้าง motion mask และการ "แยก blob ที่ติดกัน" ออกมาเป็นโมดูลเดี่ยว
เพื่อให้ปรับความแม่นยำได้ง่ายและทดสอบได้

หลักการสำคัญ (ทำไมถึงแม่นขึ้น):
  - เดิมใช้ DILATE 5x5 ซ้ำ 2 รอบ → ทุก blob ขยายออก ~8px รอบด้าน ทำให้
    (1) กรอบใหญ่กว่าของจริงมาก  (2) ของ 2 ชิ้นที่อยู่ใกล้กันถูกรวมเป็นก้อนเดียว
    ตั้งแต่ก่อนหา contour → แยกกันไม่ได้อีกเลย
  - ใหม่: OPEN เล็ก (ลบ noise จุดเดียว) + CLOSE เล็ก (อุดรูในชิ้นเดิมโดยไม่บวมออก)
    → กรอบแนบกับของจริง และของที่อยู่ใกล้กันยังแยกกันอยู่
  - ถ้า blob ก้อนเดียวมีของหลายชิ้นติดกันจริง → ใช้ distance-transform + watershed
    แยกกลับออกเป็นหลายกล่องตามยอด (peak) ของแต่ละชิ้น
"""

import cv2
import numpy as np
import math


def build_fgmask(diff, mot_thresh, open_ksize=3, close_ksize=3, median_ksize=0):
    """
    สร้าง binary motion mask จากภาพ diff (absdiff ระหว่างเฟรมกับ background)

    median_ksize : ขนาด median blur (เลขคี่) ลบ speckle noise ก่อน morphology
                   สำคัญตอน mot_thresh ต่ำ ๆ — ลบจุด noise กระจายโดยไม่กินของตัน
    open_ksize   : ขนาด kernel ของ MORPH_OPEN — ลบ noise จุดเล็ก ๆ
    close_ksize  : ขนาด kernel ของ MORPH_CLOSE — อุดรูภายในชิ้นเดิมโดยไม่บวมออก
    """
    fgmask = np.where(diff > mot_thresh, np.uint8(255), np.uint8(0))

    if median_ksize and median_ksize >= 3:
        k = median_ksize if median_ksize % 2 == 1 else median_ksize + 1
        fgmask = cv2.medianBlur(fgmask, k)
    if open_ksize and open_ksize >= 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_ksize, open_ksize))
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, k)
    if close_ksize and close_ksize >= 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_ksize, close_ksize))
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_CLOSE, k)
    return fgmask


def contour_boxes(fgmask, min_area, min_solidity=0.0):
    """
    หา bounding boxes จาก contours โดยกรอง noise:
      - พื้นที่ contour <= min_area  → เล็กเกิน = noise
      - fill ratio (จำนวน pixel ขาวจริงในกรอบ / พื้นที่กรอบ) < min_solidity → กระจาย = noise
        ของจริงตัน (fill สูง ~0.5+) / noise กระจายเป็นจุด-เส้น-วง (fill ต่ำ) → ตัดทิ้ง
        * ใช้ fill ratio ไม่ใช่ contourArea เพราะ RETR_EXTERNAL คิดพื้นที่ทั้งวง
          ทำให้ blob กลวง/โปร่งดู "ตัน" หลอก ๆ
    คืน list ของ (x, y, w, h)
    """
    contours, _ = cv2.findContours(
        fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    boxes = []
    for c in contours:
        if cv2.contourArea(c) <= min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if min_solidity > 0.0:
            roi = fgmask[y:y + h, x:x + w]
            fill = cv2.countNonZero(roi) / max(1, w * h)
            if fill < min_solidity:
                continue
        boxes.append((x, y, w, h))
    return boxes


# ─────────────────────────────────────────────────────────────────────────────
# Displacement guard — กันการนับของที่ "นับไปแล้ว" ซ้ำ เมื่อมันถูกชนขยับ
# ─────────────────────────────────────────────────────────────────────────────
def region_activity(diff, cx, cy, w, h, pad=0):
    """
    ค่าเฉลี่ยความต่าง (motion) ในกรอบรอบจุด (cx, cy)
    สูง = บริเวณนั้นมีการเปลี่ยนแปลง (ของเพิ่งออกจากจุดนี้ / มีของมาทับ)
    ต่ำ (~0) = ตรงกับ background = ของยังอยู่ที่เดิม (หลังถูกกลืนเข้า bg แล้ว)
    """
    H, W = diff.shape[:2]
    x1 = max(0, int(cx - w / 2) - pad)
    y1 = max(0, int(cy - h / 2) - pad)
    x2 = min(W, int(cx + w / 2) + pad)
    y2 = min(H, int(cy + h / 2) + pad)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return float(diff[y1:y2, x1:x2].mean())


def _boxes_overlap_ratio(a, b):
    """สัดส่วนพื้นที่ทับกันเทียบกับกล่องที่เล็กกว่า (a, b = (cx,cy,w,h))"""
    ax1, ay1 = a[0] - a[2] / 2, a[1] - a[3] / 2
    ax2, ay2 = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2
    bx2, by2 = b[0] + b[2] / 2, b[1] + b[3] / 2
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    small = max(1.0, min(a[2] * a[3], b[2] * b[3]))
    return inter / small


def classify_landing(
    landing, anchors, diff, vacate_mean_diff, displace_radius, stack_overlap=0.6
):
    """
    ตัดสินว่า blob ที่เพิ่งลงจอด (landing = (cx,cy,w,h)) คือ:
      - ('new', None)            → ของชิ้นใหม่จริง → นับเพิ่ม
      - ('displaced', anchor_id) → ของที่นับไปแล้วถูกชนขยับมาที่นี่ → ไม่นับเพิ่ม

    anchors : list ของ (anchor_id, ax, ay, aw, ah) = ตำแหน่งของที่จับ/นับไปแล้ว

    หลัก conservation:
      ของชิ้นเดิมที่ "ถูกชนขยับ" จะทำให้จุดเดิมของมัน "ว่างลง" (diff สูงเพราะ bg ยังจำ
      ของไว้ที่จุดเดิม แต่ตอนนี้เป็นถาดเปล่า) และ blob ใหม่โผล่ใกล้ ๆ จุดเดิม
      → ถือเป็นของเดิมที่ขยับ ไม่ใช่ชิ้นใหม่

    ข้อยกเว้น (ของตกทับ = stacking):
      ถ้า blob ใหม่ "ทับ" anchor เดิมเยอะ (overlap >= stack_overlap) → เป็นของชิ้นใหม่
      ที่ตกลงมาทับของเดิม (ไม่ใช่ของเดิมขยับ) → นับเป็นชิ้นใหม่
    """
    lcx, lcy, lw, lh = landing
    best, best_d = None, float("inf")
    for aid, ax, ay, aw, ah in anchors:
        d = math.hypot(lcx - ax, lcy - ay)
        if d > displace_radius:
            continue
        # ตกทับของเดิม (overlap สูง) → ไม่ถือว่า displaced แต่เป็นชิ้นใหม่ซ้อน
        if _boxes_overlap_ratio(landing, (ax, ay, aw, ah)) >= stack_overlap:
            continue
        vacated = region_activity(diff, ax, ay, aw, ah, pad=2) > vacate_mean_diff
        if vacated and d < best_d:
            best_d, best = d, aid
    if best is not None:
        return ("displaced", best)
    return ("new", None)