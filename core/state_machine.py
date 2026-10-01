import threading
import time
import os
from datetime import datetime
from api.retry_queue import send_or_queue
from utils.image_saver import save_evidence_image
from config import ORDER_WINDOW, CAP_COUNT_TO_ORDER_QTY
from utils.logger import get_logger

logger = get_logger("state_machine")


class VendingStateMachine:
    def __init__(self, machine_id):
        self.machine_id = machine_id
        self._reset_fields()

    def _reset_fields(self):
        self.state = "IDLE"
        self.transaction_id = None
        self.drop_time = None

        # --- multi-item tracking ---
        self.captured_items = {}

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
        # เริ่มนับ order_window ทันทีที่รับ order
        # ไม่ต้องรอให้มี motion ก่อน เพื่อให้ badge countdown ขึ้นเลย
        # และถ้าหมดเวลาโดยไม่มีของตกเลย → no_drop
        self.order_window_start = time.time()
        logger.info(
            f"[{self.machine_id}] 🛒 รับ order #{order['id']} "
            f"qty={order['qty']} — เริ่มนับ {ORDER_WINDOW}s ทันที"
        )

    def has_order(self) -> bool:
        return self.current_order is not None

    def order_qty(self) -> int:
        if self.current_order:
            return int(self.current_order.get("qty", 0))
        return 0

    def reset_order_window(self, now: float):
        self.order_window_start = now
        logger.info(f"[{self.machine_id}] ⏱️ order window reset → รอต่ออีก {ORDER_WINDOW}s")

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

        logger.info(
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

        # ส่งผลสรุป order กลับ server → server อัปเดต orders.status และ items_detected
        if order_id is not None:
            self._emit(
                "ORDER_RESULT",
                f"{self.transaction_id}-summary",
                summary_img_path,
                order_id=order_id,
                order_status=status,
                items_detected=got,
                items_expected=expected,
                land_time=self._ts(time.time()),
            )
        return status

    # ─────────────────────────────────────────────
    # trigger() — เรียกจาก main loop
    # ─────────────────────────────────────────────
    def trigger(self, event, obj_id=None, frame=None, centroid=None, shape=None):
        now = time.time()

        if self.state == "IDLE":
            if event == "motion_in_ROI":
                self.state = "DROP_DETECTED"
                self.drop_time = now
                self.transaction_id = self.new_transaction_id()

                if self.has_order():
                    # order_window_start เริ่มนับตั้งแต่ set_order() แล้ว ไม่ reset ใหม่
                    elapsed = now - self.order_window_start
                    remaining = max(0, ORDER_WINDOW - elapsed)
                    logger.info(
                        f"[{self.machine_id}] 📦 ของกำลังตก... "
                        f"(txn={self.transaction_id}) "
                        f"[order #{self.current_order['id']} "
                        f"qty={self.order_qty()} เหลือ {remaining:.0f}s]"
                    )
                else:
                    logger.info(
                        f"[{self.machine_id}] 📦 ของกำลังตก... "
                        f"(txn={self.transaction_id}) [ไม่มี order]"
                    )

        elif self.state == "DROP_DETECTED":
            if event == "still_in_ROI" and obj_id is not None:
                if self.can_capture_more():
                    self._capture_item(obj_id, frame, now, centroid, shape)

            elif event == "timeout":
                if not self.captured_items:
                    # DROP_TIMEOUT หมดแบบไม่มี order (มี order จะใช้ finalize_order แทน)
                    self._emit(
                        "NO_DROP",
                        self.transaction_id,
                        land_time=None,
                        order_id=self._order_id(),
                    )
                self.reset()

        elif self.state == "EVIDENCE_CAPTURED":
            if event == "still_in_ROI" and obj_id is not None:
                if obj_id not in self.captured_items and self.can_capture_more():
                    self._capture_item(obj_id, frame, now, centroid, shape)

    def can_capture_more(self) -> bool:
        """
        ถ้ามี order และเปิด CAP_COUNT_TO_ORDER_QTY → ห้ามนับเกิน qty ที่สั่ง
        เป็น backstop กัน over-count (เช่น ของถูกชนขยับจนถูกนับซ้ำ 1→2→3)
        """
        if CAP_COUNT_TO_ORDER_QTY and self.has_order():
            return self.item_count() < self.order_qty()
        return True

    # ─────────────────────────────────────────────
    # _capture_item() — บันทึกและ emit ทีละชิ้น
    # ─────────────────────────────────────────────
    def _capture_item(self, obj_id, frame, now, centroid=None, shape=None):
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

        cx, cy = centroid if centroid else (None, None)
        w, h = shape if shape else (None, None)
        self.captured_items[obj_id] = {
            "land_time": now,
            "land_img_path": img_path,
            "item_no": item_no,
            # ── anchor geometry (สำหรับ re-baseline / displacement guard) ──
            "cx": cx,
            "cy": cy,
            "w": w,
            "h": h,
        }

        if self.state != "EVIDENCE_CAPTURED":
            self.state = "EVIDENCE_CAPTURED"

        # reset order_window ทุกครั้งที่ confirm item
        if self.has_order():
            self.reset_order_window(now)

        logger.info(
            f"[{self.machine_id}] 📸 จับของชิ้นที่ {item_no} ได้! "
            f"obj_id={obj_id}  txn={self.transaction_id}"
        )
        self._emit(
            "ITEM_LANDED",
            f"{self.transaction_id}-item{item_no}",
            img_path,
            item_no=item_no,
            obj_id=obj_id,
            land_time=self._ts(now),
            # แนบ order_id เพื่อให้ server เชื่อม transaction กับ order
            order_id=self._order_id(),
        )

    # ─────────────────────────────────────────────
    # emit helpers
    # ─────────────────────────────────────────────
    def _emit(self, event, transaction_id, image_path=None, **fields):
        """ส่ง event ขึ้น server ใน background thread (ส่งไม่ได้ → เข้า retry queue)"""
        payload = {
            "machine_id": self.machine_id,
            "event": event,
            "transaction_id": transaction_id,
            **fields,
        }
        threading.Thread(
            target=send_or_queue,
            args=(payload, image_path),
            daemon=True,
        ).start()

    # ─────────────────────────────────────────────
    # helpers
    # ─────────────────────────────────────────────

    def reset(self):
        self._reset_fields()

    @staticmethod
    def new_transaction_id():
        return datetime.now().strftime("TXN-%Y%m%d-%H%M%S")

    def item_count(self):
        return len(self.captured_items)

    def is_obj_captured(self, obj_id):
        return obj_id in self.captured_items

    def _order_id(self):
        return self.current_order["id"] if self.current_order else ""

    def _ts(self, t):
        return datetime.fromtimestamp(t).strftime("%H:%M:%S")