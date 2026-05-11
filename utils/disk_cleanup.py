"""
disk_cleanup.py  –  ลบไฟล์รูปเก่าออกอัตโนมัติ

Policy ค่าเริ่มต้น:
  - เก็บไฟล์ไม่เกิน KEEP_DAYS วัน (default 30 วัน)
  - เรียกทุก CLEANUP_INTERVAL_HOURS ชั่วโมง (default 6 ชั่วโมง)
"""

import os
import time
import threading
from utils.logger import get_logger

logger = get_logger("disk_cleanup")

IMAGE_DIR = "evidence_images"
KEEP_DAYS = int(os.getenv("CLEANUP_KEEP_DAYS", "30"))
CLEANUP_INTERVAL_HOURS = int(os.getenv("CLEANUP_INTERVAL_HOURS", "6"))


def _cleanup_once():
    """ลบไฟล์ที่เก่ากว่า KEEP_DAYS วันออกจาก IMAGE_DIR"""
    if not os.path.isdir(IMAGE_DIR):
        return
    cutoff = time.time() - KEEP_DAYS * 86400
    removed = 0
    for fname in os.listdir(IMAGE_DIR):
        fpath = os.path.join(IMAGE_DIR, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                removed += 1
        except Exception as e:
            logger.warning(f"ลบไฟล์ไม่ได้ {fpath}: {e}")
    if removed:
        logger.info(f"🧹 Disk cleanup: ลบ {removed} ไฟล์ (เก่ากว่า {KEEP_DAYS} วัน)")


def start_cleanup_thread():
    """เริ่ม background thread สำหรับ disk cleanup"""

    def _loop():
        while True:
            _cleanup_once()
            time.sleep(CLEANUP_INTERVAL_HOURS * 3600)

    t = threading.Thread(target=_loop, daemon=True, name="disk-cleanup")
    t.start()
    logger.info(
        f"🧹 Disk cleanup thread เริ่มแล้ว (เก็บ {KEEP_DAYS} วัน, cleanup ทุก {CLEANUP_INTERVAL_HOURS} ชม.)"
    )
