"""
api/cloud.py — เริ่ม/หยุด thread ฝั่ง cloud ตามสวิตช์ใน config (cloud_features)

  - ฟีเจอร์ที่ปิด: ไม่เริ่ม thread และไม่ส่ง HTTP เลย
  - ทุก thread หยุดได้ (stop event) — main เรียก stop() ตอนปิดโปรแกรม, test ไม่มี thread ค้างข้าม test
  - main loop ไม่รอ network: แค่ฝากเฟรม (submit_frame) แล้วไปต่อ
"""

import threading

from api import client
from config import ROI_CONFIG_PATH, ROI_POLL_INTERVAL, SEND_INTERVAL
from utils.logger import get_logger

logger = get_logger("cloud")


class CloudServices:
    def __init__(self, machine_id, features, roi_path=ROI_CONFIG_PATH):
        self.machine_id = machine_id
        self.features = dict(features)
        self.roi_path = roi_path
        self.stop_event = threading.Event()
        self.threads = []
        self.last_send_time = None  # เวลาที่ส่งภาพสดล่าสุด (None = ยังไม่เคย)

        self._frame_lock = threading.Lock()
        self._frame_ready = threading.Event()
        self._latest_frame = None

    @property
    def any_enabled(self):
        return any(self.features.values())

    def _spawn(self, target, name):
        t = threading.Thread(target=target, daemon=True, name=name)
        t.start()
        self.threads.append(t)

    def start(self):
        f = self.features
        if f["register"]:
            self._spawn(lambda: client.register_machine(self.machine_id), "cloud-register")
        if f["roi_sync"]:
            self._spawn(lambda: client.push_default_roi(self.machine_id, self.roi_path), "cloud-roi-push")
            self._spawn(self._roi_poll_loop, "cloud-roi-poll")
        if f["realtime"]:
            self._spawn(self._frame_sender_loop, "cloud-frame-sender")
        if f["events"]:
            from api.retry_queue import start_retry_thread

            self.threads.append(start_retry_thread())
        return self

    def stop(self, timeout=2.0):
        self.stop_event.set()
        self._frame_ready.set()  # ปลุก sender ให้เห็น stop
        for t in self.threads:
            t.join(timeout)

    # ── ROI sync ─────────────────────────────────────────────────────────────
    def _roi_poll_loop(self):
        while not self.stop_event.is_set():
            try:
                client.fetch_remote_roi(self.machine_id, self.roi_path)
            except Exception as e:
                logger.warning(f"⚠️ roi polling error: {e}")
            self.stop_event.wait(ROI_POLL_INTERVAL)

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
