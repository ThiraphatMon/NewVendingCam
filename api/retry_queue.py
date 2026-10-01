"""
retry_queue.py
--------------
ระบบรับมือเน็ตหลุด

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
            print(f"🗑️ ลบรูปสำเร็จ: {image_path}")
        except Exception as e:
            print(f"⚠️ ลบรูปไม่ได้: {image_path} — {e}")


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
        print(
            f"✅ ส่ง event สำเร็จ: {payload.get('event')} / {payload.get('transaction_id')}"
        )
    else:
        # ❌ ส่งไม่สำเร็จ — เก็บลง queue รอ retry
        item = {"payload": payload, "image_path": image_path}
        with _queue_lock:
            _pending_queue.append(item)
        print(
            f"📥 บันทึกลง queue รอ retry: {payload.get('event')} / {payload.get('transaction_id')}"
            f" (queue ตอนนี้มี {len(_pending_queue)} รายการ)"
        )


def _retry_loop():
    """
    Background thread — วน retry ทุก RETRY_INTERVAL วินาที
    ทำงานตลอดอายุโปรแกรม (daemon=True)
    """
    print(f"🔄 Retry loop เริ่มทำงาน (ทุก {RETRY_INTERVAL} วินาที)")
    while True:
        time.sleep(RETRY_INTERVAL)

        # ดึง snapshot ของ queue ออกมาทำงาน
        # ทำแบบนี้เพื่อไม่ lock นานเกินไประหว่าง network call
        with _queue_lock:
            if not _pending_queue:
                continue  # queue ว่าง → รอรอบถัดไป
            items_to_retry = list(_pending_queue)

        print(f"🔄 กำลัง retry {len(items_to_retry)} รายการ...")

        still_pending = []  # รายการที่ยังส่งไม่สำเร็จ

        for item in items_to_retry:
            success = post_event(item["payload"], item["image_path"])
            if success:
                # ✅ retry สำเร็จ — ลบรูปทิ้ง
                _delete_image(item["image_path"])
                print(
                    f"✅ Retry สำเร็จ: {item['payload'].get('event')} / "
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
            print(f"⏳ ยังมี {len(still_pending)} รายการรอ retry รอบถัดไป")
        else:
            print("✅ Retry ครบทุกรายการแล้ว — queue ว่างแล้ว")


def start_retry_thread():
    """
    เรียกครั้งเดียวตอน startup เพื่อเริ่ม background retry loop
    daemon=True → thread จะดับตามโปรแกรมหลักโดยอัตโนมัติ
    """
    t = threading.Thread(target=_retry_loop, daemon=True)
    t.start()
    return t
