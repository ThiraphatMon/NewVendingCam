"""
api/cloud.py — เริ่ม/หยุด thread ฝั่ง cloud ตามสวิตช์ใน config (cloud_features)

  - ฟีเจอร์ที่ปิด: ไม่เริ่ม thread และไม่ส่ง HTTP เลย
  - ทุก thread หยุดได้ (stop event) — main เรียก stop() ตอนปิดโปรแกรม, test ไม่มี thread ค้างข้าม test
  - main loop ไม่รอ network: แค่ฝากเฟรม (submit_frame) / แจ้งว่ามี event ใน outbox (notify_outbox) แล้วไปต่อ

event ขึ้นเว็บ (ITEM_LANDED): main เขียนลงตาราง cloud_outbox ใน state DB หลังส่ง S0 → worker thread ส่งทีละรายการ
  สำเร็จ (2xx) → SENT | ไม่สำเร็จ → PENDING ต่อ + backoff (5s, 10s, 20s, ... สูงสุด RETRY_INTERVAL) ข้าม restart ได้
  ปิด CLOUD_SEND_EVENTS → ไม่เริ่ม worker: รายการที่ค้างหยุดส่ง (ไม่ลบ) | ไม่ลบภาพในเครื่องหลังส่งสำเร็จ
"""

import json
import sqlite3
import threading
import time

from api import client
from config import RETRY_INTERVAL, ROI_CONFIG_PATH, ROI_POLL_INTERVAL, SEND_INTERVAL, STATE_DB_PATH
from utils.logger import LogThrottle, get_logger
from utils.state_store import CloudOutbox

logger = get_logger("cloud")

# backoff ของการลองใหม่ (event / register / push ROI): BASE, BASE×2, ×4, ... สูงสุด RETRY_INTERVAL
BACKOFF_BASE_SEC = 5.0
# worker ตื่นมาดู outbox เองอย่างน้อยทุกกี่วินาที (ปกติ main ปลุกทันทีที่มี event ใหม่)
OUTBOX_IDLE_SEC = 30.0
# เปิด/อ่าน DB ไม่ได้ → ลองใหม่ทุกกี่วินาที
OUTBOX_DB_RETRY_SEC = 5.0
_outbox_err_log = LogThrottle(60.0)


def backoff_delay(attempts):
    """เวลารอก่อนลองครั้งถัดไป หลังล้มเหลวมาแล้ว attempts ครั้ง (≥1)"""
    cap = max(RETRY_INTERVAL, BACKOFF_BASE_SEC)
    return min(cap, BACKOFF_BASE_SEC * 2 ** max(0, attempts - 1))


def item_landed_event(machine_id, conf, obj_id):
    """event ITEM_LANDED แบบที่เว็บเดิมรับ → (event_id, payload)
    transaction_id = TXN-<เวลาไทยตอนยืนยัน>-<cycle_id 8 ตัวแรก> (ไม่ซ้ำ อ้างถึงรอบได้)
    item_no = ลำดับยอดของวัน, land_time = %H:%M:%S เวลาไทย, order_id ว่าง (โหมด START–STOP ไม่มี order)"""
    t = conf.confirmed_at
    payload = {
        "machine_id": machine_id,
        "event": "ITEM_LANDED",
        "transaction_id": f"TXN-{t:%Y%m%d-%H%M%S}-{conf.cycle_id[:8]}",
        "item_no": str(conf.daily_sequence),
        "obj_id": str(obj_id),
        "land_time": t.strftime("%H:%M:%S"),
        "order_id": "",
    }
    return f"ITEM_LANDED:{conf.cycle_id}", payload


class CloudServices:
    def __init__(self, machine_id, features, roi_path=ROI_CONFIG_PATH, db_path=STATE_DB_PATH):
        self.machine_id = machine_id
        self.features = dict(features)
        self.roi_path = roi_path
        self.db_path = db_path
        self._outbox_wake = threading.Event()
        self.stop_event = threading.Event()
        self.threads = []
        self.last_send_time = None  # เวลาที่ส่งภาพสดล่าสุด (None = ยังไม่เคย)

        self._frame_lock = threading.Lock()
        self._frame_ready = threading.Event()
        self._latest_frame = None

    def _spawn(self, target, name):
        t = threading.Thread(target=target, daemon=True, name=name)
        t.start()
        self.threads.append(t)

    def start(self):
        f = self.features
        # register / push ROI: เน็ตยังไม่มาตอนบูต → ลองใหม่แบบ backoff จนสำเร็จ (ไม่ busy-loop)
        if f["register"]:
            self._spawn(
                lambda: self._retry_until_ok(lambda: client.register_machine(self.machine_id), "register ตู้"),
                "cloud-register",
            )
        if f["roi_sync"]:
            self._spawn(
                lambda: self._retry_until_ok(
                    lambda: client.push_default_roi(self.machine_id, self.roi_path), "push ROI ตอนเริ่ม"
                ),
                "cloud-roi-push",
            )
            self._spawn(self._roi_poll_loop, "cloud-roi-poll")
        if f["realtime"]:
            self._spawn(self._frame_sender_loop, "cloud-frame-sender")
        if f["events"]:
            self._spawn(self._outbox_loop, "cloud-outbox")
        return self

    def stop(self, timeout=2.0):
        self.stop_event.set()
        self._frame_ready.set()  # ปลุก sender / outbox ให้เห็น stop
        self._outbox_wake.set()
        for t in self.threads:
            t.join(timeout)

    def _retry_until_ok(self, fn, what):
        """เรียก fn จนคืน True — ล้มเหลวรอ backoff_delay (5s, 10s, ... สูงสุด RETRY_INTERVAL) หยุดได้ด้วย stop()"""
        attempts = 0
        while not self.stop_event.is_set():
            if fn():
                if attempts:
                    logger.info(f"☁️ {what} สำเร็จ (หลังลองใหม่ {attempts} ครั้ง)")
                return True
            attempts += 1
            delay = backoff_delay(attempts)
            logger.warning(f"⚠️ {what} ไม่สำเร็จ → ลองใหม่ใน {delay:.0f}s (ครั้งที่ {attempts})")
            self.stop_event.wait(delay)
        return False

    # ── ROI sync ─────────────────────────────────────────────────────────────
    def _roi_poll_loop(self):
        while not self.stop_event.is_set():
            try:
                client.fetch_remote_roi(self.machine_id, self.roi_path)
            except Exception as e:
                logger.warning(f"⚠️ roi polling error: {e}")
            self.stop_event.wait(ROI_POLL_INTERVAL)

    # ── event ขึ้นเว็บ (outbox) ─────────────────────────────────────────────────
    def notify_outbox(self):
        """main เพิ่มแถวใน outbox แล้ว → ปลุก worker (ไม่รอ)"""
        self._outbox_wake.set()

    def _outbox_loop(self):
        outbox = None
        while not self.stop_event.is_set():
            try:
                if outbox is None:
                    outbox = CloudOutbox(self.db_path)
                self._outbox_step(outbox)
            except sqlite3.Error as e:
                _outbox_err_log(logger.error, f"❌ outbox DB error: {e} → ลองใหม่ใน {OUTBOX_DB_RETRY_SEC:.0f}s")
                if outbox is not None:
                    outbox.close()
                    outbox = None
                self.stop_event.wait(OUTBOX_DB_RETRY_SEC)
        if outbox is not None:
            outbox.close()

    def _outbox_step(self, outbox):
        now = time.time()
        row = outbox.next_due(now)
        if row is None:
            nxt = outbox.next_attempt_at()
            timeout = OUTBOX_IDLE_SEC if nxt is None else min(OUTBOX_IDLE_SEC, max(0.0, nxt - now))
            self._outbox_wake.wait(timeout)
            self._outbox_wake.clear()
            return
        err = client.send_event(json.loads(row["payload"]), row["image_path"])
        name = f"{row['event']} {json.loads(row['payload']).get('transaction_id', row['event_id'])}"
        if err is None:
            outbox.mark_sent(row["id"])
            logger.info(f"☁️ ส่ง {name} สำเร็จ (ครั้งที่ {row['attempts'] + 1})")
        else:
            delay = backoff_delay(row["attempts"] + 1)
            outbox.mark_failed(row["id"], err, time.time() + delay)
            _outbox_err_log(logger.warning, f"⚠️ ส่ง {name} ไม่สำเร็จ ({err}) → ลองใหม่ใน {delay:.0f}s")

    # ── ภาพสด ───────────────────────────────────────────────────────────────
    def realtime_due(self, now):
        """ถึงเวลาส่งภาพสดหรือยัง (ภาพแรกส่งทันที แล้วทุก SEND_INTERVAL วินาที)"""
        if not self.features["realtime"]:
            return False
        return self.last_send_time is None or now - self.last_send_time >= SEND_INTERVAL

    def submit_frame(self, frame, now):
        """ฝากเฟรมให้ thread ส่ง (copy เพราะ main loop วาด overlay ทับต่อ) — เฟรมที่ยังไม่ได้ส่งถูกทับทิ้ง ไม่ต่อคิว"""
        with self._frame_lock:
            self._latest_frame = frame.copy()
            self._frame_ready.set()
        self.last_send_time = now

    def _frame_sender_loop(self):
        while not self.stop_event.is_set():
            self._frame_ready.wait()
            with self._frame_lock:
                frame, self._latest_frame = self._latest_frame, None
                self._frame_ready.clear()
            if frame is not None and not self.stop_event.is_set():
                client.send_frame(self.machine_id, frame)
