"""
ui/overlay.py — วาดข้อมูล debug ลงบนเฟรม (ใช้เฉพาะโหมด DISPLAY / HEADLESS=0 บน PC)

ไม่มีผลต่อการนับของ — บน Orange Pi (HEADLESS=1) ไม่ถูกเรียกเลย
"""

import cv2
from config import CONFIRMED_HOLD_TIMEOUT, ORDER_WINDOW


def draw_captured_items(frame, sm):
    """วาดกรอบของที่ confirmed แล้ว (ใช้เฉพาะโหมด DISPLAY).

    หลัง capture ของถูกกลืนเข้า bg (re-baseline) และ tracker ถูกล้างทุกครั้ง
    → ของที่นับแล้วไม่อยู่ใน tracker อีก จึงวาดกรอบจากพิกัดที่จำไว้ใน captured_items
    """
    for item_info in sm.captured_items.values():
        if item_info.get("cx") is None or not item_info.get("w"):
            continue
        cx, cy = int(item_info["cx"]), int(item_info["cy"])
        w, h = int(item_info["w"]), int(item_info["h"])
        cv2.rectangle(
            frame,
            (cx - w // 2, cy - h // 2),
            (cx + w // 2, cy + h // 2),
            (0, 200, 0),
            2,
        )
        cv2.putText(
            frame,
            f"#{item_info['item_no']} COUNTED",
            (cx - w // 2, cy - h // 2 - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.40,
            (0, 200, 0),
            1,
        )


def render_overlay(frame, sm, tracked, roi_manager, bg_frozen, now, actual_w, actual_h):
    """วาด ROI + badges + กรอบ tracked objects ลงบน frame (ใช้เฉพาะโหมด DISPLAY)."""
    # ── วาด ROI + state badge ───────────────────────────────────────────
    roi_manager.draw(frame)
    color = (
        (0, 255, 0)
        if sm.state == "EVIDENCE_CAPTURED"
        else (0, 200, 255) if sm.state == "DROP_DETECTED" else (150, 150, 150)
    )

    if bg_frozen:
        cv2.putText(
            frame,
            "BG FROZEN",
            (10, actual_h - 15),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 200, 0),
            1,
        )

    # item count badge (แสดงเฉพาะตอนกำลังจับของ)
    if sm.state != "IDLE" and sm.item_count() > 0:
        badge = f"Items: {sm.item_count()}"
        cv2.putText(
            frame,
            badge,
            (10, actual_h - 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 200),
            1,
        )

    # ── order window countdown badge (ขวาล่าง) ──────────────────────────
    if sm.has_order() and sm.order_window_start is not None:
        elapsed = now - sm.order_window_start
        time_left = max(0, ORDER_WINDOW - elapsed)
        order_badge = (
            f"ORDER #{sm.current_order['id']} "
            f"{sm.item_count()}/{sm.order_qty()} "
            f"({time_left:.0f}s)"
        )
        # คำนวณ x ให้ชิดขวา
        (badge_w, badge_h), _ = cv2.getTextSize(
            order_badge, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2
        )
        badge_x = actual_w - badge_w - 10
        badge_y = actual_h - 15
        cv2.putText(
            frame,
            order_badge,
            (badge_x, badge_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 200, 255),
            2,
        )
        
        # ──  เพิ่มโค้ดส่วนนี้: แสดง Hold Timeout Countdown ที่ขวาล่าง (เฉพาะตอนไม่มีออเดอร์) ──
    elif sm.state == "EVIDENCE_CAPTURED" and sm.captured_items:
        latest_item = max(sm.captured_items.values(), key=lambda i: i["land_time"])
        
        # ตรวจสอบว่าในพื้นที่ ROI ตอนนี้มีมือหรือวัตถุใหม่กำลังขยับอยู่หรือไม่ (ถ้ามีให้ตรึงเวลาไว้เต็ม)
        has_active_motion = any(
            obj_id not in sm.captured_items
            and obj["state"] in ("MOVING", "DETECTING", "SHAPE_CONFIRMED")
            for obj_id, obj in tracked.items()
        )
        
        if has_active_motion:
            hold_time_left = CONFIRMED_HOLD_TIMEOUT
        else:
            hold_elapsed = now - latest_item["land_time"]
            hold_time_left = max(0, CONFIRMED_HOLD_TIMEOUT - hold_elapsed)
            
        # สร้างข้อความแสดงเวลาถอยหลังก่อนรีเซ็ตระบบ
        hold_badge = f"RESET IN: {hold_time_left:.0f}s"
        (badge_w, badge_h), _ = cv2.getTextSize(hold_badge, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        badge_x = actual_w - badge_w - 10
        badge_y = actual_h - 15  # ใช้พิกัดความสูงเท่ากันกับป้ายออเดอร์เพราะมันไม่แสดงพร้อมกัน
        
        # วาดข้อความสีแดง (0, 0, 255) หรือปรับสีตามชอบเพื่อให้เห็นเด่นชัด
        cv2.putText(frame, hold_badge, (badge_x, badge_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        

    cv2.rectangle(frame, (actual_w - 255, 5), (actual_w - 5, 80), (20, 20, 20), -1)
    cv2.putText(
        frame,
        sm.state,
        (actual_w - 245, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )

    # ── วาดกรอบ tracked objects ที่ยังไม่ confirmed ─────────────────────
    sc = {
        "CONFIRMED_STOP": (0, 255, 0),
        "SHAPE_CONFIRMED": (0, 255, 0),
        "MOVING": (0, 0, 255),
        "DETECTING": (0, 140, 255),
    }

    for obj_id, obj in tracked.items():
        # ข้ามของที่ confirmed แล้ว (วาดไปแล้วด้านบน)
        if sm.is_obj_captured(obj_id):
            continue
        cx, cy = obj["centroid"]
        w, h = obj["shape"]
        state = obj["state"]
        box_color = (
            (0, 165, 255) if "WAITING" in state else sc.get(state, (0, 0, 255))
        )
        cv2.rectangle(
            frame,
            (cx - w // 2, cy - h // 2),
            (cx + w // 2, cy + h // 2),
            box_color,
            2,
        )
        cv2.putText(
            frame,
            f"ID:{obj_id} {state[:12]}",
            (cx - w // 2, cy - h // 2 - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            box_color,
            1,
        )
