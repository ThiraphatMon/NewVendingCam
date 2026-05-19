import threading
import time
import os
from datetime import datetime
from api.retry_queue import send_or_queue  # ← เปลี่ยนจาก post_event
from utils.image_saver import save_evidence_image


class VendingStateMachine:
    def __init__(self, default_machine="VENDING_01"):
        self.machine_id = default_machine
        self._reset_fields()

    def _reset_fields(self):
        self.state = "IDLE"
        self.transaction_id = None
        self.land_time = None
        self.capture_time = None
        self.land_obj_id = None
        self.land_img_path = None
        self.drop_time = None

    def trigger(self, event, obj_id=None, frame=None):
        now = time.time()
        if self.state == "IDLE":
            if event == "motion_in_ROI":
                self.state = "DROP_DETECTED"
                self.drop_time = now
                self.transaction_id = datetime.now().strftime("TXN-%Y%m%d-%H%M%S")
                print(f"[{self.machine_id}] 📦 ของกำลังตก...")

        elif self.state == "DROP_DETECTED":
            if event == "still_in_ROI":
                self.land_time = now
                self.land_obj_id = obj_id
                if frame is not None:
                    self.land_img_path = save_evidence_image(
                        frame, "LANDED", self.transaction_id
                    )
                self.state = "EVIDENCE_CAPTURED"
                self.capture_time = now
                print(f"[{self.machine_id}] 📸 ถ่ายรูปสำเร็จ! กำลังส่งไป Server...")
                self._emit("ITEM_LANDED")
            elif event == "timeout":
                self.state = "NO_DROP"
                self._emit("NO_DROP")
                self.reset()

    def reset(self):
        self._reset_fields()

    def _ts(self, t):
        return datetime.fromtimestamp(t).strftime("%H:%M:%S")

    def _emit(self, event_type):
        payload = {
            "machine_id": self.machine_id,
            "event": event_type,
            "transaction_id": self.transaction_id,
            "land_time": self._ts(self.land_time) if self.land_time else None,
        }

        # ส่ง image_path ไปด้วยเฉพาะ ITEM_LANDED เพราะ NO_DROP ไม่มีรูป
        image_path = self.land_img_path if event_type == "ITEM_LANDED" else None

        # ใช้ thread เพื่อไม่บล็อก main loop
        # send_or_queue จะจัดการลบรูป / เก็บ queue ให้เองอัตโนมัติ
        threading.Thread(
            target=send_or_queue,
            args=(payload, image_path),
            daemon=True,
        ).start()
