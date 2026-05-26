import threading
import time
import os
from datetime import datetime
from api.retry_queue import send_or_queue
from utils.image_saver import save_evidence_image
from config import CONFIRMED_ITEM_GONE_TIMEOUT


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
            "gone_since": None,  # timestamp ที่ของหายจาก tracked (None = ยังอยู่)
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
        # [FIX: DUPLICATE] Server ใช้ transaction_id เป็น unique key
        # item หลายชิ้นใน transaction เดียวกันจึงต้องได้ transaction_id ต่างกัน
        # ใช้รูปแบบ TXN-...-item1, TXN-...-item2 เพื่อให้ยังเชื่อมกับ transaction หลักได้
        item_transaction_id = f"{self.transaction_id}-item{item_no}"
        payload = {
            "machine_id": self.machine_id,
            "event": "ITEM_LANDED",
            "transaction_id": item_transaction_id,
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
    # gone_since timer — ติดตามของที่หายจาก tracked
    # ─────────────────────────────────────────────

    def mark_gone(self, obj_id, now):
        """
        เรียกเมื่อ confirmed item หายจาก tracked (ถูกบัง/slat)
        เริ่มนับ gone_since ถ้ายังไม่ได้นับ
        """
        if obj_id in self.captured_items:
            item = self.captured_items[obj_id]
            if item["gone_since"] is None:
                item["gone_since"] = now
                print(
                    f"[{self.machine_id}] ⏳ item#{item['item_no']} (obj#{obj_id}) "
                    f"หายจาก ROI — เริ่มนับ gone_timer"
                )

    def mark_seen(self, obj_id, now):
        """
        เรียกเมื่อ confirmed item กลับมาปรากฏใน tracked อีกครั้ง
        - reset gone_since → ยังอยู่
        - reset land_time → hold_timeout เริ่มนับใหม่ (รอลูกค้าหยิบรอบใหม่)
        """
        if obj_id in self.captured_items:
            item = self.captured_items[obj_id]
            if item["gone_since"] is not None:
                gone_duration = now - item["gone_since"]
                print(
                    f"[{self.machine_id}] ✅ item#{item['item_no']} (obj#{obj_id}) "
                    f"กลับมาปรากฏ (หายไป {gone_duration:.1f}s) — reset hold_timeout"
                )
                item["gone_since"] = None
                # reset land_time → CONFIRMED_HOLD_TIMEOUT เริ่มนับใหม่
                item["land_time"] = now

    def check_all_gone(self, now):
        """
        คืน True ถ้าทุก confirmed item หายนานเกิน CONFIRMED_ITEM_GONE_TIMEOUT
        → ถือว่าของถูกหยิบออกจริง → ควร reset
        คืน False ถ้ายังมี item ที่ gone_since = None (ยังอยู่)
        หรือ item ที่หายไปยังไม่ครบ timeout
        """
        if not self.captured_items:
            return False
        for obj_id, item in self.captured_items.items():
            if item["gone_since"] is None:
                return False  # ยังมีของที่เห็นอยู่
            elapsed = now - item["gone_since"]
            if elapsed < CONFIRMED_ITEM_GONE_TIMEOUT:
                return False  # หายไปแต่ยังไม่ครบ timeout
        return True  # ทุกชิ้นหายนานพอ → หายจริง

    # ─────────────────────────────────────────────
    # helpers
    # ─────────────────────────────────────────────

    def reset(self):
        self._reset_fields()

    def release_item(self, obj_id):
        """
        เอา item ที่ confirm แล้วออกจาก captured_items หลังของออก ROI
        ไม่ reset transaction — ระบบยังพร้อมรับของชิ้นใหม่ใน EVIDENCE_CAPTURED
        คืนค่า True ถ้า captured_items ว่างแล้ว (ของออกหมดแล้ว)
        """
        if obj_id in self.captured_items:
            item_no = self.captured_items[obj_id]["item_no"]
            del self.captured_items[obj_id]
            print(
                f"[{self.machine_id}] 👋 item#{item_no} (obj#{obj_id}) "
                f"ออกจาก ROI แล้ว — released"
            )
        return len(self.captured_items) == 0

    def item_count(self):
        """จำนวนชิ้นที่จับได้ใน transaction นี้"""
        return len(self.captured_items)

    def is_obj_captured(self, obj_id):
        return obj_id in self.captured_items

    def _ts(self, t):
        return datetime.fromtimestamp(t).strftime("%H:%M:%S")
