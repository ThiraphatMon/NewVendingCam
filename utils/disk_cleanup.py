"""
disk_cleanup.py  –  ลบไฟล์รูปเก่าออกอัตโนมัติ

Policy (ตั้งใน config / .env):
  - เก็บไฟล์ไม่เกิน CLEANUP_KEEP_DAYS วัน
  - เรียกทุก CLEANUP_INTERVAL_HOURS ชั่วโมง
"""

import os
import time
import threading
from config import CLEANUP_KEEP_DAYS, CLEANUP_INTERVAL_HOURS
from utils.logger import get_logger

logger = get_logger("disk_cleanup")

IMAGE_DIR = "evidence_images"


def _cleanup_once():
    """ลบไฟล์ที่เก่ากว่า CLEANUP_KEEP_DAYS วันออกจาก IMAGE_DIR"""
    if not os.path.isdir(IMAGE_DIR):
        return
    cutoff = time.time() - CLEANUP_KEEP_DAYS * 86400
    removed = 0
    # อัพเดทใหม่สำหรับลง Orange Pi:
    # รูปจริงอยู่ใน with_order/ และ without_order/ จึงต้องเดินทุกโฟลเดอร์ย่อย
    # เพื่อป้องกัน eMMC เต็มเมื่อเครื่องทำงานต่อเนื่อง
    for root, _, files in os.walk(IMAGE_DIR):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
            except Exception as e:
                logger.warning(f"ลบไฟล์ไม่ได้ {fpath}: {e}")
    if removed:
        logger.info(f"🧹 Disk cleanup: ลบ {removed} ไฟล์ (เก่ากว่า {CLEANUP_KEEP_DAYS} วัน)")


def start_cleanup_thread():
    """เริ่ม background thread สำหรับ disk cleanup"""

    def _loop():
        while True:
            _cleanup_once()
            time.sleep(CLEANUP_INTERVAL_HOURS * 3600)

    t = threading.Thread(target=_loop, daemon=True, name="disk-cleanup")
    t.start()
    logger.info(
        f"🧹 Disk cleanup thread เริ่มแล้ว (เก็บ {CLEANUP_KEEP_DAYS} วัน, cleanup ทุก {CLEANUP_INTERVAL_HOURS} ชม.)"
    )
