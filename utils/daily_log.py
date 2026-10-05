"""
utils/daily_log.py — log ยอดรายวัน logs/item_drops/YYYY-MM-DD.log (1 บรรทัด = การยืนยัน 1 ครั้ง)

    05/10/2026 13:45:12 : item drop : 1

  - เป็นแค่ภาพสะท้อนของตาราง confirmations ใน SQLite (แหล่งจริงของยอด) — ห้ามใช้ไฟล์นี้กู้ยอด
  - เวลา / วันที่ = confirmed_at ตาม COUNT_TIMEZONE (ไม่ขึ้นกับ timezone ของเครื่อง)
  - ระหว่างทำงาน: append ทีละบรรทัด (flush + fsync)
  - startup: สร้างไฟล์ของวันนี้ใหม่จาก DB แบบ atomic → ซ่อมบรรทัดที่ขาด/ซ้ำหลัง crash
  - ไม่ใช้ logging module (กัน timestamp/prefix ซ้อนจนรูปแบบเพี้ยน)
"""

import os

from utils.logger import get_logger

logger = get_logger("daily_log")


def format_line(conf):
    return f"{conf.confirmed_at.strftime('%d/%m/%Y %H:%M:%S')} : item drop : {conf.daily_sequence}\n"


def path_for(log_dir, local_date):
    return os.path.join(log_dir, f"{local_date}.log")


def append(log_dir, conf):
    """เพิ่มบรรทัดของการยืนยัน 1 ครั้ง — ล้มเหลวแค่ log error (ยอดจริงอยู่ใน DB แล้ว)"""
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(path_for(log_dir, conf.local_date), "a", encoding="utf-8", newline="\n") as f:
            f.write(format_line(conf))
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        logger.error(f"❌ เขียน daily log ไม่ได้ ({conf.local_date} #{conf.daily_sequence}): {e}")


def rebuild(log_dir, store, local_date):
    """เขียนไฟล์ของวันนั้นใหม่ทั้งไฟล์จาก DB (atomic) คืนจำนวนบรรทัด
    วันนั้นยังไม่มีการยืนยัน + ยังไม่มีไฟล์ → ไม่สร้างไฟล์ (ไม่มีบรรทัด item drop : 0 ปลอม)"""
    confs = store.confirmations_for_date(local_date)
    path = path_for(log_dir, local_date)
    if not confs and not os.path.exists(path):
        return 0
    try:
        os.makedirs(log_dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(format_line(c) for c in confs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        logger.error(f"❌ สร้าง daily log ใหม่ไม่ได้ ({path}): {e}")
    return len(confs)
