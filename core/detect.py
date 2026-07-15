"""
core/detect.py — foreground-mask building + blob detection

สร้าง binary motion mask จากภาพ diff แล้วหา bounding boxes ของ blob

Pipeline: threshold → OPEN (ลบ noise จุดเล็ก) → DILATE (เชื่อม mask ชิ้นเดียวที่ขาด)
  - OPEN ลบ noise จุดเดียวออกก่อน
  - DILATE อยู่ท้ายสุด: ขยายเฉพาะมวลของจริงที่เหลือ (ถ้า dilate ก่อน noise จะโดนขยายตาม)
    ทำให้ mask ของวัตถุชิ้นเดียวที่ขาดเป็นหย่อม ๆ เชื่อมเป็นก้อนตัน → contour เดียว
"""

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
