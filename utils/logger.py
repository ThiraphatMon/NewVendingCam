import logging
import os
import time
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "vending.log")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 5  # เก็บ 5 ไฟล์ = 25 MB สูงสุด

ROOT_NAME = "vending"


def _setup_root() -> logging.Logger:
    """ตั้ง handler ครั้งเดียวที่ logger แม่ "vending"
    ทุกโมดูลใช้ logger ลูก ("vending.<ชื่อ>") ที่ส่งต่อขึ้นมาที่นี่
    → มี RotatingFileHandler ตัวเดียวต่อไฟล์ (หลายตัวเขียนไฟล์เดียวกันจะ rotate พัง)"""
    root = logging.getLogger(ROOT_NAME)
    if root.handlers:
        return root  # ตั้งค่าไปแล้ว ไม่ต้องทำซ้ำ

    root.setLevel(logging.DEBUG)
    os.makedirs(LOG_DIR, exist_ok=True)

    # Handler: เขียนไฟล์ + rotate อัตโนมัติ
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)

    # Handler: แสดงใน console (docker compose logs)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    root.addHandler(fh)
    root.addHandler(ch)
    return root


def get_logger(name: str = ROOT_NAME) -> logging.Logger:
    """คืน logger ที่ตั้งค่าแล้ว (เรียกซ้ำได้ ได้ object เดิมเสมอ)"""
    root = _setup_root()
    if name == ROOT_NAME:
        return root
    return logging.getLogger(f"{ROOT_NAME}.{name}")


class LogThrottle:
    """จำกัดความถี่ของ log ที่อาจเกิดทุกเฟรม (~30 ครั้ง/วิ)
    ปล่อยผ่านได้ 1 ครั้งทุก interval วินาที และบอกจำนวนครั้งที่ถูกข้ามไปต่อท้ายข้อความ

    ใช้: _throttle = LogThrottle(5.0) แล้ว _throttle(logger.info, "ข้อความ")
    """

    def __init__(self, interval: float):
        self.interval = interval
        self._last = None
        self._skipped = 0

    def __call__(self, log_fn, msg: str):
        now = time.time()
        if self._last is not None and now - self._last < self.interval:
            self._skipped += 1
            return
        if self._skipped:
            msg += f" (+{self._skipped} repeats in previous {self.interval:.0f}s)"
        log_fn(msg)
        self._last = now
        self._skipped = 0
