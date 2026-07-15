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
    CONFIRMED_HOLD_TIMEOUT,
    MACHINE_ID,
    HEADLESS,
    SEND_INTERVAL,
    MAX_BLOB_ROI_RATIO,
    ORDER_WINDOW,
    MOT_THRESH,
    MORPH_OPEN_KSIZE,
    MORPH_DILATE_KSIZE,
    MORPH_DILATE_ITER,
    GROUP_MODE,
    GROUP_OVERLAP_PAD,
    MIN_PRESENCE_SEC,
    CAPTURE_HOLD_SEC,
    REBASELINE_ON_CAPTURE,
)
import threading
from api.client import fetch_remote_roi, push_default_roi, register_machine
from api.retry_queue import start_retry_thread
from core.tracker import MemoryTracker, group_close_boxes
from core.detect import build_fgmask, contour_boxes
from core.state_machine import VendingStateMachine
from core.roi import ROIManager
from utils.disk_cleanup import start_cleanup_thread

from api.sent_frame import send_frame
from api.order_listener import (
    start_order_listener,
    get_pending_order,
    clear_pending_order,
)



def draw_captured_items(frame, sm, tracked, now):
    """วาดกรอบของที่ confirmed แล้ว (ใช้เฉพาะโหมด DISPLAY)."""
    all_gone = True
    for obj_id, item_info in sm.captured_items.items():
        landed_obj = tracked.get(obj_id)
        # วาดกรอบสด (เขียวสว่าง) เฉพาะของที่ยังเห็นอยู่จริงใน tracker (ไม่ใช่ ghost)
        # ปกติในโหมด re-baseline ของถูกกลืนเข้า bg ทันที → ตกไป branch COUNTED ด้านล่าง
        item_visible = (
            landed_obj is not None
            and landed_obj.get("ghost_frames", 0) == 0
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
        elif (
            REBASELINE_ON_CAPTURE
            and item_info.get("cx") is not None
            and item_info.get("w")
        ):
            # [RE-BASELINE] ของถูกกลืนเข้า bg แล้ว (ไม่อยู่ใน tracker)
            # → วาดกรอบจากพิกัดที่จำไว้ เพื่อให้เห็นว่านับชิ้นนี้แล้ว
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine", type=str, default=MACHINE_ID)
    args = parser.parse_args()

    print(f"🖥️ ระบบทำงานในชื่อตู้: {args.machine}")
    print(f"🖥️ โหมด: {'HEADLESS (Pi)' if HEADLESS else 'DISPLAY (PC)'}")

    start_cleanup_thread()
    start_retry_thread()
    start_order_listener()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    # หมายเหตุ: สำหรับไฟล์วิดีโอ cap.set(WIDTH/HEIGHT) จะไม่มีผล (ใช้ได้เฉพาะกล้องจริง)
    # จึงบังคับใช้ FRAME_W/FRAME_H เป็นขนาดมาตรฐานของ pipeline แล้ว resize ทุกเฟรมให้ตรง
    # เพื่อให้พิกัด ROI (ตั้งไว้ที่ 640x480) และการวาดทุกอย่างสอดคล้องกัน
    actual_w = FRAME_W
    actual_h = FRAME_H

    roi_manager = ROIManager(actual_w, actual_h, config_path="data/roi_config.json")

    # เปิดหน้าต่างแบบปรับขนาดได้ (WINDOW_NORMAL) แทน AUTOSIZE ที่ล็อกขนาดตายตัว
    if not HEADLESS:
        cv2.namedWindow("Vending System", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Vending System", actual_w, actual_h)
        cv2.namedWindow("Motion Mask", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Motion Mask", actual_w, actual_h)

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
    # MOT_THRESH ย้ายไปอยู่ใน config.py แล้ว (ปรับผ่าน .env ได้)
    bg_frozen = False
    bg_frozen_snapshot = None  # snapshot ของ bg ตอนที่ freeze (ตอนเจอของชิ้นแรก)
    RECONNECT_DELAY = 2

    # [CLEAN BG] เก็บ snapshot ของ bg ที่ clean (ไม่มี motion) ไว้ล่วงหน้า
    # เพื่อใช้ตอน freeze แทน bg_np ที่อาจถูกดูดมือเข้าไปบางส่วนแล้ว
    # update ทุกๆ CLEAN_BG_INTERVAL วินาที เฉพาะตอน IDLE + ไม่มี motion
    clean_bg = None
    clean_bg_last_update = 0.0
    CLEAN_BG_INTERVAL = 0.5  # วินาที (ปรับได้)

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

    # ── Playback pacing (เฉพาะไฟล์วิดีโอ) ─────────────────────────────────────
    # อ่านไฟล์วิดีโอด้วย OpenCV จะได้เฟรมเร็วสุดเท่าที่ลูปไหว (ไม่ผูกกับ FPS คลิป)
    # ทำให้คลิปเล่นเร็วผิดปกติ และ timer ที่อิงเวลาจริงเพี้ยน จึงต้องหน่วงตาม FPS จริง
    # กล้องจริง (CAMERA_INDEX เป็นตัวเลข) ไม่ต้องหน่วง เพราะมันส่งเฟรมตามอัตราของมันเอง
    is_video_file = isinstance(CAMERA_INDEX, str)
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if not src_fps or src_fps <= 0 or src_fps != src_fps:  # 0 / ค่าผิด / NaN
        src_fps = 30.0
    FRAME_PERIOD = 1.0 / src_fps
    if is_video_file:
        print(f"🎞️ Video file @ {src_fps:.2f} FPS → pacing playback ตามเวลาจริง")
    next_frame_deadline = time.time() + FRAME_PERIOD

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
            clean_bg = None
            clean_bg_last_update = 0.0
            reset_grace_until = 0.0
            continue

        # บังคับขนาดเฟรมให้เป็น FRAME_W x FRAME_H เสมอ (สำคัญมากสำหรับไฟล์วิดีโอ
        # ที่ cap.set ไม่มีผล) เพื่อไม่ให้หน้าต่างใหญ่เกินและให้ตรงกับพิกัด ROI
        if frame.shape[1] != actual_w or frame.shape[0] != actual_h:
            frame = cv2.resize(frame, (actual_w, actual_h))

        now = time.time()

        if now - last_send_time >= SEND_INTERVAL:
            send_frame(sm.machine_id, frame)
            last_send_time = now

        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)

        if bg_np is None:
            bg_np = frame_gray.copy()
            continue

        diff = cv2.absdiff(frame_gray, bg_np)

        if not bg_frozen:
            # [BUG FIX] ระหว่าง grace period re-learn เร็วขึ้นเพื่อดูดมือเข้า background
            # ก่อนที่ระบบจะเปิดรับ motion ใหม่
            lr = LR_RELEARN if now < reset_grace_until else LR
            cv2.addWeighted(bg_np, 1 - lr, frame_gray, lr, 0, dst=bg_np)

            # [CLEAN BG] snapshot bg ที่สะอาด เฉพาะตอน IDLE + ไม่มี motion
            # ใช้แทน bg_np ตอน freeze เพื่อให้ได้ bg ที่ไม่มีมืออยู่เลย
            no_raw_motion = (
                cv2.countNonZero(
                    np.where(diff > MOT_THRESH, np.uint8(255), np.uint8(0))
                )
                == 0
            )
            if (
                sm.state == "IDLE"
                and no_raw_motion
                and now >= reset_grace_until
                and (now - clean_bg_last_update) >= CLEAN_BG_INTERVAL
            ):
                clean_bg = bg_np.copy()
                clean_bg_last_update = now

        # สร้าง motion mask: OPEN (ลบ noise จุดเล็ก) → DILATE (เชื่อม mask ชิ้นเดียว
        # ที่ขาดให้ตันเป็นก้อนเดียว) — ดูรายละเอียดใน core/detect.py
        fgmask = build_fgmask(
            diff,
            MOT_THRESH,
            MORPH_OPEN_KSIZE,
            MORPH_DILATE_KSIZE,
            MORPH_DILATE_ITER,
        )

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

                # รีเซ็ต hold timeout ของ confirmed items (กันตัดระหว่างจัดการ large motion)
                for _oid, _item in sm.captured_items.items():
                    _item["land_time"] = now

                # large motion blob นี้ไม่ส่งเข้า tracker ต่อ
                # แต่ยังให้ tracker update ด้วย detected ที่กรอง large blob ออกแล้ว
                # → ของเดิมที่ track อยู่จะยังคงอยู่ใน tracker (ghost tolerance)
            # ทั้ง IDLE และ non-IDLE → กรอง blob ที่ใหญ่เกิน threshold ออกจาก raw_boxes
            # per-area: blob จะถูกกรองออกถ้ามันใหญ่เกิน threshold ของ area ที่มันอยู่
            # [NOISE] contour_boxes กรอง contour ที่เล็กกว่า MIN_AREA
            raw_boxes = []
            for bx, by, bw, bh in contour_boxes(fgmask, MIN_AREA):
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
            # [NOISE] กรองด้วย MIN_AREA (contour เล็กเกิน = noise → ตัดทิ้ง)
            raw_boxes = contour_boxes(fgmask, MIN_AREA)

        # ── MULTI-ITEM: ไม่ตัดเหลือแค่ชิ้นเดียวอีกต่อไป ──────────────────────
        # group_close_boxes รวมกล่องที่ใกล้กัน (เผื่อของชิ้นเดียวแตกเป็นหลาย contour)
        # แต่ถ้ามีหลายกลุ่มที่ห่างกัน → เก็บทุกกลุ่มไว้เป็น candidate แยกกัน
        merged = group_close_boxes(
            raw_boxes,
            max_dist=GROUP_DIST,
            overlap_pad=GROUP_OVERLAP_PAD,
            mode=GROUP_MODE,
        )
        # ลบ biggest-only filter ออก → รักษาทุก merged box

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

        def reset_motion_baseline():
            """[RESET MOTION] เอาเฟรมปัจจุบัน "ทั้งภาพ" มาเป็น background ใหม่
            → motion mask ว่างเปล่าทันที, ROI สะอาดเอี่ยม พร้อมจับ item ชิ้นถัดไป

            เรียกทันทีหลัง capture item สำเร็จ. ต่างจากการกลืนเฉพาะจุด (เดิม) ตรงที่
            ล้าง motion ทั้งเฟรม — env ที่เปลี่ยนจากการกระแทก (แม้ก้อนที่ไม่เชื่อมกับ
            ตัววัตถุ) ก็ถูกกลืนหมด. กรอบเขียว confirm ค้างไว้ที่ตำแหน่งเดิมได้
            เพราะมันเป็นแค่ overlay วาดจากพิกัดใน captured_items ไม่เกี่ยวกับ mask.
            """
            nonlocal bg_np, bg_frozen_snapshot
            bg_np = frame_gray.copy()
            # อัปเดต snapshot ด้วย (กันกรณี large_motion restore ดึง bg เก่ากลับมา)
            bg_frozen_snapshot = frame_gray.copy()

        # ── IDLE: รับ order จาก server (ถ้ามี และยัง IDLE อยู่) ───────────────
        if sm.state == "IDLE" and not sm.has_order():
            pending = get_pending_order()
            if pending is not None:
                sm.set_order(pending)

        # ── IDLE: มี order แต่หมดเวลาโดยไม่มีของตกเลย → no_drop ─────────────
        if sm.state == "IDLE" and sm.has_order() and sm.is_order_window_expired(now):
            print(f"[{sm.machine_id}] ⏰ order window หมด — ไม่มีของตกเลย → no_drop")
            if sm.transaction_id is None:
                import datetime

                sm.transaction_id = datetime.datetime.now().strftime(
                    "TXN-%Y%m%d-%H%M%S"
                )
            sm.finalize_order(frame=frame)
            clear_pending_order()
            sm.reset()

        # ── IDLE: ตรวจพบการเคลื่อนไหว ──────────────────────────────────────
        if motion_in_roi and sm.state == "IDLE":
            # [BUG FIX] ระหว่าง grace period ห้าม trigger ใหม่
            # มือที่กำลังถอยออกหลัง reset อาจทำให้ motion_in_roi = True
            # ต้องรอให้ background ดูดมือเข้าไปก่อน
            if now < reset_grace_until:
                pass  # เงียบ (ไม่ print ทุกเฟรม)
            else:
                if not bg_frozen:
                    bg_frozen = True
                    # [CLEAN BG] ใช้ clean_bg (bg ก่อนมือเข้า) แทน bg_np ที่อาจถูกดูดมือไปแล้ว
                    # ถ้ายังไม่มี clean_bg (เพิ่งเริ่มระบบ) → fallback ใช้ bg_np แทน
                    freeze_src = clean_bg if clean_bg is not None else bg_np
                    bg_frozen_snapshot = freeze_src.copy()
                    bg_np = freeze_src.copy()  # ดึง bg กลับไปที่ clean version
                    print("🧊 Background FROZEN — ใช้ clean_bg ก่อนมี motion")
                sm.trigger("motion_in_ROI")

        # ── DROP_DETECTED / EVIDENCE_CAPTURED: จับของแต่ละชิ้น ─────────────
        if sm.state in ("DROP_DETECTED", "EVIDENCE_CAPTURED"):
            for obj_id, obj in tracked.items():
                # ข้ามของที่จับไปแล้ว
                if sm.is_obj_captured(obj_id):
                    continue

                # ── [CAPTURE-ON-LANDING] จับทันทีที่ของ "นิ่ง" = ตกถึงที่แล้ว ──
                # ของที่กำลังตกจะเคลื่อนที่ (state = MOVING/DETECTING) → ยังไม่ capture
                # พอถึงที่แล้วจะนิ่งครบ LANDING_STABLE_FRAMES → state = SHAPE_CONFIRMED
                # = จังหวะที่ควร capture ทันที แล้วพร้อมรับชิ้นถัดไปเลย
                #
                # เดิม: ต้องรอ presence >= CONFIRM_TIME+1.5 (~2.5s) + hold อีก CONFIRM_TIME
                #       → ของชิ้นที่ 2 ที่ลูกค้าหยิบเร็ว ๆ จับไม่ทัน
                # ใหม่: presence floor แค่กัน noise แวบเดียว (MIN_PRESENCE_SEC)
                #       + hold หลังนิ่งสั้นมาก/เป็นศูนย์ (CAPTURE_HOLD_SEC)
                #       slat บังมือแล้ว จึงไม่ต้องใช้ presence ยาว ๆ กันมืออีก
                presence = now - obj.get("first_seen", now)
                if presence < MIN_PRESENCE_SEC:
                    continue

                # ของที่ลงจอดแล้ว (นิ่ง) และนิ่งครบ hold สั้น ๆ → capture
                if (
                    obj["state"] == "SHAPE_CONFIRMED"
                    and (now - obj.get("shape_confirmed_time", now)) >= CAPTURE_HOLD_SEC
                ):
                    o_cx, o_cy = obj["centroid"]
                    o_w, o_h = obj["shape"]

                    # ── capture + นับเพิ่ม (ตกที่เดิม = ชิ้นใหม่ ไม่ต้องกันนับซ้ำ) ──
                    sm.trigger(
                        "still_in_ROI", obj_id=obj_id, frame=frame,
                        centroid=(o_cx, o_cy), shape=(o_w, o_h),
                    )

                    # ── [RESET MOTION] ล้าง motion mask ทั้งหมดหลัง capture สำเร็จ ──
                    # เอาเฟรมปัจจุบัน "ทั้งภาพ" มาเป็น background ใหม่
                    # → motion mask ว่างเปล่าทันที, ROI สะอาดเอี่ยม พร้อมจับชิ้นถัดไป
                    # กรอบเขียว confirm ค้างไว้ที่ตำแหน่งเดิม (เป็นแค่ overlay ที่วาด
                    # จากพิกัดใน captured_items — ไม่เกี่ยวกับ motion mask)
                    # ของชิ้นถัดไปที่ตกลงมา (แม้ตกทับที่เดิม) จะเป็น motion ใหม่
                    # เพียงชิ้นเดียวในเฟรมสะอาด → capture เป็นชิ้นใหม่ได้
                    if REBASELINE_ON_CAPTURE and sm.is_obj_captured(obj_id):
                        reset_motion_baseline()
                        tracker.clear_all()  # เปลี่ยนเป็นคำสั่งนี้ เพื่อให้ Tracker ลืม Item 1 ไปเลยทันที
                        break

            # ── ตรวจ timeout / order_window ───────────────────────────────────
            # ลำดับความสำคัญ (priority) ของการ reset:
            #   1) order window หมดเวลา (เฉพาะมี order)  → reset
            #   2) มี confirmed item ค้างอยู่ → "ห้าม" reset ที่ block นี้เลย
            #        ปล่อยให้ block EVIDENCE_CAPTURED ด้านล่างเป็นผู้ตัดสินด้วย
            #        CONFIRMED_HOLD_TIMEOUT (นับใหม่ทุกครั้งที่มี motion/ของใหม่)
            #        → กัน DROP_TIMEOUT / frame-ว่าง มา reset เองทั้งที่ hold countdown
            #          ยังนับอยู่ (รอว่าไม่มีของตกเพิ่มแล้วจริง)
            #   3) ไม่มี order + ไม่มี confirmed item + เกิน DROP_TIMEOUT → reset
            #   4) ไม่มี confirmed item + frame ว่าง → reset
            if sm.has_order() and sm.is_order_window_expired(now):
                # order_window หมดเวลา → สรุปผล order แล้ว reset
                sm.finalize_order(frame=frame)
                clear_pending_order()
                do_reset()
            elif sm.captured_items:
                # มี confirmed item แล้ว → ให้ CONFIRMED_HOLD_TIMEOUT (block ล่าง) จัดการ
                pass
            elif (
                not sm.has_order()
                and sm.drop_time
                and (now - sm.drop_time) > DROP_TIMEOUT
            ):
                sm.trigger("timeout")
                do_reset()

            # ── ไม่มี confirmed item เลย และ frame ว่าง ──────────────────────────
            elif not tracked:
                # ── ถ้ามี order window ยังเปิดอยู่ → อย่า reset ────────────
                # ของอาจยังไม่ตกลงมา หรือกำลังตกอยู่ ให้รอจน window หมดเอง
                if sm.has_order() and not sm.is_order_window_expired(now):
                    pass  # รอต่อ
                else:
                    print("🔄 Frame ว่าง — ไม่มีของค้างใน ROI → reset กลับ IDLE")
                    do_reset()

        # ── EVIDENCE_CAPTURED: จับ timeout + reset (ทำงานทั้ง HEADLESS/DISPLAY) ─
        if sm.state == "EVIDENCE_CAPTURED":
            if not HEADLESS:
                draw_captured_items(frame, sm, tracked, now)

            # force-reset: ทุก confirmed item หายจาก ROI หรือ hold timeout เกิน
            if sm.captured_items:
                latest_item = max(
                    sm.captured_items.values(), key=lambda i: i["land_time"]
                )

                # ── [MOTION FREEZE] มือ/ของใหม่เข้ามาใน ROI → หยุดนับ timer ทั้งหมด ──
                # ตรวจจาก tracker: มี object ที่ยังไม่ confirmed (MOVING/DETECTING/SHAPE_CONFIRMED)
                # และไม่ใช่ confirmed item เดิม → ถือว่ามี "motion จริง" ที่ควร freeze
                # noise เล็กๆ บน item เดิมจะถูก tracker match กลับ id เดิม (CONFIRMED_STOP)
                # จึงไม่ถูกนับว่าเป็น motion → timer เดินปกติ
                has_active_motion = any(
                    obj_id not in sm.captured_items
                    and obj["state"] in ("MOVING", "DETECTING", "SHAPE_CONFIRMED")
                    for obj_id, obj in tracked.items()
                )

                if has_active_motion:
                    # มือ/ของใหม่เข้ามาใน ROI → หยุดนับ hold_elapsed
                    # reset land_time ของทุก item ไปที่ now = เริ่มนับ hold timeout ใหม่
                    # (รอว่าไม่มีของตกเพิ่มอีกแล้วจริง ก่อนจะ reset)
                    for oid, item_info in sm.captured_items.items():
                        item_info["land_time"] = now
                    hold_elapsed = 0.0
                    # (ไม่ print ทุก frame เพื่อไม่ spam log)
                else:
                    hold_elapsed = now - latest_item["land_time"]

                # ── ตัดสิน reset ──────────────────────────────────────────────
                # ของถูกกลืนเข้า bg ทันทีหลัง capture (re-baseline) → มองไม่เห็นของที่
                # นับแล้วอีก จึงไม่ตรวจ "ของหายจาก ROI จริง" (เป็นไปไม่ได้) แต่ใช้กติกา:
                #   - มี order  → รอ order window หมด แล้ว finalize
                #   - ไม่มี order → "ครบ hold timeout ไม่มี motion = ไม่มีของตกเพิ่ม → reset"
                #       ทุกครั้งที่มี motion/ของใหม่ land_time ถูกรีเซ็ต = นับ hold ใหม่
                if sm.has_order():
                    if sm.is_order_window_expired(now):
                        # order window หมด → สรุปผล order แล้ว reset
                        sm.finalize_order(frame=frame)
                        clear_pending_order()
                        do_reset()
                    # order ยังไม่หมด → รอต่อ (hold timeout ไม่ตัดก่อน order window)
                elif not has_active_motion and hold_elapsed >= CONFIRMED_HOLD_TIMEOUT:
                    n = sm.item_count()
                    print(
                        f"⏰ ครบ {CONFIRMED_HOLD_TIMEOUT}s ไม่มีของตกเพิ่ม → "
                        f"RESET (จับได้ {n} ชิ้น, txn={sm.transaction_id})"
                    )
                    do_reset()

        # ── วาด overlay ลงจอ (เฉพาะโหมด DISPLAY — ข้ามทั้งหมดบน Pi/HEADLESS) ──
        if not HEADLESS:
            render_overlay(
                frame, sm, tracked, roi_manager, bg_frozen, now, actual_w, actual_h
            )

        # ── pacing: หน่วงให้ไฟล์วิดีโอเล่นตามเฟรมเรตจริง ไม่เร่งเร็ว ──────────
        if is_video_file:
            sleep_time = next_frame_deadline - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)
            next_frame_deadline += FRAME_PERIOD
            # ถ้าประมวลผลช้ากว่าเฟรมเรต (deadline หลุดไปแล้ว) รีเซ็ตกันสะสมหน่วง
            if next_frame_deadline < time.time():
                next_frame_deadline = time.time() + FRAME_PERIOD

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