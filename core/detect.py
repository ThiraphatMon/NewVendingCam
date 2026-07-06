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


def build_fgmask(
    diff,
    mot_thresh,
    open_ksize=3,
    close_ksize=3,
    median_ksize=0,
    dilate_ksize=0,
    dilate_iter=0,
):
    """
    สร้าง binary motion mask จากภาพ diff (absdiff ระหว่างเฟรมกับ background)

    median_ksize : ขนาด median blur (เลขคี่) ลบ speckle noise ก่อน morphology
                   สำคัญตอน mot_thresh ต่ำ ๆ — ลบจุด noise กระจายโดยไม่กินของตัน
    open_ksize   : ขนาด kernel ของ MORPH_OPEN — ลบ noise จุดเล็ก ๆ
    close_ksize  : ขนาด kernel ของ MORPH_CLOSE — อุดรูภายในชิ้นเดิมโดยไม่บวมออก
    dilate_ksize : ขนาด kernel ของ MORPH_DILATE — ขยาย/เชื่อม mask ของชิ้นเดียว
                   ที่ขาดเป็นหย่อม ๆ ให้ตันเป็นก้อนเดียว (สไตล์ OLD ที่ detect แม่น)
                   0 = ปิด (ใช้เฉพาะ OPEN+CLOSE เล็กแบบเดิม)
    dilate_iter  : จำนวนรอบที่ทำ DILATE (OLD ใช้ 2). 0 = ปิด

    ลำดับ: threshold → median → OPEN (ลบ noise) → CLOSE (อุดรู) → DILATE (เชื่อมชิ้น)
    เหตุที่ DILATE อยู่ท้ายสุด: ให้ลบ noise ออกก่อน (OPEN) แล้วค่อยขยายเฉพาะ
    มวลของจริงที่เหลือ — ถ้า dilate ก่อน noise จะถูกขยายตามไปด้วย
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
    if dilate_ksize and dilate_ksize >= 1 and dilate_iter and dilate_iter >= 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_ksize, dilate_ksize))
        fgmask = cv2.morphologyEx(
            fgmask, cv2.MORPH_DILATE, k, iterations=dilate_iter
        )
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
