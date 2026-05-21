import threading
import time
import os
from datetime import datetime
from api.retry_queue import send_or_queue
from utils.image_saver import save_evidence_image


class VendingStateMachine:
    def __init__(self, default_machine="VENDING_01"):
        self.machine_id = default_machine
        self._reset_fields()

    def _reset_fields(self):
        self.state = "IDLE"
        self.transaction_id = None
        self.drop_time = None

        # --- multi-item tracking ---
        # dict: obj_id -> {"capture_time", "land_img_path", "land_time", "emitted"}
        self.captured_items = {}
        # ยังคง land_obj_id / land_img_path ไว้เพื่อ backward-compat กับ main.py display
        self.land_obj_id = None
        self.capture_time = None
        self.land_img_path = None

    # ─────────────────────────────────────────────
    # trigger() — เรียกจาก main loop
    # ─────────────────────────────────────────────
    def trigger(self, event, obj_id=None, frame=None):
        now = time.time()

        if self.state == "IDLE":
            if event == "motion_in_ROI":
                self.state = "DROP_DETECTED"
                self.drop_time = now
                self.transaction_id = datetime.now().strftime("TXN-%Y%m%d-%H%M%S")
                print(
                    f"[{self.machine_id}] 📦 ของกำลังตก... (txn={self.transaction_id})"
                )

        elif self.state == "DROP_DETECTED":
            if event == "still_in_ROI" and obj_id is not None:
                self._capture_item(obj_id, frame, now)

            elif event == "timeout":
                if not self.captured_items:
                    # timeout โดยไม่จับได้อะไรเลย
                    self._emit_no_drop()
                self.reset()

        elif self.state == "EVIDENCE_CAPTURED":
            # รับชิ้นใหม่ที่ confirmed เพิ่มเข้ามา (ของชิ้นที่ 2, 3, ...)
            if event == "still_in_ROI" and obj_id is not None:
                if obj_id not in self.captured_items:
                    self._capture_item(obj_id, frame, now)

    # ─────────────────────────────────────────────
    # _capture_item() — บันทึกและ emit ทีละชิ้น
    # ─────────────────────────────────────────────
    def _capture_item(self, obj_id, frame, now):
        item_no = len(self.captured_items) + 1
        img_path = None
        if frame is not None:
            img_path = save_evidence_image(
                frame, f"LANDED_item{item_no}", self.transaction_id
            )

        self.captured_items[obj_id] = {
            "land_time": now,
            "land_img_path": img_path,
            "item_no": item_no,
        }

        # อัปเดต backward-compat fields (ชี้ไปที่ชิ้นล่าสุดเสมอ)
        self.land_obj_id = obj_id
        self.capture_time = now
        self.land_img_path = img_path

        if self.state != "EVIDENCE_CAPTURED":
            self.state = "EVIDENCE_CAPTURED"

        print(
            f"[{self.machine_id}] 📸 จับของชิ้นที่ {item_no} ได้! "
            f"obj_id={obj_id}  txn={self.transaction_id}"
        )
        self._emit_item_landed(obj_id, now, img_path, item_no)

    # ─────────────────────────────────────────────
    # emit helpers
    # ─────────────────────────────────────────────
    def _emit_item_landed(self, obj_id, land_time, image_path, item_no):
        payload = {
            "machine_id": self.machine_id,
            "event": "ITEM_LANDED",
            "transaction_id": self.transaction_id,
            "item_no": item_no,
            "obj_id": obj_id,
            "land_time": self._ts(land_time),
        }
        threading.Thread(
            target=send_or_queue,
            args=(payload, image_path),
            daemon=True,
        ).start()

    def _emit_no_drop(self):
        payload = {
            "machine_id": self.machine_id,
            "event": "NO_DROP",
            "transaction_id": self.transaction_id,
            "land_time": None,
        }
        threading.Thread(
            target=send_or_queue,
            args=(payload, None),
            daemon=True,
        ).start()

    # ─────────────────────────────────────────────
    # helpers
    # ─────────────────────────────────────────────
    def reset(self):
        self._reset_fields()

    def item_count(self):
        """จำนวนชิ้นที่จับได้ใน transaction นี้"""
        return len(self.captured_items)

    def is_obj_captured(self, obj_id):
        return obj_id in self.captured_items

    def _ts(self, t):
        return datetime.fromtimestamp(t).strftime("%H:%M:%S")
