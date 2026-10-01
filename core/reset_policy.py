"""
core/reset_policy.py — ตัดสินว่าเมื่อไหร่ต้อง reset กลับ IDLE (รวมกติกาไว้ที่เดียว)

main เรียก decide_reset() เฉพาะตอน state = DROP_DETECTED / EVIDENCE_CAPTURED
(หลังพยายาม capture ของในเฟรมนั้นแล้ว) ลำดับความสำคัญ:

  1) "order_done"   มี order + order window หมด → สรุปผล order แล้ว reset
  2) มีของที่นับแล้ว → ห้าม DROP_TIMEOUT / frame ว่าง มาตัด
       - มี order   → รอ order window หมด (ข้อ 1) อย่างเดียว
       - ไม่มี order → "hold_timeout" ครบ CONFIRMED_HOLD_TIMEOUT โดยไม่มี motion ใหม่
                       = ไม่มีของตกเพิ่มแล้วจริง (มี motion/ของใหม่ → เริ่มนับ hold ใหม่)
  3) "drop_timeout" ไม่มี order + ยังไม่ได้ของ + เห็น motion นานเกิน DROP_TIMEOUT → ส่ง NO_DROP
  4) "empty_frame"  ไม่มี order + ยังไม่ได้ของ + ROI ว่าง (มี order → รอ window หมด)

หมายเหตุ: กรณี IDLE + order หมดโดยไม่มีของตกเลย อยู่ใน main
          เพราะต้องเช็คก่อนรับ motion ใหม่ในเฟรมเดียวกัน
"""

from config import DROP_TIMEOUT, CONFIRMED_HOLD_TIMEOUT
from core.tracker import has_active_motion


def decide_reset(sm, tracked, now):
    """คืนเหตุผลที่ต้อง reset (str) หรือ None ถ้ายังไม่ต้อง reset

    side effect: ถ้ามีของที่นับแล้ว และมีมือ/ของใหม่ขยับใน ROI
                 → เลื่อน land_time ของทุกชิ้นเป็น now (เริ่มนับ hold ใหม่)
    """
    if sm.has_order() and sm.is_order_window_expired(now):
        return "order_done"

    if sm.captured_items:
        # ── [MOTION FREEZE] มือ/ของใหม่เข้ามาใน ROI → หยุดนับ hold timer ──
        # ของที่นับแล้วถูกกลืนเข้า bg ทันที (re-baseline) จึงไม่ตรวจ "ของหายจาก ROI"
        # แต่ใช้ "ไม่มี motion ใหม่ครบ hold timeout" แทน
        active = has_active_motion(tracked, sm.captured_items)
        if active:
            for item_info in sm.captured_items.values():
                item_info["land_time"] = now
            return None
        if sm.has_order():
            return None  # hold timeout ไม่ตัดก่อน order window
        latest_land = max(i["land_time"] for i in sm.captured_items.values())
        if now - latest_land >= CONFIRMED_HOLD_TIMEOUT:
            return "hold_timeout"
        return None

    if not sm.has_order() and sm.drop_time and (now - sm.drop_time) > DROP_TIMEOUT:
        return "drop_timeout"

    # มี order (และ window ยังไม่หมด) → ของอาจยังไม่ตก ให้รอจน window หมดเอง
    if not tracked and not sm.has_order():
        return "empty_frame"

    return None
