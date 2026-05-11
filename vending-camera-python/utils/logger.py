import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "vending.log")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 5  # เก็บ 5 ไฟล์ = 25 MB สูงสุด


def get_logger(name: str = "vending") -> logging.Logger:
    """คืน logger ที่ตั้งค่าแล้ว (เรียกซ้ำได้ ได้ object เดิมเสมอ)"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # ตั้งค่าไปแล้ว ไม่ต้องทำซ้ำ

    logger.setLevel(logging.DEBUG)

    os.makedirs(LOG_DIR, exist_ok=True)

    # Handler: เขียนไฟล์ + rotate อัตโนมัติ
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)

    # Handler: แสดงใน console
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger
