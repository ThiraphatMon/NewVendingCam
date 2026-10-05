"""
ui/overlay.py — วาดข้อมูล debug ลงบนเฟรม (ใช้เฉพาะโหมด DISPLAY / HEADLESS=0 บน PC)

ไม่มีผลต่อการนับของ — บน Orange Pi (HEADLESS=1) ไม่ถูกเรียกเลย
แสดง: ROI, กรอบวัตถุใน tracker, state ของรอบ, cycle_id สั้น, ยอดวันนี้, สถานะ Redis / กล้อง
"""

import cv2

from core.cycle import ACTIVE, BLOCKED_WAIT_STOP, CONFIRMED_WAIT_STOP

FONT = cv2.FONT_HERSHEY_SIMPLEX

_STATE_COLORS = {
    ACTIVE: (0, 200, 255),
    CONFIRMED_WAIT_STOP: (0, 255, 0),
    BLOCKED_WAIT_STOP: (0, 0, 255),
}

_OBJ_COLORS = {
    "SHAPE_CONFIRMED": (0, 255, 0),
    "MOVING": (0, 0, 255),
    "DETECTING": (0, 140, 255),
}


def _status_text(ok, up_text, down_text):
    if ok is None:
        return "...", (150, 150, 150)
    return (up_text, (0, 200, 0)) if ok else (down_text, (0, 0, 255))


def render_overlay(frame, view, tracked, roi_manager, frame_w, frame_h):
    """view: dict จาก App.view() — state, watching, cycle_id, today_count, redis_up, camera_ok, bg_frozen, keyboard"""
    roi_manager.draw(frame)

    # ── กรอบวัตถุใน tracker ─────────────────────────────────────────────────
    for obj_id, obj in tracked.items():
        cx, cy = obj["centroid"]
        w, h = obj["shape"]
        color = _OBJ_COLORS.get(obj["state"], (0, 0, 255))
        cv2.rectangle(frame, (cx - w // 2, cy - h // 2), (cx + w // 2, cy + h // 2), color, 2)
        cv2.putText(
            frame, f"ID:{obj_id} {obj['state'][:12]}",
            (cx - w // 2, cy - h // 2 - 6), FONT, 0.38, color, 1,
        )

    # ── กล่องสถานะ (ขวาบน) ──────────────────────────────────────────────────
    state = view["state"]
    label = f"{state} (watch)" if view.get("watching") else state
    cv2.rectangle(frame, (frame_w - 265, 5), (frame_w - 5, 120), (20, 20, 20), -1)
    cv2.putText(
        frame, label, (frame_w - 255, 30), FONT, 0.55,
        _STATE_COLORS.get(state, (150, 150, 150)), 2,
    )
    cycle = view["cycle_id"][:8] if view["cycle_id"] else "-"
    cv2.putText(frame, f"cycle: {cycle}", (frame_w - 255, 55), FONT, 0.5, (220, 220, 220), 1)
    cv2.putText(
        frame, f"today: {view['today_count']}", (frame_w - 255, 80), FONT, 0.55, (0, 255, 200), 2,
    )
    redis_txt, redis_color = _status_text(view["redis_up"], "redis OK", "redis DOWN")
    if view["keyboard"]:
        redis_txt, redis_color = "keyboard", (200, 200, 0)
    cam_txt, cam_color = _status_text(view["camera_ok"], "cam OK", "cam LOST")
    cv2.putText(frame, redis_txt, (frame_w - 255, 108), FONT, 0.45, redis_color, 1)
    cv2.putText(frame, cam_txt, (frame_w - 130, 108), FONT, 0.45, cam_color, 1)

    # ── ล่างซ้าย ─────────────────────────────────────────────────────────────
    if view["bg_frozen"]:
        cv2.putText(frame, "BG FROZEN", (10, frame_h - 15), FONT, 0.5, (255, 200, 0), 1)
    cv2.putText(
        frame, "s=START  x=STOP  r=reset bg  q=quit",
        (10, frame_h - 35), FONT, 0.45, (200, 200, 200), 1,
    )
