import cv2
import numpy as np
import time
import argparse
from config import (
    FRAME_W,
    FRAME_H,
    CAMERA_INDEX,
    MIN_AREA,
    GROUP_DIST,
    DROP_TIMEOUT,
    CONFIRM_TIME,
    CONFIRMED_HOLD_TIMEOUT,
    MACHINE_ID,
    HEADLESS,
    # SEND_INTERVAL,
    MAX_BLOB_ROI_RATIO,
)
import threading
from api.client import fetch_remote_roi, push_default_roi, register_machine
from api.retry_queue import start_retry_thread
from core.tracker import MemoryTracker, group_close_boxes
from core.state_machine import VendingStateMachine
from core.roi import ROIManager
from utils.logger import get_logger
from utils.disk_cleanup import start_cleanup_thread

# from api.sent_frame import send_frame

logger = get_logger("main")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine", type=str, default=MACHINE_ID)
    args = parser.parse_args()

    print(f"🖥️ ระบบทำงานในชื่อตู้: {args.machine}")
    print(f"🖥️ โหมด: {'HEADLESS (Pi)' if HEADLESS else 'DISPLAY (PC)'}")

    start_cleanup_thread()
    start_retry_thread()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    roi_manager = ROIManager(actual_w, actual_h, config_path="data/roi_config.json")

    threading.Thread(
        target=register_machine,
        args=(args.machine,),
        daemon=True,
    ).start()

    threading.Thread(
        target=push_default_roi,
        args=(args.machine, "data/roi_config.json"),
        daemon=True,
    ).start()

    tracker = MemoryTracker()
    sm = VendingStateMachine()
    sm.machine_id = args.machine

    def roi_polling_task():
        while True:
            try:
                fetch_remote_roi(sm.machine_id)
            except Exception as e:
                print(f"⚠️ roi_polling_task error: {e}")
            time.sleep(10)

    threading.Thread(target=roi_polling_task, daemon=True).start()

    bg_np = None
    LR = 0.1
    MOT_THRESH = 25
    bg_frozen = False
    bg_frozen_snapshot = None  # snapshot ของ bg ตอนที่ freeze (ตอนเจอของชิ้นแรก)
    RECONNECT_DELAY = 2

    # [BUG FIX: มือถูก snapshot เป็น background ตอน reset]
    # หลัง do_reset() มือผู้ใช้อาจยังอยู่ในเฟรม ถ้า bg_np = None ทันที
    # เฟรมถัดไปจะ snapshot มือเป็น background ใหม่ → พอมือถอยออกกลายเป็น blob
    # แก้: ไม่ล้าง bg_np แต่ unfreeze ให้ re-learn ช้าๆ + ล็อก grace period
    # ระหว่าง grace period ห้าม trigger DROP_DETECTED ใหม่
    # เพื่อให้ background ดูดมือเข้าไปก่อน แล้วค่อยรับ motion ใหม่
    RESET_GRACE_PERIOD = 1.5  # วินาที (ปรับได้ถ้าต้องการ)
    LR_RELEARN = 0.3  # learning rate เร็วขึ้นระหว่าง grace เพื่อดูดมือเข้า bg
    reset_grace_until = 0.0  # timestamp สิ้นสุด grace period

    last_send_time = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️ กล้องหลุด กำลัง reconnect...")
            cap.release()
            time.sleep(RECONNECT_DELAY)
            cap = cv2.VideoCapture(CAMERA_INDEX)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
            bg_np = None
            bg_frozen = False
            bg_frozen_snapshot = None
            reset_grace_until = 0.0
            continue

        now = time.time()

        # if now - last_send_time >= SEND_INTERVAL:
        #     send_frame(frame)
        #     last_send_time = now

        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)

        if bg_np is None:
            bg_np = frame_gray.copy()
            continue

        diff = cv2.absdiff(frame_gray, bg_np)
        fgmask = np.where(diff > MOT_THRESH, np.uint8(255), np.uint8(0))

        if not bg_frozen:
            # [BUG FIX] ระหว่าง grace period re-learn เร็วขึ้นเพื่อดูดมือเข้า background
            # ก่อนที่ระบบจะเปิดรับ motion ใหม่
            lr = LR_RELEARN if now < reset_grace_until else LR
            cv2.addWeighted(bg_np, 1 - lr, frame_gray, lr, 0, dst=bg_np)

        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, k5)
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_DILATE, k5, iterations=2)

        roi_manager.reload_if_changed()
        roi_mask = roi_manager.build_mask(fgmask.shape)
        fgmask = cv2.bitwise_and(fgmask, roi_mask)

        # ── LARGE MOTION CHECK per-area (env change / แสง / bg เปลี่ยน) ────────
        # ตรวจแต่ละ ROI area ว่า motion blob รวมใหญ่เกิน MAX_BLOB_ROI_RATIO หรือไม่
        # ถ้าใหญ่เกิน → ถือว่าเป็น env change ไม่ใช่ของจริงที่ตก
        large_motion_detected = False
        roi_areas = roi_manager.get_roi_areas(fgmask.shape)
        for roi_area in roi_areas:
            area_fgmask = cv2.bitwise_and(fgmask, roi_area["mask"])
            blob_px = int(cv2.countNonZero(area_fgmask))
            if blob_px > roi_area["area_px"] * MAX_BLOB_ROI_RATIO:
                large_motion_detected = True
                print(
                    f"⚡ Large motion detected — "
                    f"blob={blob_px}px / roi={roi_area['area_px']}px "
                    f"({blob_px / roi_area['area_px'] * 100:.0f}%) "
                    f"→ env change"
                )
                break

        if large_motion_detected:
            if sm.state != "IDLE" and bg_frozen_snapshot is not None:
                # restore bg กลับไปที่ตอน freeze เพื่อให้ของเดิมกลับมาเห็น
                bg_np = bg_frozen_snapshot.copy()
                print("🔄 BG restored to frozen snapshot")

                # อัปเดต mark_seen สำหรับ confirmed items
                for oid in list(sm.captured_items.keys()):
                    sm.mark_seen(oid, now)

                # large motion blob นี้ไม่ส่งเข้า tracker ต่อ
                # แต่ยังให้ tracker update ด้วย detected ที่กรอง large blob ออกแล้ว
                # → ของเดิมที่ track อยู่จะยังคงอยู่ใน tracker (ghost tolerance)
            # ทั้ง IDLE และ non-IDLE → กรอง blob ที่ใหญ่เกิน threshold ออกจาก raw_boxes
            # per-area: blob จะถูกกรองออกถ้ามันใหญ่เกิน threshold ของ area ที่มันอยู่
            all_contours, _ = cv2.findContours(
                fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            raw_boxes = []
            for c in all_contours:
                if cv2.contourArea(c) <= MIN_AREA:
                    continue
                bx, by, bw, bh = cv2.boundingRect(c)
                blob_area = bw * bh
                # เช็คว่า blob นี้ใหญ่เกิน threshold ของ area ไหนบ้าง
                is_large = False
                for roi_area in roi_areas:
                    if blob_area > roi_area["area_px"] * MAX_BLOB_ROI_RATIO:
                        is_large = True
                        break
                if not is_large:
                    raw_boxes.append((bx, by, bw, bh))
        else:
            contours, _ = cv2.findContours(
                fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            raw_boxes = [
                cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > MIN_AREA
            ]

        # ── MULTI-ITEM: ไม่ตัดเหลือแค่ชิ้นเดียวอีกต่อไป ──────────────────────
        # group_close_boxes รวมกล่องที่ใกล้กัน (เผื่อของชิ้นเดียวแตกเป็นหลาย contour)
        # แต่ถ้ามีหลายกลุ่มที่ห่างกัน → เก็บทุกกลุ่มไว้เป็น candidate แยกกัน
        merged = group_close_boxes(raw_boxes, max_dist=GROUP_DIST)
        # ลบ biggest-only filter ออก → รักษาทุก merged box
        # ─────────────────────────────────────────────────────────────────────

        detected = [(int(x + w / 2), int(y + h / 2), w, h) for x, y, w, h in merged]
        tracked = tracker.update(detected)

        motion_in_roi = any(
            obj["state"] in ("MOVING", "DETECTING", "SHAPE_CONFIRMED")
            or "WAITING" in obj["state"]
            for obj in tracked.values()
        )

        def do_reset():
            sm.reset()
            tracker.clear_all()
            nonlocal bg_frozen, bg_np, reset_grace_until
            bg_frozen = False
            # [BUG FIX: มือถูก snapshot เป็น background ตอน reset]
            # เดิม: bg_np = None → เฟรมถัดไป snapshot มือเป็น background ใหม่ทันที
            # ใหม่: ไม่ล้าง bg_np แต่ unfreeze + ตั้ง grace period
            #       ระหว่าง grace: re-learn เร็ว (LR_RELEARN) เพื่อดูดมือเข้า bg
            #       ระหว่าง grace: ห้าม trigger DROP_DETECTED ใหม่
            #       หลัง grace: กลับใช้ LR ปกติ พร้อมรับของชิ้นใหม่
            reset_grace_until = now + RESET_GRACE_PERIOD
            print(f"🌅 Background UNFROZEN — grace period {RESET_GRACE_PERIOD}s")

        # ── IDLE: ตรวจพบการเคลื่อนไหว ──────────────────────────────────────
        if motion_in_roi and sm.state == "IDLE":
            # [BUG FIX] ระหว่าง grace period ห้าม trigger ใหม่
            # มือที่กำลังถอยออกหลัง reset อาจทำให้ motion_in_roi = True
            # ต้องรอให้ background ดูดมือเข้าไปก่อน
            if now < reset_grace_until:
                remaining = reset_grace_until - now
                pass  # เงียบ (ไม่ print ทุกเฟรม)
            else:
                if not bg_frozen:
                    bg_frozen = True
                    bg_frozen_snapshot = bg_np.copy()  # snapshot bg ณ ตอน freeze
                    print("🧊 Background FROZEN — พบวัตถุใน ROI")
                sm.trigger("motion_in_ROI")

        # ── DROP_DETECTED / EVIDENCE_CAPTURED: จับของแต่ละชิ้น ─────────────
        if sm.state in ("DROP_DETECTED", "EVIDENCE_CAPTURED"):
            for obj_id, obj in tracked.items():
                # ข้ามของที่จับไปแล้ว
                if sm.is_obj_captured(obj_id):
                    continue

                # [BUG FIX: มือถูก capture เป็นของ]
                # ของที่ตกจากตู้: ตกลงมาเร็ว แล้วหยุดนิ่ง → อยู่ใน ROI นาน
                # มือ: เข้ามา → หยิบ → ออก ไม่เคยอยู่นาน
                # เงื่อนไข: object ต้องอยู่ใน ROI มาแล้วอย่างน้อย MIN_PRESENCE
                # นับจาก first_seen ถึงปัจจุบัน ก่อนจึงจะ capture ได้
                # ค่านี้ต้องมากกว่า CONFIRM_TIME เพื่อให้ครอบคลุม
                # เวลา MOVING → DETECTING → SHAPE_CONFIRMED + รอ CONFIRM_TIME
                # มือที่นิ่งสั้น ๆ แล้วออกจะไม่ผ่าน เพราะ presence รวมสั้นกว่า
                MIN_PRESENCE = CONFIRM_TIME + 1.5  # วินาที (ปรับได้)
                presence = now - obj.get("first_seen", now)
                if presence < MIN_PRESENCE:
                    continue

                # ของที่ shape stable แล้วและค้างอยู่นานพอ → capture
                if (
                    obj["state"] == "SHAPE_CONFIRMED"
                    and (now - obj.get("shape_confirmed_time", now)) >= CONFIRM_TIME
                ):
                    sm.trigger("still_in_ROI", obj_id=obj_id, frame=frame)
                    tracker.mark_confirmed(obj_id)

            # ── ตรวจ timeout ─────────────────────────────────────────────
            if sm.drop_time and (now - sm.drop_time) > DROP_TIMEOUT:
                sm.trigger("timeout")
                do_reset()

            # ── ไม่มีของค้างใน ROI เลย → ถ้ามี confirmed items ให้ gone_timer ทำงาน
            elif not tracked:
                if sm.state == "EVIDENCE_CAPTURED" and sm.captured_items:
                    # slat อาจบัง ROI ทั้งหมดจนไม่มี detection
                    # → mark ทุก confirmed item ว่าหายไป แล้วรอ gone_timer ตัดสิน
                    for oid in sm.captured_items:
                        sm.mark_gone(oid, now)
                    if sm.check_all_gone(now):
                        print("✅ ของออกจาก ROI ทั้งหมด (gone_timer) → RESET")
                        do_reset()
                else:
                    print("🔄 Frame ว่าง — ไม่มีของค้างใน ROI → reset กลับ IDLE")
                    do_reset()

        # ── EVIDENCE_CAPTURED: แสดงผลและรอ reset อัตโนมัติ ─────────────────
        if sm.state == "EVIDENCE_CAPTURED":
            all_gone = True
            for obj_id, item_info in sm.captured_items.items():
                landed_obj = tracked.get(obj_id)
                # วาดกรอบเฉพาะของที่ยังเห็นอยู่จริง (ไม่ใช่ ghost และ gone_since = None)
                item_visible = (
                    landed_obj is not None
                    and landed_obj.get("ghost_frames", 0) == 0
                    and item_info.get("gone_since") is None
                )
                if item_visible:
                    all_gone = False
                    # วาดกรอบสีเขียว (confirmed)
                    cx, cy = landed_obj["centroid"]
                    w, h = landed_obj["shape"]
                    latest_land = max(
                        sm.captured_items.values(), key=lambda i: i["land_time"]
                    )["land_time"]
                    hold_elapsed = now - latest_land
                    time_left = max(0, CONFIRMED_HOLD_TIMEOUT - hold_elapsed)
                    cv2.rectangle(
                        frame,
                        (cx - w // 2, cy - h // 2),
                        (cx + w // 2, cy + h // 2),
                        (0, 255, 0),
                        3,
                    )
                    cv2.putText(
                        frame,
                        f"#{item_info['item_no']} CONFIRMED ({time_left:.0f}s)",
                        (cx - w // 2, cy - h // 2 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.40,
                        (0, 255, 0),
                        1,
                    )

            # force-reset: ทุก confirmed item หายจาก ROI หรือ hold timeout เกิน
            if sm.captured_items:
                latest_item = max(
                    sm.captured_items.values(), key=lambda i: i["land_time"]
                )
                hold_elapsed = now - latest_item["land_time"]

                # [FIX: gone_timer] อัปเดต gone_since ของแต่ละ confirmed item
                # ตามสถานะที่ tracker เห็นในเฟรมนี้
                # - item_visible → mark_seen → reset gone_since + reset land_time
                # - ไม่เห็น → mark_gone → เริ่มนับ / ต่อ timer
                for oid in list(sm.captured_items.keys()):
                    o = tracked.get(oid)
                    item_visible = o is not None and o.get("ghost_frames", 0) == 0
                    if item_visible:
                        sm.mark_seen(oid, now)
                    else:
                        sm.mark_gone(oid, now)

                all_really_gone = sm.check_all_gone(now)
                if all_really_gone:
                    n = sm.item_count()
                    print(f"✅ ของออกจาก ROI ทั้งหมด → RESET ({n} ชิ้น)")
                    do_reset()
                elif hold_elapsed >= CONFIRMED_HOLD_TIMEOUT:
                    n = sm.item_count()
                    print(
                        f"⏰ Force reset — จับของได้ {n} ชิ้น "
                        f"(txn={sm.transaction_id})"
                    )
                    do_reset()

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

        if not HEADLESS:
            cv2.imshow("Vending System", frame)
            cv2.imshow("Motion Mask", fgmask)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("r"):
                sm.reset()
                tracker.clear_all()
                bg_np = None
                bg_frozen = False
                reset_grace_until = 0.0
        else:
            pass

    cap.release()
    if not HEADLESS:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
