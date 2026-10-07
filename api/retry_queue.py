"""
retry_queue.py
--------------
⚠️ เลิกใช้แล้ว (ไม่มีใครเริ่ม thread นี้) — event ขึ้นเว็บใช้ cloud_outbox ใน DB (api/cloud.py)
   ห้ามนำกลับมาใช้กับภาพหลักฐาน: ส่งสำเร็จแล้วลบภาพในเครื่อง (_delete_image) และคิวอยู่ใน memory (restart แล้วหาย)

ระบบรับมือเน็ตหลุด (เดิม)

หลักการทำงาน:
  1. ทุกครั้งที่จะส่ง event → เรียก send_or_queue()
  2. ถ้าส่งสำเร็จทันที → ลบรูปออกจากเครื่องเลย
  3. ถ้าส่งไม่สำเร็จ  → บันทึกลง pending_queue (เก็บไว้ใน memory)
  4. background thread วน retry ทุก RETRY_INTERVAL วินาที (ตั้งใน config)
  5. เมื่อ retry สำเร็จ → ลบรูปออกจากเครื่อง
"""

import threading
import time
import os
from api.client import post_event
from config import RETRY_INTERVAL
from utils.logger import get_logger

logger = get_logger("retry_queue")

# ---- Queue และ Lock ----
# pending_queue คือ list ของ dict แต่ละตัวมีรูปแบบดังนี้:
# {
#   "payload":    dict  — ข้อมูล event ที่จะส่ง (machine_id, event, ...)
#   "image_path": str หรือ None — path รูปที่เก็บไว้
# }
_pending_queue: list[dict] = []
_queue_lock = threading.Lock()  # ป้องกัน 2 thread แก้ queue พร้อมกัน


def _delete_image(image_path: str | None):
    """ลบรูปออกจากเครื่อง ถ้า path ไม่ None และไฟล์ยังอยู่"""
    if image_path and os.path.exists(image_path):
        try:
            os.remove(image_path)
            logger.info(f"image deleted: {image_path}")
        except Exception as e:
            logger.warning(f"cannot delete image: {image_path} - {e}")


def send_or_queue(payload: dict, image_path: str | None = None):
    """
    พยายามส่ง event ไปยัง server ทันที
      - สำเร็จ → ลบรูปทิ้งเลย
      - ไม่สำเร็จ → เก็บลง pending_queue รอ retry
    เรียกฟังก์ชันนี้แทน post_event() โดยตรง
    """
    success = post_event(payload, image_path)

    if success:
        # ✅ ส่งสำเร็จ — ลบรูปทันที
        _delete_image(image_path)
        logger.info(
            f"event sent: {payload.get('event')} / {payload.get('transaction_id')}"
        )
    else:
        # ❌ ส่งไม่สำเร็จ — เก็บลง queue รอ retry
        item = {"payload": payload, "image_path": image_path}
        with _queue_lock:
            _pending_queue.append(item)
        logger.info(
            f"queued for retry: {payload.get('event')} / {payload.get('transaction_id')}"
            f" (queue now has {len(_pending_queue)} item(s))"
        )


def _retry_loop():
    """
    Background thread — วน retry ทุก RETRY_INTERVAL วินาที
    ทำงานตลอดอายุโปรแกรม (daemon=True)
    """
    logger.info(f"retry loop started (every {RETRY_INTERVAL}s)")
    while True:
        time.sleep(RETRY_INTERVAL)

        # ดึง snapshot ของ queue ออกมาทำงาน
        # ทำแบบนี้เพื่อไม่ lock นานเกินไประหว่าง network call
        with _queue_lock:
            if not _pending_queue:
                continue  # queue ว่าง → รอรอบถัดไป
            items_to_retry = list(_pending_queue)

        logger.info(f"retrying {len(items_to_retry)} item(s)...")

        still_pending = []  # รายการที่ยังส่งไม่สำเร็จ

        for item in items_to_retry:
            success = post_event(item["payload"], item["image_path"])
            if success:
                # ✅ retry สำเร็จ — ลบรูปทิ้ง
                _delete_image(item["image_path"])
                logger.info(
                    f"retry OK: {item['payload'].get('event')} / "
                    f"{item['payload'].get('transaction_id')}"
                )
            else:
                # ❌ ยังส่งไม่ได้ — เก็บรอรอบถัดไป
                still_pending.append(item)

        # อัปเดต queue ด้วยรายการที่ยังค้างอยู่
        with _queue_lock:
            # ใช้ slice แทน assignment ตรงๆ เพื่อความปลอดภัย
            _pending_queue[:] = still_pending

        if still_pending:
            logger.info(f"{len(still_pending)} item(s) left for next retry")
        else:
            logger.info("all retries done - queue empty")


def start_retry_thread():
    """
    เรียกครั้งเดียวตอน startup เพื่อเริ่ม background retry loop
    daemon=True → thread จะดับตามโปรแกรมหลักโดยอัตโนมัติ
    """
    t = threading.Thread(target=_retry_loop, daemon=True)
    t.start()
    return t
