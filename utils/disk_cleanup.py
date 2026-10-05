"""
disk_cleanup.py  –  ลบไฟล์รูปเก่าออกอัตโนมัติ

Policy (ตั้งใน config / .env):
  - evidence_images/anomaly/ เก็บไม่เกิน ANOMALY_KEEP_DAYS วัน
  - รูปอื่นใน evidence_images/ (confirmed/ และโฟลเดอร์เดิม with_order/ without_order/)
    เก็บไม่เกิน CLEANUP_KEEP_DAYS วัน
  - เรียกทุก CLEANUP_INTERVAL_HOURS ชั่วโมง
  - ลบเฉพาะใน evidence_images เท่านั้น — ไม่แตะไฟล์ DB (data/) และ logs/item_drops
    (ลบรูปเก่าไม่ทำให้ยอดรายวันลด เพราะยอดอยู่ใน DB)
  - ห้ามลบภาพของ event ที่ยังรอส่งขึ้นเว็บ (cloud_outbox PENDING) แม้เก่าเกินกำหนด
    อ่านรายการไม่ได้ → ข้าม cleanup รอบนั้นทั้งรอบ (ไม่เสี่ยงลบภาพที่รอส่ง)
"""

import os
import time
import threading
from config import CLEANUP_KEEP_DAYS, CLEANUP_INTERVAL_HOURS, ANOMALY_KEEP_DAYS, EVIDENCE_DIR
from utils.logger import get_logger

logger = get_logger("disk_cleanup")

ANOMALY_SUBDIR = "anomaly"


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _cleanup_once(image_dir=EVIDENCE_DIR, now=None, protected=()):
    """ลบไฟล์ที่เก่าเกินกำหนดออกจาก image_dir คืนจำนวนไฟล์ที่ลบ
    protected: path ที่ห้ามลบ (ภาพที่รอส่งขึ้นเว็บ)"""
    protected = {_norm(p) for p in protected}
    kept = 0
    if not os.path.isdir(image_dir):
        return 0
    now = time.time() if now is None else now
    anomaly_root = os.path.join(image_dir, ANOMALY_SUBDIR)
    removed = 0
    # อัพเดทใหม่สำหรับลง Orange Pi:
    # รูปอยู่ในโฟลเดอร์ย่อย จึงต้องเดินทุกโฟลเดอร์ย่อย เพื่อป้องกัน eMMC เต็มเมื่อเครื่องทำงานต่อเนื่อง
    for root, _, files in os.walk(image_dir):
        is_anomaly = os.path.commonpath([root, anomaly_root]) == anomaly_root
        keep_days = ANOMALY_KEEP_DAYS if is_anomaly else CLEANUP_KEEP_DAYS
        cutoff = now - keep_days * 86400
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    if protected and _norm(fpath) in protected:
                        kept += 1
                        continue
                    os.remove(fpath)
                    removed += 1
            except Exception as e:
                logger.warning(f"ลบไฟล์ไม่ได้ {fpath}: {e}")
    if kept:
        logger.info(f"🧹 Disk cleanup: เก็บภาพเก่า {kept} ไฟล์ไว้ก่อน (ยังรอส่งขึ้นเว็บ)")
    if removed:
        logger.info(
            f"🧹 Disk cleanup: ลบ {removed} ไฟล์ "
            f"(ภาพทั่วไปเก่ากว่า {CLEANUP_KEEP_DAYS} วัน / anomaly เก่ากว่า {ANOMALY_KEEP_DAYS} วัน)"
        )
    return removed


def start_cleanup_thread(protected_paths=None):
    """เริ่ม background thread สำหรับ disk cleanup
    protected_paths: callable คืน path ที่ห้ามลบ (เรียกใหม่ทุกรอบ)"""

    def _loop():
        while True:
            try:
                protected = protected_paths() if protected_paths else ()
            except Exception as e:
                logger.warning(f"⚠️ Disk cleanup: อ่านรายการภาพที่รอส่งไม่ได้ ({e}) → ข้ามรอบนี้")
            else:
                _cleanup_once(protected=protected)
            time.sleep(CLEANUP_INTERVAL_HOURS * 3600)

    t = threading.Thread(target=_loop, daemon=True, name="disk-cleanup")
    t.start()
    logger.info(
        f"🧹 Disk cleanup thread เริ่มแล้ว (เก็บภาพ {CLEANUP_KEEP_DAYS} วัน, anomaly {ANOMALY_KEEP_DAYS} วัน, "
        f"cleanup ทุก {CLEANUP_INTERVAL_HOURS} ชม.)"
    )
