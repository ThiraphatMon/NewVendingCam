"""
utils/image_saver.py — บันทึกภาพหลักฐานแบบ atomic

  evidence_images/confirmed/  ภาพของรอบที่ยืนยันสินค้าได้ (1 ภาพต่อรอบ)
  evidence_images/anomaly/    ภาพความผิดปกติ (นอกรอบ / ของเพิ่มหลังยืนยัน / ปิดรอบโดยไม่ยืนยัน)

เขียนไฟล์ .tmp.jpg ให้เสร็จ (ตรวจผล imwrite + fsync) แล้วค่อย os.replace เป็นชื่อจริง
→ ไฟดับกลางคันจะไม่มีไฟล์ภาพครึ่ง ๆ ที่ชื่อจริง (อาจเหลือ .tmp.jpg ซึ่ง disk_cleanup ลบตามอายุ)
"""

import os
from datetime import datetime

import cv2

from config import EVIDENCE_DIR
from utils.logger import get_logger

logger = get_logger("image_saver")

CONFIRMED = "confirmed"
ANOMALY = "anomaly"


def save_evidence(frame, folder, kind, cycle_id, base_dir=EVIDENCE_DIR, label=None):
    """บันทึกภาพ คืน path ของไฟล์ หรือ None ถ้าบันทึกไม่สำเร็จ (log สาเหตุให้แล้ว)

    folder   : CONFIRMED / ANOMALY
    kind     : ชนิดภาพ เช่น CONFIRMED, OUTSIDE_CYCLE (อยู่ในชื่อไฟล์และป้ายบนภาพ)
    cycle_id : รอบที่ภาพนี้เป็นของ (None = ไม่มีรอบ)
    """
    now = datetime.now()
    save_dir = os.path.join(base_dir, folder)
    stem = f"{now.strftime('%Y%m%d_%H%M%S_%f')[:-3]}_{kind}_{cycle_id or 'nocycle'}"
    path = os.path.join(save_dir, stem + ".jpg")
    # กันชื่อชน (เวลาเดียวกันถึงระดับ ms + รอบเดียวกัน — เช่น anomaly ถี่ ๆ)
    n = 1
    while os.path.exists(path):
        path = os.path.join(save_dir, f"{stem}_{n}.jpg")
        n += 1
    tmp = path[:-4] + ".tmp.jpg"  # ต้องลงท้าย .jpg ให้ OpenCV เลือก encoder ได้

    image = frame.copy()
    text = f"{label or kind}: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    if cycle_id:
        text += f" [{cycle_id[:8]}]"
    cv2.putText(image, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    try:
        os.makedirs(save_dir, exist_ok=True)
        if not cv2.imwrite(tmp, image):
            raise OSError("cv2.imwrite คืน False")
        with open(tmp, "rb+") as f:
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except (OSError, cv2.error) as e:
        logger.error(f"❌ บันทึกภาพ {kind} ไม่สำเร็จ ({path}): {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None
    return path
