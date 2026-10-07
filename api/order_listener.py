import threading
import time
import json
import websocket
from config import MACHINE_ID, WS_URL, WS_RECONNECT_SEC
from utils.logger import get_logger

logger = get_logger("order_listener")

# order ที่รอดำเนินการอยู่ (None = ไม่มี order)
# ใช้ lock เพราะ main loop กับ ws thread อ่าน/เขียนพร้อมกัน
_lock = threading.Lock()
_pending_order = None  # {"id": 1, "machine_id": "VENDING_01", "qty": 2}


def get_pending_order():
    """main loop เรียกเพื่อดู order ที่รอดำเนินการ"""
    with _lock:
        return _pending_order


def clear_pending_order():
    """เรียกเมื่อ order เสร็จแล้ว (completed / anomaly / no_drop)"""
    global _pending_order
    with _lock:
        _pending_order = None
        logger.info("pending_order cleared")


def _on_message(ws, message):
    global _pending_order
    try:
        data = json.loads(message)
    except Exception:
        return

    if data.get("type") != "new_order":
        return  # ไม่สนใจ message type อื่น เช่น machine_updated

    order = data.get("order", {})

    # กรอง machine_id — broadcast มาหาทุก Pi แต่เราสนใจเฉพาะของตัวเอง
    if order.get("machine_id") != MACHINE_ID:
        return

    with _lock:
        if _pending_order is not None:
            # มี order ค้างอยู่ → reject (Phase 4 จะส่งกลับ server ด้วย)
            logger.warning(
                f"order #{_pending_order['id']} still pending "
                f"-> reject order #{order.get('id')}"
            )
            return

        _pending_order = order
        logger.info(
            f"order #{order.get('id')} received " f"qty={order.get('qty')} from server"
        )


def _on_error(ws, error):
    logger.warning(f"WebSocket error: {error}")


def _on_close(ws, close_status_code, close_msg):
    logger.warning("WebSocket connection closed")


def _on_open(ws):
    logger.info(f"WebSocket connected -> {WS_URL}")


def _run_forever():
    """loop reconnect อัตโนมัติถ้าหลุด"""
    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            ws.run_forever()
        except Exception as e:
            logger.warning(f"WebSocket exception: {e}")
        logger.info(f"reconnect in {WS_RECONNECT_SEC}s...")
        time.sleep(WS_RECONNECT_SEC)


def start_order_listener():
    """เรียกจาก main.py ตอน startup — รัน background thread"""
    t = threading.Thread(target=_run_forever, daemon=True)
    t.start()
    logger.info("order_listener thread started")
