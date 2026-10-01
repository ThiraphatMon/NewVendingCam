"""
main.py — main loop ของ VendingCam

ลำดับต่อเฟรม: อ่านเฟรม → background/diff → mask → ก้อน → tracker → ตัดสินใจ (state) → วาด
รายละเอียดแต่ละขั้นอยู่ใน core/ (frame_source, background, detect, tracker, reset_policy)
"""

import argparse
import threading
import time
import cv2
import numpy as np
import config
from config import (
    FRAME_W, FRAME_H, CAMERA_INDEX, MACHINE_ID, HEADLESS, SEND_INTERVAL, ROI_CONFIG_PATH,
    MOT_THRESH, MIN_AREA, MAX_BLOB_ROI_RATIO,
    MORPH_OPEN_KSIZE, MORPH_DILATE_KSIZE, MORPH_DILATE_ITER,
    GROUP_MODE, GROUP_DIST, GROUP_OVERLAP_PAD,
    CAPTURE_HOLD_SEC, CONFIRMED_HOLD_TIMEOUT,
)
from api.client import push_default_roi, register_machine, send_frame, start_roi_polling
from api.order_listener import start_order_listener, get_pending_order, clear_pending_order
from api.retry_queue import start_retry_thread
from core.background import BackgroundModel, find_env_change
from core.detect import build_fgmask, contour_boxes, drop_large_boxes, group_close_boxes
from core.frame_source import FrameSource
from core.reset_policy import decide_reset
from core.roi import ROIManager
from core.state_machine import VendingStateMachine
from core.tracker import MemoryTracker, is_motion_in_roi
from utils.disk_cleanup import start_cleanup_thread
from ui.overlay import render_overlay
from utils.logger import get_logger

logger = get_logger("main")


def start_services(machine_id):
    """เริ่ม background thread ทั้งหมด
    (ต้องเรียกหลังสร้าง ROIManager — มันสร้างไฟล์ ROI default ให้ก่อน push ขึ้น server)"""
    start_cleanup_thread()
    start_retry_thread()
    start_order_listener()
    threading.Thread(target=register_machine, args=(machine_id,), daemon=True).start()
    threading.Thread(
        target=push_default_roi, args=(machine_id, ROI_CONFIG_PATH), daemon=True
    ).start()
    start_roi_polling(machine_id)


def detect_objects(diff, roi_manager):
    """diff → motion mask ใน ROI → กล่องของ (รวมก้อนที่แตกแล้ว)
    คืน (fgmask, detected[(cx, cy, w, h)], env_change)"""
    # OPEN (ลบ noise จุดเล็ก) → DILATE (เชื่อม mask ชิ้นเดียวที่ขาด) — ดู core/detect.py
    fgmask = build_fgmask(
        diff, MOT_THRESH, MORPH_OPEN_KSIZE, MORPH_DILATE_KSIZE, MORPH_DILATE_ITER
    )
    roi_manager.reload_if_changed()
    fgmask = cv2.bitwise_and(fgmask, roi_manager.build_mask(fgmask.shape))

    # [NOISE] contour เล็กกว่า MIN_AREA ถูกตัดทิ้ง
    # [ENV CHANGE] ก้อนใหญ่เกิน MAX_BLOB_ROI_RATIO ของ ROI = แสง/bg เปลี่ยน → ไม่ส่งเข้า tracker
    roi_areas = roi_manager.get_roi_areas(fgmask.shape)
    env_change = find_env_change(fgmask, roi_areas)
    raw_boxes = contour_boxes(fgmask, MIN_AREA)
    if env_change:
        raw_boxes = drop_large_boxes(raw_boxes, roi_areas, MAX_BLOB_ROI_RATIO)

    # [MULTI-ITEM] รวมกล่องที่ใกล้กัน (ของชิ้นเดียวแตกหลาย contour)
    # แต่กลุ่มที่ห่างกันยังแยกเป็นหลายชิ้น
    merged = group_close_boxes(
        raw_boxes, max_dist=GROUP_DIST, overlap_pad=GROUP_OVERLAP_PAD, mode=GROUP_MODE
    )
    detected = [(int(x + w / 2), int(y + h / 2), w, h) for x, y, w, h in merged]
    return fgmask, detected, env_change


def capture_landed(sm, tracked, tracker, bg, frame, frame_gray, now):
    """[CAPTURE-ON-LANDING] จับของที่ลงจอดแล้ว (นิ่ง) ครบ CAPTURE_HOLD_SEC — สูงสุด 1 ชิ้นต่อเฟรม

    ของที่กำลังตกจะขยับ (MOVING/DETECTING) → ยังไม่จับ
    นิ่งครบ LANDING_STABLE_FRAMES → SHAPE_CONFIRMED → นิ่งต่ออีก CAPTURE_HOLD_SEC → capture
    """
    for obj_id, obj in tracked.items():
        if sm.is_obj_captured(obj_id):
            continue
        if (
            obj["state"] == "SHAPE_CONFIRMED"
            and (now - obj.get("shape_confirmed_time", now)) >= CAPTURE_HOLD_SEC
        ):
            # capture + นับเพิ่ม (ตกที่เดิม = ชิ้นใหม่ ไม่ต้องกันนับซ้ำ)
            sm.trigger(
                "still_in_ROI", obj_id=obj_id, frame=frame,
                centroid=obj["centroid"], shape=obj["shape"],
            )
            if sm.is_obj_captured(obj_id):
                # [RESET MOTION] เฟรมนี้เป็น bg ใหม่ + tracker ลืมของชิ้นนี้ทันที
                # → ของชิ้นถัดไป (แม้ตกทับที่เดิม) เป็น motion ใหม่ในเฟรมสะอาด
                # กรอบ COUNTED ยังวาดได้จากพิกัดใน captured_items
                bg.rebaseline(frame_gray)
                tracker.clear_all()
                break


def reset_all(sm, tracker, bg, now):
    """reset กลับ IDLE: state machine + tracker + ปลด freeze bg แล้วเข้า grace period"""
    sm.reset()
    tracker.clear_all()
    bg.unfreeze(now)


def apply_reset(reason, sm, tracker, bg, frame, now):
    """ทำงานตามเหตุผลจาก decide_reset() แล้ว reset ทั้งระบบ"""
    if reason == "order_done":
        sm.finalize_order(frame=frame)
        clear_pending_order()
    elif reason == "drop_timeout":
        sm.trigger("timeout")  # ส่ง NO_DROP
    elif reason == "empty_frame":
        logger.info("🔄 Frame ว่าง — ไม่มีของค้างใน ROI → reset กลับ IDLE")
    elif reason == "hold_timeout":
        logger.info(
            f"⏰ ครบ {CONFIRMED_HOLD_TIMEOUT}s ไม่มีของตกเพิ่ม → "
            f"RESET (จับได้ {sm.item_count()} ชิ้น, txn={sm.transaction_id})"
        )
    reset_all(sm, tracker, bg, now)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine", type=str, default=MACHINE_ID)
    args = parser.parse_args()

    logger.info(f"🖥️ ระบบทำงานในชื่อตู้: {args.machine}")
    logger.info(f"🖥️ โหมด: {'HEADLESS (Pi)' if HEADLESS else 'DISPLAY (PC)'}")
    logger.info(config.summary())

    source = FrameSource(CAMERA_INDEX)
    roi_manager = ROIManager(FRAME_W, FRAME_H, config_path=ROI_CONFIG_PATH)
    start_services(args.machine)

    # เปิดหน้าต่างแบบปรับขนาดได้ (WINDOW_NORMAL) แทน AUTOSIZE ที่ล็อกขนาดตายตัว
    if not HEADLESS:
        for name in ("Vending System", "Motion Mask"):
            cv2.namedWindow(name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(name, FRAME_W, FRAME_H)

    tracker = MemoryTracker()
    sm = VendingStateMachine(args.machine)
    bg = BackgroundModel()
    last_send_time = 0

    while True:
        # ── 1) อ่านเฟรม ─────────────────────────────────────────────────────
        frame = source.read()
        if frame is None:
            bg.clear()  # กล้องหลุด → เริ่ม background ใหม่
            continue
        now = time.time()

        # ส่งภาพสดขึ้น dashboard (SEND_INTERVAL=0 = ปิด)
        if SEND_INTERVAL > 0 and now - last_send_time >= SEND_INTERVAL:
            send_frame(sm.machine_id, frame)
            last_send_time = now

        # ── 2) background → diff ────────────────────────────────────────────
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        diff = bg.update(frame_gray, now, idle=(sm.state == "IDLE"))
        if diff is None:
            continue

        # ── 3) mask → ก้อน → tracker ─────────────────────────────────────────
        fgmask, detected, env_change = detect_objects(diff, roi_manager)
        if env_change and sm.state != "IDLE" and bg.restore_snapshot():
            # รีเซ็ต hold timeout ของของที่นับแล้ว (กันตัดระหว่างจัดการ env change)
            for item_info in sm.captured_items.values():
                item_info["land_time"] = now
        tracked = tracker.update(detected)

        # ── 4) ตัดสินใจ ──────────────────────────────────────────────────────
        # IDLE: รับ order จาก server (ถ้ามี)
        if sm.state == "IDLE" and not sm.has_order():
            pending = get_pending_order()
            if pending is not None:
                sm.set_order(pending)

        # IDLE: มี order แต่หมดเวลาโดยไม่มีของตกเลย → no_drop
        # (reset เฉพาะ state machine — bg ยังไม่ถูก freeze จึงไม่ต้องเข้า grace)
        if sm.state == "IDLE" and sm.has_order() and sm.is_order_window_expired(now):
            logger.info(f"[{sm.machine_id}] ⏰ order window หมด — ไม่มีของตกเลย → no_drop")
            if sm.transaction_id is None:
                sm.transaction_id = sm.new_transaction_id()
            sm.finalize_order(frame=frame)
            clear_pending_order()
            sm.reset()

        # IDLE: เริ่มมีของตก → freeze bg แล้วเข้า DROP_DETECTED
        # (ระหว่าง grace period หลัง reset ห้าม trigger — มือที่ถอยออกอาจถูกนับเป็น motion)
        if sm.state == "IDLE" and is_motion_in_roi(tracked) and not bg.in_grace(now):
            bg.freeze()
            sm.trigger("motion_in_ROI")

        # กำลังรับของ: จับของที่ลงจอด แล้วดูว่าถึงเวลา reset หรือยัง
        if sm.state in ("DROP_DETECTED", "EVIDENCE_CAPTURED"):
            capture_landed(sm, tracked, tracker, bg, frame, frame_gray, now)
            reason = decide_reset(sm, tracked, now)
            if reason:
                apply_reset(reason, sm, tracker, bg, frame, now)

        # ── 5) วาด / แสดงผล (เฉพาะโหมด DISPLAY) ──────────────────────────────
        if not HEADLESS:
            render_overlay(frame, sm, tracked, roi_manager, bg.frozen, now, FRAME_W, FRAME_H)

        source.pace()

        if not HEADLESS:
            cv2.imshow("Vending System", frame)
            cv2.imshow("Motion Mask", fgmask)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("r"):
                # reset ด้วยมือ: ล้าง state + tracker + background ทั้งหมด (เหมือนกล้องหลุด)
                sm.reset()
                tracker.clear_all()
                bg.clear()

    source.release()
    if not HEADLESS:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
