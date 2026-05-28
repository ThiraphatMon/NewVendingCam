import threading
import time
import os
from datetime import datetime
from api.retry_queue import send_or_queue
from utils.image_saver import save_evidence_image
from config import CONFIRMED_ITEM_GONE_TIMEOUT, ORDER_WINDOW


class VendingStateMachine:
    def __init__(self, default_machine="VENDING_01"):
        self.machine_id = default_machine
        self._reset_fields()

    def _reset_fields(self):
        self.state = "IDLE"
        self.transaction_id = None
        self.drop_time = None

        # --- multi-item tracking ---
        self.captured_items = {}
        self.land_obj_id = None
        self.capture_time = None
        self.land_img_path = None

        # ── Order context ─────────────────────────────────────────────────────
        # None = ไม่มี order (motion ที่จับได้จะถูกแยกลง without_order folder)
        # มีค่า = มี order จาก server รออยู่
        self.current_order = None  # {"id": 1, "machine_id": "...", "qty": 2}

        # ── Order Window timer ────────────────────────────────────────────────
        self.order_window_start = None

    # ─────────────────────────────────────────────
    # order helpers — เรียกจาก main.py
    # ─────────────────────────────────────────────

    def set_order(self, order: dict):
        self.current_order = order
        print(
            f"[{self.machine_id}] 🛒 รับ order #{order['id']} "
            f"qty={order['qty']} — รอของตกใน {ORDER_WINDOW}s"
        )

    def has_order(self) -> bool:
        return self.current_order is not None

    def order_qty(self) -> int:
        if self.current_order:
            return int(self.current_order.get("qty", 0))
        return 0

    def reset_order_window(self, now: float):
        self.order_window_start = now
        print(f"[{self.machine_id}] ⏱️ order window reset → รอต่ออีก {ORDER_WINDOW}s")

    def is_order_window_expired(self, now: float) -> bool:
        if self.order_window_start is None:
            return False
        return (now - self.order_window_start) >= ORDER_WINDOW

    def finalize_order(self, frame=None):
        """
        สรุปผล order เมื่อ order_window หมดเวลา

        เปรียบเทียบ item ที่จับได้ vs qty ที่ order:
          - got == 0            → no_drop
          - got == expected     → completed
          - got != expected     → anomaly (ไม่ครบ หรือเกิน)

        บันทึกรูปสรุป (ORDER_SUMMARY) ลง with_order folder
        แล้วส่ง ORDER_RESULT event กลับ server เพื่ออัปเดต order status
        คืนค่า status string
        """
        got = self.item_count()
        expected = self.order_qty()
        order_id = self.current_order["id"] if self.current_order else None

        if got == 0:
            status = "no_drop"
        elif got == expected:
            status = "completed"
        else:
            status = "anomaly"

        print(
            f"[{self.machine_id}] 🏁 order #{order_id} จบ — "
            f"ได้ {got}/{expected} ชิ้น → {status}"
        )

        # ── รูปสรุป order — บันทึกลง with_order เสมอ ─────────────────────────
        summary_img_path = None
        if frame is not None:
            summary_img_path = save_evidence_image(
                frame,
                "ORDER_SUMMARY",
                self.transaction_id,
                has_order=True,
            )

        self._emit_order_result(order_id, status, got, expected, summary_img_path)
        return status

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

                if self.has_order():
                    self.order_window_start = now
                    print(
                        f"[{self.machine_id}] 📦 ของกำลังตก... "
                        f"(txn={self.transaction_id}) "
                        f"[order #{self.current_order['id']} "
                        f"qty={self.order_qty()} window={ORDER_WINDOW}s]"
                    )
                else:
                    print(
                        f"[{self.machine_id}] 📦 ของกำลังตก... "
                        f"(txn={self.transaction_id}) [ไม่มี order]"
                    )

        elif self.state == "DROP_DETECTED":
            if event == "still_in_ROI" and obj_id is not None:
                self._capture_item(obj_id, frame, now)

            elif event == "timeout":
                if not self.captured_items:
                    self._emit_no_drop()
                self.reset()

        elif self.state == "EVIDENCE_CAPTURED":
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
            # ── Phase 3+4: ส่ง has_order เพื่อแยก folder ─────────────────────
            img_path = save_evidence_image(
                frame,
                f"LANDED_item{item_no}",
                self.transaction_id,
                has_order=self.has_order(),
            )

        self.captured_items[obj_id] = {
            "land_time": now,
            "land_img_path": img_path,
            "item_no": item_no,
            "gone_since": None,
        }

        self.land_obj_id = obj_id
        self.capture_time = now
        self.land_img_path = img_path

        if self.state != "EVIDENCE_CAPTURED":
            self.state = "EVIDENCE_CAPTURED"

        # reset order_window ทุกครั้งที่ confirm item
        if self.has_order():
            self.reset_order_window(now)

        print(
            f"[{self.machine_id}] 📸 จับของชิ้นที่ {item_no} ได้! "
            f"obj_id={obj_id}  txn={self.transaction_id}"
        )
        self._emit_item_landed(obj_id, now, img_path, item_no)

    # ─────────────────────────────────────────────
    # emit helpers
    # ─────────────────────────────────────────────
    def _emit_item_landed(self, obj_id, land_time, image_path, item_no):
        item_transaction_id = f"{self.transaction_id}-item{item_no}"
        payload = {
            "machine_id": self.machine_id,
            "event": "ITEM_LANDED",
            "transaction_id": item_transaction_id,
            "item_no": item_no,
            "obj_id": obj_id,
            "land_time": self._ts(land_time),
            # ── Phase 3: แนบ order_id เพื่อให้ server เชื่อม transaction กับ order
            "order_id": self.current_order["id"] if self.current_order else "",
        }
        threading.Thread(
            target=send_or_queue,
            args=(payload, image_path),
            daemon=True,
        ).start()

    def _emit_no_drop(self):
        """
        ส่ง NO_DROP เมื่อ DROP_TIMEOUT หมดแบบไม่มี order
        (กรณีมี order จะใช้ finalize_order แทน)
        """
        img_path = None
        payload = {
            "machine_id": self.machine_id,
            "event": "NO_DROP",
            "transaction_id": self.transaction_id,
            "land_time": None,
            "order_id": self.current_order["id"] if self.current_order else "",
        }
        threading.Thread(
            target=send_or_queue,
            args=(payload, img_path),
            daemon=True,
        ).start()

    def _emit_order_result(self, order_id, status, got, expected, image_path):
        """
        ส่งผลสรุป order กลับ server
        server จะอัปเดต orders.status และ orders.items_detected
        """
        if order_id is None:
            return
        summary_txn = f"{self.transaction_id}-summary"
        payload = {
            "machine_id": self.machine_id,
            "event": "ORDER_RESULT",
            "transaction_id": summary_txn,
            "order_id": order_id,
            "order_status": status,
            "items_detected": got,
            "items_expected": expected,
            "land_time": self._ts(time.time()),
        }
        threading.Thread(
            target=send_or_queue,
            args=(payload, image_path),
            daemon=True,
        ).start()

    # ─────────────────────────────────────────────
    # gone_since timer
    # ─────────────────────────────────────────────

    def mark_gone(self, obj_id, now):
        if obj_id in self.captured_items:
            item = self.captured_items[obj_id]
            if item["gone_since"] is None:
                item["gone_since"] = now
                print(
                    f"[{self.machine_id}] ⏳ item#{item['item_no']} (obj#{obj_id}) "
                    f"หายจาก ROI — เริ่มนับ gone_timer"
                )

    def mark_seen(self, obj_id, now):
        if obj_id in self.captured_items:
            item = self.captured_items[obj_id]
            if item["gone_since"] is not None:
                gone_duration = now - item["gone_since"]
                print(
                    f"[{self.machine_id}] ✅ item#{item['item_no']} (obj#{obj_id}) "
                    f"กลับมาปรากฏ (หายไป {gone_duration:.1f}s) — reset hold_timeout"
                )
                item["gone_since"] = None
                item["land_time"] = now

    def check_all_gone(self, now):
        if not self.captured_items:
            return False
        for obj_id, item in self.captured_items.items():
            if item["gone_since"] is None:
                return False
            if (now - item["gone_since"]) < CONFIRMED_ITEM_GONE_TIMEOUT:
                return False
        return True

    # ─────────────────────────────────────────────
    # helpers
    # ─────────────────────────────────────────────

    def reset(self):
        self._reset_fields()

    def release_item(self, obj_id):
        if obj_id in self.captured_items:
            item_no = self.captured_items[obj_id]["item_no"]
            del self.captured_items[obj_id]
            print(
                f"[{self.machine_id}] 👋 item#{item_no} (obj#{obj_id}) "
                f"ออกจาก ROI แล้ว — released"
            )
        return len(self.captured_items) == 0

    def item_count(self):
        return len(self.captured_items)

    def is_obj_captured(self, obj_id):
        return obj_id in self.captured_items

    def _ts(self, t):
        return datetime.fromtimestamp(t).strftime("%H:%M:%S")
